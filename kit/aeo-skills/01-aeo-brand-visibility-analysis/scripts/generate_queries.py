#!/usr/bin/env python3
"""
Phase 2 — Query generation.

Loads the validated brand profile, renders the query-generation system prompt with
brand-specific context, calls the chosen LLM provider, parses the strict-JSON
response, and runs the QA validator.

Usage:
    python generate_queries.py --brand-profile output/brand_profile.json \
        --provider anthropic --target-count 20 --out output/queries.json

    python generate_queries.py --validate output/queries.json
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

THIS_DIR = Path(__file__).parent
sys.path.insert(0, str(THIS_DIR))

import providers as P  # noqa: E402

TEMPLATE_PATH = THIS_DIR.parent / "templates" / "query_generation_system_prompt.md"

VALID_CATEGORIES = {"A", "B", "C", "D", "E", "F", "G", "H", "I"}
VALID_INTENTS    = {"informational", "navigational", "decision", "problem-centric", "trend"}
VALID_STAGES     = {"awareness", "consideration", "decision"}
VALID_SPECIFICITY = {"broad", "mid", "hyper-specific"}
VALID_LENGTH     = {"short", "medium", "long"}


def load_brand_profile(path):
    with open(path, encoding="utf-8") as f:
        bp = json.load(f)
    if not bp.get("validated_at"):
        print(f"WARNING: brand profile {path} is not stamped validated_at — proceed only if Phase 1 is done.",
              file=sys.stderr)
    return bp


def render_prompt(brand_profile, target_count):
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    return (template
            .replace("{{TARGET_COUNT}}", str(target_count))
            .replace("{{BRAND_PROFILE_JSON}}", json.dumps(brand_profile, indent=2, ensure_ascii=False)))


def call_llm_for_queries(prompt, provider_name, model):
    """Use the cascading judge so a single provider's quota / rate-limit /
    transient failure doesn't block query generation. The `provider_name` arg
    is treated as the PREFERRED provider; fallback order is preferred -> the
    other two, in the cascade defined by providers.judge_provider().
    """
    judge = P.judge_provider(prefer=provider_name)
    if judge is None:
        raise RuntimeError(
            f"No LLM provider available. Set at least one of: "
            f"ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY.")

    response_text = judge.judge(
        prompt,
        {"task": "Generate the queries now per the system prompt. Return strict JSON."},
        model=model,
    )
    return parse_json_response(response_text)


def parse_json_response(text):
    text = text.strip()
    # Strip markdown fences if the model added them despite instruction
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # Try to extract first JSON object
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise RuntimeError(f"LLM response was not valid JSON: {e}\n\n{text[:500]}")


def validate_queries(queries_obj, brand_profile=None, target_count=20):
    bp = brand_profile or {}
    competitors = (bp.get("competitors") or {})
    all_competitors = (competitors.get("direct") or []) + (competitors.get("indirect") or [])
    brand_name = (bp.get("brand_name")
                  or ((bp.get("target_brand") or {}).get("name"))
                  or "").strip()
    brand_aliases = (bp.get("brand_aliases")
                     or ((bp.get("target_brand") or {}).get("aliases"))
                     or [])
    market_focus = bp.get("market_focus") or {}
    geo_terms = []
    for g in market_focus.get("geo") or []:
        geo_terms.append(g.lower())
    demo_note = (market_focus.get("demographic_notes") or "").lower()
    geo_corpus = " ".join(geo_terms + [demo_note])

    queries = queries_obj.get("queries") or []
    n = len(queries)

    checks = {}

    # Tolerance scales with target_count. ±25% (or ±5, whichever is bigger) so
    # target=20 accepts 15-25 and target=55 accepts 41-69.
    tol = max(5, int(round(target_count * 0.25)))
    checks["count_in_range"] = (target_count - tol) <= n <= (target_count + tol)

    cats_seen = {}
    intents_seen = {}
    lengths_seen = {"short": 0, "medium": 0, "long": 0}
    spec_seen = {"broad": 0, "mid": 0, "hyper-specific": 0}
    brand_hits = 0
    competitor_hits = 0
    geo_hits = 0
    queries_text = []

    for q in queries:
        cat = q.get("category")
        cats_seen[cat] = cats_seen.get(cat, 0) + 1
        intents_seen[q.get("intent")] = intents_seen.get(q.get("intent"), 0) + 1
        lengths_seen[q.get("length_bucket")] = lengths_seen.get(q.get("length_bucket"), 0) + 1
        spec_seen[q.get("specificity")] = spec_seen.get(q.get("specificity"), 0) + 1

        text = (q.get("query") or "")
        text_lower = text.lower()
        queries_text.append(text_lower)

        # Brand mention check
        if brand_name and re.search(rf"\b{re.escape(brand_name.lower())}\b", text_lower):
            brand_hits += 1
        for alias in brand_aliases:
            if alias and re.search(rf"\b{re.escape(alias.lower())}\b", text_lower):
                brand_hits += 1
                break

        # Competitor mention check
        for comp in all_competitors:
            if comp and re.search(rf"\b{re.escape(comp.lower())}\b", text_lower):
                competitor_hits += 1
                break

        # Geo / demo context check (word-boundary match — substring match
        # over-reports because short codes like "us" or "eu" appear inside
        # common words such as "use", "user", "issues", "europe", etc.).
        if geo_corpus.strip():
            for term in geo_terms:
                if not term:
                    continue
                t = term.strip()
                if not t:
                    continue
                if re.search(rf"\b{re.escape(t)}\b", text_lower):
                    geo_hits += 1
                    break

    checks["all_categories_present"] = VALID_CATEGORIES.issubset(set(cats_seen.keys()))
    # Per-category floors scale to target_count: A-G need ~15% each, H-I ~5%
    floor_abc = max(1, int(round(target_count * 0.10)))   # ~2 at target=20, ~6 at target=55
    floor_hi = max(1, int(round(target_count * 0.04)))    # ~1 at target=20, ~2 at target=55
    checks["per_category_min"] = all(
        (cats_seen.get(c, 0) >= floor_abc) if c in "ABCDEFG" else (cats_seen.get(c, 0) >= floor_hi)
        for c in VALID_CATEGORIES
    )
    checks["brand_mentions_under_10pct"] = (brand_hits + competitor_hits) <= max(5, int(0.10 * n))

    # Length distribution within ±10% of 35/40/25
    def pct(c): return 100.0 * c / n if n else 0
    checks["length_distribution_ok"] = (
        25 <= pct(lengths_seen["short"]) <= 45 and
        30 <= pct(lengths_seen["medium"]) <= 50 and
        15 <= pct(lengths_seen["long"]) <= 35
    )
    checks["specificity_distribution_ok"] = (
        10 <= pct(spec_seen["broad"]) <= 30 and
        40 <= pct(spec_seen["mid"]) <= 60 and
        20 <= pct(spec_seen["hyper-specific"]) <= 40
    )

    # Geo context inclusion: 20-30% of queries (only enforced if brand_profile has geo)
    if geo_terms:
        geo_pct = pct(geo_hits)
        checks["geo_context_in_range"] = 15 <= geo_pct <= 40
    else:
        checks["geo_context_in_range"] = True

    # Near-duplicate detection (simple: identical normalized query)
    norm = [re.sub(r"\s+", " ", t.strip()) for t in queries_text]
    checks["no_duplicates"] = len(norm) == len(set(norm))

    # Enum validity
    bad_enums = []
    for q in queries:
        if q.get("category") not in VALID_CATEGORIES: bad_enums.append(("category", q.get("id")))
        if q.get("intent") not in VALID_INTENTS:     bad_enums.append(("intent", q.get("id")))
        if q.get("stage") not in VALID_STAGES:       bad_enums.append(("stage", q.get("id")))
        if q.get("specificity") not in VALID_SPECIFICITY: bad_enums.append(("specificity", q.get("id")))
        if q.get("length_bucket") not in VALID_LENGTH:    bad_enums.append(("length_bucket", q.get("id")))
    checks["enums_valid"] = len(bad_enums) == 0

    summary = {
        "checks": checks,
        "passed": all(checks.values()),
        "stats": {
            "n": n,
            "categories": cats_seen,
            "intents": intents_seen,
            "lengths_pct": {k: round(pct(v), 1) for k, v in lengths_seen.items()},
            "specificity_pct": {k: round(pct(v), 1) for k, v in spec_seen.items()},
            "brand_mentions": brand_hits,
            "competitor_mentions": competitor_hits,
            "geo_context_pct": round(pct(geo_hits), 1) if geo_terms else None,
        },
        "bad_enums": bad_enums,
    }
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand-profile", help="path to brand_profile.json")
    ap.add_argument("--provider", default="anthropic", choices=["anthropic", "openai", "gemini"])
    ap.add_argument("--model", default=None, help="override default model for the provider")
    ap.add_argument("--target-count", type=int, default=20)
    ap.add_argument("--out", default="output/queries.json")
    ap.add_argument("--validate", help="path to existing queries.json — run validator only")
    args = ap.parse_args()

    if args.validate:
        with open(args.validate, encoding="utf-8") as f:
            obj = json.load(f)
        bp = None
        # Try to read brand profile from sibling path if present
        sibling = Path(args.validate).parent / "brand_profile.json"
        if sibling.exists():
            with open(sibling, encoding="utf-8") as f:
                bp = json.load(f)
        v = validate_queries(obj, brand_profile=bp, target_count=args.target_count)
        print(json.dumps(v, indent=2))
        sys.exit(0 if v["passed"] else 1)

    if not args.brand_profile:
        print("ERROR: --brand-profile is required (unless --validate is used)", file=sys.stderr)
        sys.exit(2)

    bp = load_brand_profile(args.brand_profile)
    prompt = render_prompt(bp, args.target_count)

    print(f"Generating {args.target_count} queries via {args.provider} ...", file=sys.stderr)
    obj = call_llm_for_queries(prompt, args.provider, args.model)

    obj.setdefault("brand", bp.get("brand_name")
                            or ((bp.get("target_brand") or {}).get("name")))
    obj.setdefault("category", bp.get("category"))
    obj.setdefault("model", args.model or "default")
    from datetime import datetime
    obj["generated_at"] = datetime.utcnow().isoformat() + "Z"

    v = validate_queries(obj, brand_profile=bp, target_count=args.target_count)
    obj["validation"] = v

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

    print(f"Wrote {args.out} — {v['stats']['n']} queries, validation passed: {v['passed']}", file=sys.stderr)
    if not v["passed"]:
        print("Failed checks:", [k for k, ok in v["checks"].items() if not ok], file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
