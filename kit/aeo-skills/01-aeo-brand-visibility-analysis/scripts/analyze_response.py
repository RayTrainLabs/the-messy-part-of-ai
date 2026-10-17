#!/usr/bin/env python3
"""
Phase 4 / 5 — Per-row scoring (mode=metrics) and gap analysis (mode=gaps).

For each (query x engine) row in raw_responses.jsonl:
  - mode=metrics:
      Run a deterministic brand-mention pre-scan, then call the judge LLM with
      templates/metrics_analysis_system_prompt.md. Validate the response, write
      to scored_rows.jsonl.
  - mode=gaps:
      Join scored row + raw row, call the judge LLM with
      templates/gap_optimization_system_prompt.md. Validate, write to gap_rows.jsonl.

Usage (metrics):
    python analyze_response.py --responses output/raw_responses.jsonl \
        --brand-profile output/brand_profile.json --mode metrics \
        --judge-provider anthropic --concurrency 6 \
        --out output/scored_rows.jsonl

Usage (gaps):
    python analyze_response.py --responses output/raw_responses.jsonl \
        --scored output/scored_rows.jsonl --brand-profile output/brand_profile.json \
        --mode gaps --judge-provider anthropic --concurrency 6 \
        --out output/gap_rows.jsonl
"""

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

THIS_DIR = Path(__file__).parent
sys.path.insert(0, str(THIS_DIR))

import providers as P  # noqa: E402

METRICS_PROMPT = THIS_DIR.parent / "templates" / "metrics_analysis_system_prompt.md"
GAPS_PROMPT    = THIS_DIR.parent / "templates" / "gap_optimization_system_prompt.md"

VALID_POSITIONS = {"Leader", "Challenger", "Alternative", "Niche", "Not competitive", "Not mentioned"}
VALID_ROLES     = {"Primary", "Secondary", "Fallback", "Avoided", "Absent"}
VALID_PRIORITY  = {"Critical", "High", "Medium", "Low"}
VALID_ASSESSMENT = {"Excellent", "Good", "Moderate", "Weak", "Not visible"}

# Defensive substitution: even with the system-prompt ban, judge LLMs sometimes
# still emit literal `{TargetBrand}`/`{Target}`/`[Brand]` tokens in long
# `optimization_action` and `_gap_details[].gap_description` strings. We replace
# those tokens post-parse with the real brand name from `brand_profile`, so the
# downstream PDF / executive summary doesn't show curly-brace placeholders.
_BRAND_PLACEHOLDER_RE = re.compile(
    r"\{(?:TargetBrand|Target|Brand|BrandName|TARGET_BRAND|target_brand|brand_name)\}"
    r"|\[(?:TargetBrand|Target|Brand|BrandName)\]"
)


def _substitute_brand_placeholders(node, real_brand):
    """Walk a JSON-shaped object and replace placeholder tokens with the real brand."""
    if isinstance(node, str):
        return _BRAND_PLACEHOLDER_RE.sub(real_brand, node)
    if isinstance(node, dict):
        return {k: _substitute_brand_placeholders(v, real_brand) for k, v in node.items()}
    if isinstance(node, list):
        return [_substitute_brand_placeholders(v, real_brand) for v in node]
    return node


# ---------- shared helpers ----------

def load_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def parse_strict_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def domain_of(url):
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def deterministic_brand_scan(text, citations, target_brand, target_aliases, competitors, target_url):
    text = text or ""
    cits = citations or []
    target_terms = [t.lower() for t in [target_brand] + (target_aliases or []) if t]
    target_domain = domain_of(target_url) if target_url else ""

    text_lower = text.lower()

    target_text_hits = 0
    for t in target_terms:
        target_text_hits += len(re.findall(rf"\b{re.escape(t)}\b", text_lower))

    target_citation_hits = 0
    if target_domain:
        for u in cits:
            if domain_of(u).endswith(target_domain) or target_domain.endswith(domain_of(u)):
                target_citation_hits += 1

    competitor_hits = {}
    for comp in (competitors or []):
        c_lower = comp.lower()
        n = len(re.findall(rf"\b{re.escape(c_lower)}\b", text_lower))
        if n > 0:
            competitor_hits[comp] = n

    return {
        "target_text_mentions":     target_text_hits,
        "target_citation_mentions": target_citation_hits,
        "target_appears":           target_text_hits + target_citation_hits > 0,
        "competitor_text_mentions": competitor_hits,
    }


# ---------- metrics mode ----------

def score_one(raw_row, brand_profile, judge_mod, prompt_template):
    target_brand = (brand_profile.get("brand_name")
                    or ((brand_profile.get("target_brand") or {}).get("name"))
                    or "")
    target_aliases = (brand_profile.get("brand_aliases")
                      or ((brand_profile.get("target_brand") or {}).get("aliases"))
                      or [])
    target_url = (brand_profile.get("url")
                  or ((brand_profile.get("target_brand") or {}).get("domain"))
                  or "")
    competitors = ((brand_profile.get("competitors") or {}).get("direct") or []) + \
                  ((brand_profile.get("competitors") or {}).get("indirect") or [])

    text_for_scan = raw_row.get("llm_answer_text") or ""
    if raw_row.get("engine_type") == "serp":
        # Concatenate AI Overview + organic snippets for SERP rows
        parts = []
        if raw_row.get("serp_ai_overview"):
            parts.append(raw_row["serp_ai_overview"])
        for r in (raw_row.get("serp_results") or []):
            if r.get("snippet"):
                parts.append(r["snippet"])
        text_for_scan = "\n".join(parts)

    hint = deterministic_brand_scan(
        text=text_for_scan,
        citations=raw_row.get("citation_urls"),
        target_brand=target_brand,
        target_aliases=target_aliases,
        competitors=competitors,
        target_url=target_url,
    )

    payload = {
        "query_tested": raw_row.get("query_tested"),
        "ai_engine":    raw_row.get("engine"),
        "llm_answer_text": raw_row.get("llm_answer_text"),
        "citation_urls":   raw_row.get("citation_urls"),
        "serp_results":    raw_row.get("serp_results"),
        "serp_ai_overview": raw_row.get("serp_ai_overview"),
        "target_brand":          target_brand,
        "target_brand_aliases":  target_aliases,
        "known_competitors":     competitors,
        "deterministic_brand_scan_hint": hint,
    }

    last_err = None
    for attempt in range(3):
        try:
            response_text = judge_mod.judge(prompt_template, payload)
            obj = parse_strict_json(response_text)
            problems = validate_metrics_obj(obj, hint, target_brand, target_aliases)
            if not problems:
                obj["row_id"] = raw_row["row_id"]
                obj["query_id"] = raw_row.get("query_id")
                obj["query_tested"] = raw_row.get("query_tested")
                obj["engine"] = raw_row.get("engine")
                obj["_judge"] = {"model": getattr(judge_mod, "JUDGE_MODEL", None),
                                  "provider": getattr(judge_mod, "PROVIDER_NAME", None)}
                return obj
            last_err = problems
            payload["_validator_feedback"] = problems
        except Exception as e:
            last_err = str(e)

    return {
        "row_id": raw_row["row_id"],
        "query_id": raw_row.get("query_id"),
        "query_tested": raw_row.get("query_tested"),
        "engine": raw_row.get("engine"),
        "_scoring_error": str(last_err)[:500],
    }


def validate_metrics_obj(obj, hint, target_brand, target_aliases):
    problems = []

    required = ["response_summary", "brand_mentioned", "brands_mentioned_list",
                "citation_frequency_score", "share_of_voice_percentage",
                "positional_authority_score", "sentiment_direction_score",
                "response_relevance_score", "market_position_type",
                "discovery_role", "positioning_narrative", "strength_score",
                "_brand_mention_counts"]
    for k in required:
        if k not in obj:
            problems.append(f"missing field: {k}")

    if not isinstance(obj.get("brand_mentioned"), bool):
        problems.append("brand_mentioned must be boolean")

    if hint.get("target_appears") and obj.get("brand_mentioned") is False:
        problems.append("deterministic scan says target appears but brand_mentioned is false")

    if obj.get("brand_mentioned") and target_brand:
        present = False
        for b in (obj.get("brands_mentioned_list") or []):
            if b and (b.lower() == target_brand.lower() or any(b.lower() == a.lower() for a in target_aliases)):
                present = True; break
        if not present:
            problems.append("brand_mentioned=true but target not in brands_mentioned_list")

    if obj.get("brand_mentioned") is False:
        for k in ["citation_frequency_score", "positional_authority_score",
                  "sentiment_direction_score", "response_relevance_score", "strength_score"]:
            if obj.get(k, 0) != 0:
                problems.append(f"{k} must be 0 when brand_mentioned is false")
        if obj.get("share_of_voice_percentage", 0.0) != 0.0:
            problems.append("share_of_voice_percentage must be 0.0 when brand_mentioned is false")

    if not isinstance(obj.get("share_of_voice_percentage"), (int, float)) or \
       not (0.0 <= float(obj.get("share_of_voice_percentage", -1)) <= 100.0):
        problems.append("share_of_voice_percentage out of range [0.0, 100.0]")
    if not isinstance(obj.get("positional_authority_score"), int) or \
       not (0 <= obj.get("positional_authority_score", -1) <= 100):
        problems.append("positional_authority_score out of range [0, 100]")
    if not isinstance(obj.get("sentiment_direction_score"), int) or \
       not (-50 <= obj.get("sentiment_direction_score", -999) <= 50):
        problems.append("sentiment_direction_score out of range [-50, 50]")
    if not isinstance(obj.get("strength_score"), int) or \
       not (0 <= obj.get("strength_score", -1) <= 10):
        problems.append("strength_score out of range [0, 10]")

    if obj.get("market_position_type") not in VALID_POSITIONS:
        problems.append(f"market_position_type invalid: {obj.get('market_position_type')}")
    if obj.get("discovery_role") not in VALID_ROLES:
        problems.append(f"discovery_role invalid: {obj.get('discovery_role')}")

    pn = obj.get("positioning_narrative") or ""
    # Rubric target is 150-250 chars. Real-world judge LLMs (especially
    # gemini-2.5-flash) routinely write 300-500 — strictly rejecting cost ~50%
    # of rows in the Country Bean test run. Strategy: AUTO-TRUNCATE the upper
    # bound (preserve the leading 250 chars + ellipsis), only reject if the
    # narrative is suspiciously short (likely a truncation / missing field).
    if len(pn) < 80:
        problems.append(f"positioning_narrative length {len(pn)} too short (<80; "
                        f"likely truncated or missing)")
    elif len(pn) > 250:
        # auto-fix: clip in place. 247 + "..." = 250 chars exact.
        obj["positioning_narrative"] = pn[:247].rstrip() + "..."

    return problems


# ---------- gaps mode ----------

def gap_one(raw_row, scored_row, brand_profile, judge_mod, prompt_template):
    target_brand = (brand_profile.get("brand_name")
                    or ((brand_profile.get("target_brand") or {}).get("name"))
                    or "")
    target_url = (brand_profile.get("url")
                  or ((brand_profile.get("target_brand") or {}).get("domain"))
                  or "")
    target_aliases = (brand_profile.get("brand_aliases")
                      or ((brand_profile.get("target_brand") or {}).get("aliases"))
                      or [])
    competitors = ((brand_profile.get("competitors") or {}).get("direct") or []) + \
                  ((brand_profile.get("competitors") or {}).get("indirect") or [])

    metrics_block = {k: v for k, v in scored_row.items()
                     if k not in ("row_id", "query_id", "query_tested", "engine", "_judge")}

    payload = {
        "query_tested": raw_row.get("query_tested"),
        "ai_engine":    raw_row.get("engine"),
        "llm_answer_text": raw_row.get("llm_answer_text"),
        "citation_urls":   raw_row.get("citation_urls"),
        "serp_results":    raw_row.get("serp_results"),
        "serp_ai_overview": raw_row.get("serp_ai_overview"),
        "target_brand":         target_brand,
        "target_brand_url":     target_url,
        "target_brand_aliases": target_aliases,
        "known_competitors":    competitors,
        "metrics":              metrics_block,
    }

    last_err = None
    for attempt in range(3):
        try:
            response_text = judge_mod.judge(prompt_template, payload)
            obj = parse_strict_json(response_text)
            # Substitute leaked placeholders BEFORE validation so the row is
            # accepted and the report later renders real brand names.
            real_brand = target_brand or "the brand"
            obj = _substitute_brand_placeholders(obj, real_brand)
            problems = validate_gaps_obj(obj, metrics_block)
            if not problems:
                obj["row_id"] = raw_row["row_id"]
                obj["query_id"] = raw_row.get("query_id")
                obj["query_tested"] = raw_row.get("query_tested")
                obj["engine"] = raw_row.get("engine")
                return obj
            last_err = problems
            payload["_validator_feedback"] = problems
        except Exception as e:
            last_err = str(e)

    return {
        "row_id": raw_row["row_id"],
        "query_id": raw_row.get("query_id"),
        "query_tested": raw_row.get("query_tested"),
        "engine": raw_row.get("engine"),
        "_gap_error": str(last_err)[:500],
    }


def validate_gaps_obj(obj, metrics):
    problems = []

    required = ["content_gap", "optimization_action", "optimization_rationale",
                "optimization_priority", "optimization_expected_impact",
                "overall_visibility_assessment", "key_insights", "_gap_details"]
    for k in required:
        if k not in obj:
            problems.append(f"missing field: {k}")

    if obj.get("optimization_priority") not in VALID_PRIORITY:
        problems.append(f"optimization_priority invalid: {obj.get('optimization_priority')}")
    if obj.get("overall_visibility_assessment") not in VALID_ASSESSMENT:
        problems.append(f"overall_visibility_assessment invalid: {obj.get('overall_visibility_assessment')}")

    ki = obj.get("key_insights") or []
    if len(ki) != 3:
        problems.append(f"key_insights must have exactly 3 items, got {len(ki)}")

    gd = obj.get("_gap_details") or []
    if not gd:
        problems.append("_gap_details must contain at least one gap")

    if metrics.get("brand_mentioned") is False:
        if not gd or gd[0].get("gap_type") != "Total Visibility Gap":
            problems.append("when brand_mentioned is false, _gap_details[0] must be Total Visibility Gap")

    impact = obj.get("optimization_expected_impact") or ""
    if impact.count(";") < 2:
        problems.append("optimization_expected_impact must contain three semicolon-separated timeframes")

    return problems


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--responses", required=True)
    ap.add_argument("--scored", help="(gaps mode) path to scored_rows.jsonl")
    ap.add_argument("--brand-profile", required=True)
    ap.add_argument("--mode", choices=["metrics", "gaps"], required=True)
    ap.add_argument("--judge-provider", default="anthropic", choices=["anthropic", "openai", "gemini"])
    ap.add_argument("--judge-model", default=None)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=None, help="for testing — only score first N rows")
    args = ap.parse_args()

    judge_mod = P.judge_provider(prefer=args.judge_provider)
    if not judge_mod:
        print("ERROR: no judge LLM available. Set ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY.",
              file=sys.stderr); sys.exit(1)
    if args.judge_model:
        # override default for this run
        try:
            judge_mod.JUDGE_MODEL = args.judge_model
        except Exception:
            pass

    with open(args.brand_profile, encoding="utf-8") as f:
        brand_profile = json.load(f)

    raw_rows = [r for r in load_jsonl(args.responses) if r.get("ok")]
    if args.limit:
        raw_rows = raw_rows[: args.limit]

    if args.mode == "metrics":
        prompt = METRICS_PROMPT.read_text(encoding="utf-8")
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        out_f = open(args.out, "w", encoding="utf-8")
        ok = err = 0
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futs = [pool.submit(score_one, r, brand_profile, judge_mod, prompt) for r in raw_rows]
            for i, fut in enumerate(as_completed(futs), start=1):
                row = fut.result()
                out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
                out_f.flush()
                if "_scoring_error" in row:
                    err += 1
                else:
                    ok += 1
                if i % 10 == 0:
                    print(f"  ... scored {i}/{len(raw_rows)}  ok={ok} err={err}", file=sys.stderr)
        out_f.close()
        print(f"\nScoring done. ok={ok} err={err}. Output -> {args.out}", file=sys.stderr)

    else:  # gaps
        if not args.scored:
            print("ERROR: --scored is required for gaps mode", file=sys.stderr); sys.exit(2)
        prompt = GAPS_PROMPT.read_text(encoding="utf-8")
        scored_rows = {r["row_id"]: r for r in load_jsonl(args.scored) if "_scoring_error" not in r}
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        out_f = open(args.out, "w", encoding="utf-8")
        ok = err = skipped = 0
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futs = []
            for r in raw_rows:
                s = scored_rows.get(r["row_id"])
                if not s:
                    skipped += 1
                    continue
                futs.append(pool.submit(gap_one, r, s, brand_profile, judge_mod, prompt))
            for i, fut in enumerate(as_completed(futs), start=1):
                row = fut.result()
                out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
                out_f.flush()
                if "_gap_error" in row:
                    err += 1
                else:
                    ok += 1
                if i % 10 == 0:
                    print(f"  ... gap-analyzed {i}/{len(futs)}  ok={ok} err={err}", file=sys.stderr)
        out_f.close()
        print(f"\nGap analysis done. ok={ok} err={err} skipped={skipped}. Output -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
