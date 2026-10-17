#!/usr/bin/env python3
"""
Phase 2 — Generate per-query content recommendations.

For each target query:
  1. Load every scraped page from output/website_pages/.
  2. Build a single payload: query, AEO signals, brand profile, the entire site
     (each page as { url, title, page_type, is_ugc, content_excerpt }).
  3. Call the judge LLM with templates/content_recommendations_system_prompt.md.
     The LLM picks which pages are relevant — no TF-IDF / page-index step.
  4. Validate the JSON response (deterministic safety: enums, UGC, on-site URLs,
     per-action-type field minimums, on-domain new_article).
  5. Re-prompt up to 2x on validation failure.
  6. Append validated record to output/recommendations.jsonl.

Usage (chained from skill 01 output):
    python recommend_content.py \
        --queries output/aeo_scorecard.csv \
        --pages-dir output/website_pages/ \
        --brand-profile output/brand_profile.json \
        --judge-provider anthropic \
        --concurrency 4 \
        --out output/recommendations.jsonl

Standalone (no AEO scorecard):
    python recommend_content.py \
        --queries-txt my_queries.txt \
        --pages-dir output/website_pages/ \
        --brand-profile output/brand_profile.json \
        --out output/recommendations.jsonl
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

THIS_DIR = Path(__file__).parent
sys.path.insert(0, str(THIS_DIR))
import providers as P  # noqa: E402

PROMPT_PATH = THIS_DIR.parent / "templates" / "content_recommendations_system_prompt.md"

VALID_COVERAGE = {"comprehensive", "partial", "indirect", "none"}
VALID_ACTION   = {"new_article", "section_addition", "minor_optimization", "maintain"}


# ---------- helpers ----------

_BRAND_PLACEHOLDER_RE = re.compile(
    r"\{(?:TargetBrand|Target|Brand|BrandName|TARGET_BRAND|target_brand|brand_name)\}"
    r"|\[(?:TargetBrand|Target|Brand|BrandName)\]"
)


def _substitute_brand_placeholders(node, real_brand):
    """Walk a JSON-shaped recommendation and replace {TargetBrand} / {Target} /
    {Brand} placeholders the LLM emitted instead of writing the real name.
    Strings are mutated in place (returned new); dicts and lists are walked."""
    if isinstance(node, str):
        return _BRAND_PLACEHOLDER_RE.sub(real_brand, node)
    if isinstance(node, dict):
        return {k: _substitute_brand_placeholders(v, real_brand) for k, v in node.items()}
    if isinstance(node, list):
        return [_substitute_brand_placeholders(v, real_brand) for v in node]
    return node


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


def parse_frontmatter(md_text):
    """Pull out the YAML-style frontmatter that scrape_website.py writes."""
    if not md_text.startswith("---"):
        return {}, md_text
    end = md_text.find("\n---", 3)
    if end < 0:
        return {}, md_text
    fm_block = md_text[3:end].strip()
    body = md_text[end + 4:].lstrip()
    fm = {}
    cur_list_key = None
    for line in fm_block.split("\n"):
        if not line.strip():
            cur_list_key = None
            continue
        if cur_list_key and line.startswith("  - "):
            fm.setdefault(cur_list_key, []).append(line[4:].strip())
            continue
        cur_list_key = None
        if ":" in line:
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if v == "":
                cur_list_key = k
                fm[k] = []
            else:
                fm[k] = v
    return fm, body


def load_all_pages(pages_dir):
    """Load every scraped page into a list of {url, title, page_type, is_ugc, body, ...}."""
    pages_dir = Path(pages_dir)
    index_path = pages_dir / "_index.json"
    if not index_path.exists():
        print(f"ERROR: {index_path} not found. Run scrape_website.py first.", file=sys.stderr)
        sys.exit(1)

    with open(index_path, encoding="utf-8") as f:
        site = json.load(f)

    pages = []
    for entry in site.get("pages", []):
        if not entry.get("scraped_ok"):
            continue
        md_path = pages_dir / entry["path_md"]
        if not md_path.exists():
            continue
        text = md_path.read_text(encoding="utf-8")
        _, body = parse_frontmatter(text)
        pages.append({
            "url":        entry["url"],
            "title":      entry.get("title") or "",
            "page_type":  entry.get("page_type") or "other",
            "is_ugc":     bool(entry.get("is_ugc")),
            "word_count": entry.get("word_count", 0),
            "body":       body.strip(),
        })
    return pages, site.get("homepage", "")


def build_site_payload(pages):
    """Adapt per-page snippet size to keep the prompt budget reasonable.

    The judge LLM gets every page (URL + title + type + UGC flag + content excerpt).
    Smaller sites get more text per page; larger sites get less.
    """
    n = len(pages)
    if n <= 30:
        snippet_chars = 6000   # generous — roughly the full body of most marketing pages
    elif n <= 80:
        snippet_chars = 2500
    elif n <= 200:
        snippet_chars = 900
    else:
        snippet_chars = 400

    site = []
    for p in pages:
        body = (p["body"] or "")
        excerpt = body[:snippet_chars]
        truncated = len(body) > snippet_chars
        site.append({
            "url":        p["url"],
            "title":      p["title"],
            "page_type":  p["page_type"],
            "is_ugc":     p["is_ugc"],
            "word_count": p["word_count"],
            "content":    excerpt + ("\n\n[... truncated ...]" if truncated else ""),
        })
    return site, snippet_chars


# ---------- AEO scorecard aggregator ----------

def load_aeo_scorecard(path):
    """Returns dict[query] -> aggregated signals."""
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)

    by_query = defaultdict(list)
    for r in rows:
        by_query[r.get("query_tested")].append(r)

    out = {}
    for q, group in by_query.items():
        if not q:
            continue
        priorities = [r.get("optimization_priority") for r in group]
        rank = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
        worst_priority = sorted(priorities, key=lambda p: rank.get(p, 99))[0] if priorities else "Medium"

        gap_types = set()
        for r in group:
            for tok in (r.get("content_gap") or "").split(";"):
                tok = tok.split("(")[0].strip().rstrip(":").strip()
                if tok and tok.lower() != "no gap":
                    gap_types.add(tok)

        sov_values, mention_flags = [], []
        for r in group:
            try:
                sov_values.append(float(r.get("share_of_voice_percentage") or 0))
            except ValueError:
                pass
            mention_flags.append(str(r.get("brand_mentioned")).lower() == "true")

        comps = Counter()
        for r in group:
            for b in (r.get("brands_mentioned_list") or "").split(","):
                b = b.strip()
                if b:
                    comps[b] += 1

        out[q] = {
            "priority":         worst_priority,
            "mention_rate":     (sum(mention_flags) / len(mention_flags)) if mention_flags else 0,
            "avg_sov":          round(sum(sov_values) / len(sov_values), 1) if sov_values else 0.0,
            "gap_types":        sorted(gap_types),
            "top_competitors":  [b for b, _ in comps.most_common(8)],
            "_n_rows":          len(group),
            "_query_id":        (group[0].get("query_id") if group else None),
            "_query_category":  (group[0].get("query_category") if group else None),
        }
    return out


def load_paa_from_raw_responses(path):
    """Pull PAA / related-question text per query from skill 01's
    raw_responses.jsonl. Returns dict[query] -> list[str]."""
    if not path or not Path(path).exists():
        return {}
    paa = defaultdict(set)
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("engine_type") != "serp":
                continue
            q = row.get("query_tested")
            if not q:
                continue
            for src_key in ("people_also_ask", "peopleAlsoAsk", "related_questions"):
                items = row.get(src_key) or []
                for it in items:
                    if isinstance(it, dict):
                        question = it.get("question") or it.get("title")
                    else:
                        question = it
                    if question and isinstance(question, str):
                        paa[q].add(question.strip())
    return {q: sorted(qs)[:8] for q, qs in paa.items()}


def load_shipped_queries(path):
    """Read output/shipped.csv and return the set of queries marked shipped.
    The CSV needs at least a `query` column."""
    if not path or not Path(path).exists():
        return set()
    shipped = set()
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            q = (r.get("query") or "").strip()
            if q:
                shipped.add(q)
    return shipped


# ---------- validation ----------

def validate_recommendation(obj, sitemap_urls, ugc_urls, brand_domain=None):
    problems = []

    cs = obj.get("content_status") or {}
    rec = obj.get("recommendation") or {}

    if cs.get("coverage_level") not in VALID_COVERAGE:
        problems.append(f"coverage_level invalid: {cs.get('coverage_level')}")

    action = rec.get("action_type")
    if action not in VALID_ACTION:
        problems.append(f"action_type invalid: {action}")

    coverage = cs.get("coverage_level")
    allowed = {
        "comprehensive": {"minor_optimization", "maintain"},
        "partial":       {"section_addition", "minor_optimization"},
        "indirect":      {"section_addition", "minor_optimization", "new_article"},
        "none":          {"new_article"},
    }.get(coverage, set())
    if allowed and action not in allowed:
        problems.append(f"coverage_level={coverage} does not allow action_type={action}")

    target = rec.get("target_page") or ""
    if not target:
        problems.append("target_page is required")
    if target in ugc_urls:
        problems.append(f"target_page {target} is a UGC page (not allowed)")
    if action != "new_article" and target and target not in sitemap_urls:
        problems.append(f"target_page {target} is not on the scraped site (action_type={action} requires existing URL)")

    if action == "new_article" and target and brand_domain:
        from urllib.parse import urlparse
        target_host = urlparse(target).netloc.lower().replace("www.", "")
        bd = brand_domain.lower().replace("www.", "")
        if target_host and not (target_host == bd or target_host.endswith("." + bd)):
            problems.append(f"new_article target_page {target_host} is not on the brand domain ({bd})")

    int_links = rec.get("internal_links") or []
    invented = [u for u in int_links if u not in sitemap_urls]
    if invented:
        problems.append(f"internal_links contain invented URLs: {invented[:3]}{'...' if len(invented) > 3 else ''}")

    if action == "new_article":
        if not (rec.get("article_outline") or []):
            problems.append("new_article requires article_outline")
        else:
            n = len(rec["article_outline"])
            if not (4 <= n <= 8):
                problems.append(f"article_outline has {n} sections; required 4-8")
            for sec in rec["article_outline"]:
                if not sec.get("heading") or not sec.get("content_points"):
                    problems.append("each article_outline section needs heading + content_points")
                    break
        if len(rec.get("seo_keywords") or []) < 3:
            problems.append("new_article requires >= 3 seo_keywords")
        if len(rec.get("internal_links") or []) < 2:
            problems.append("new_article requires >= 2 internal_links")
        if len(rec.get("external_links") or []) < 1:
            problems.append("new_article requires >= 1 external_link")
        if not rec.get("changes"):
            problems.append("new_article requires changes (Title + Meta)")
    elif action == "section_addition":
        if not rec.get("placement"):
            problems.append("section_addition requires placement")
        ch = rec.get("changes") or ""
        wc = len(re.findall(r"\b\w+\b", ch))
        if not (100 <= wc <= 600):
            problems.append(f"section_addition changes word count {wc} not in 100-600 range")
        if len(rec.get("seo_keywords") or []) < 3:
            problems.append("section_addition requires >= 3 seo_keywords")
        if len(rec.get("internal_links") or []) < 1:
            problems.append("section_addition requires >= 1 internal_link")
        if len(rec.get("external_links") or []) < 1:
            problems.append("section_addition requires >= 1 external_link")
    elif action == "minor_optimization":
        if not (rec.get("changes") or "").strip():
            problems.append("minor_optimization requires changes")
        if len(rec.get("seo_keywords") or []) < 2:
            problems.append("minor_optimization requires >= 2 seo_keywords")
        if len(rec.get("internal_links") or []) < 1:
            problems.append("minor_optimization requires >= 1 internal_link")

    if not rec.get("expected_result"):
        problems.append("expected_result is required")

    return problems


# ---------- main per-query processing ----------

def process_query(query, query_meta, site_pages, sitemap_urls, ugc_urls,
                  brand_profile, judge_mod, prompt, brand_domain, paa_map=None):
    aeo_signals = query_meta.get("aeo_signals") or {}
    related_questions = (paa_map or {}).get(query, [])

    bp_excerpt = {
        "brand_name":  (brand_profile.get("brand_name")
                        or ((brand_profile.get("target_brand") or {}).get("name"))),
        "one_liner":   (brand_profile.get("one_liner")
                        or ((brand_profile.get("target_brand") or {}).get("tagline"))),
        "positioning": (brand_profile.get("positioning")
                        or ((brand_profile.get("target_brand") or {}).get("value_proposition"))),
        "icp":         brand_profile.get("icp"),
        "brand_voice_samples": (
            brand_profile.get("brand_voice_samples") or [brand_profile.get("positioning") or ""]
        ),
        "competitors": (
            (brand_profile.get("competitors") or {}).get("direct", []) +
            (brand_profile.get("competitors") or {}).get("indirect", [])
        ),
    }

    payload = {
        "query": query,
        "query_category": query_meta.get("query_category"),
        "aeo_signals": aeo_signals,
        "related_questions": related_questions,
        "brand_profile": bp_excerpt,
        "site_pages": site_pages,
        "excluded_ugc_urls": sorted(ugc_urls),
    }

    last_err = None
    for attempt in range(3):
        try:
            text = judge_mod.judge(prompt, payload)
            obj = parse_strict_json(text)
            # Defensive: substitute any literal {TargetBrand} / {Target} / {Brand}
            # placeholders the LLM emitted with the real brand name before validating.
            real_brand = bp_excerpt.get("brand_name") or "the brand"
            obj = _substitute_brand_placeholders(obj, real_brand)
            problems = validate_recommendation(obj, sitemap_urls, ugc_urls, brand_domain=brand_domain)
            if not problems:
                rec = obj.get("recommendation") or {}
                action = rec.get("action_type")
                effort = "S"
                if action == "section_addition":
                    effort = "M"
                elif action == "new_article":
                    n = len(rec.get("article_outline") or [])
                    effort = "L" if n >= 6 else "M"
                obj["row_id"] = query_meta.get("row_id") or query_meta.get("query_id") or "?"
                obj["query"] = query
                obj["query_category"] = query_meta.get("query_category")
                obj["aeo_signals"] = aeo_signals
                obj["related_questions"] = related_questions
                obj["priority"] = aeo_signals.get("priority", "Medium")
                obj["effort"] = effort
                obj["_judge"] = {"provider": getattr(judge_mod, "PROVIDER_NAME", None),
                                  "model": getattr(judge_mod, "JUDGE_MODEL", None)}
                return obj
            last_err = problems
            payload["_validator_feedback"] = problems
        except Exception as e:
            last_err = str(e)

    # Surface what actually failed so the user sees the validator delta in the
    # skipped-row log, not just a generic "recommend_error". `last_err` is
    # either a list[str] of validator problems or a stringified exception.
    if isinstance(last_err, list):
        err_str = "validation_failed: " + " | ".join(str(p) for p in last_err)
    else:
        err_str = str(last_err)
    return {
        "row_id": query_meta.get("row_id") or "?",
        "query": query,
        "_recommend_error": err_str[:800],
    }


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", help="path to aeo_scorecard.csv (preferred) or queries.json")
    ap.add_argument("--queries-txt", help="alternative: plain text file, one query per line")
    ap.add_argument("--pages-dir", required=True)
    ap.add_argument("--brand-profile", required=True)
    ap.add_argument("--judge-provider", default="anthropic", choices=["anthropic", "openai", "gemini"])
    ap.add_argument("--judge-model", default=None)
    ap.add_argument("--concurrency", type=int, default=2,
                    help="parallel LLM calls. Default 2 to stay under tier-1 TPM caps "
                         "(~30k TPM); raise to 4-6 if your account is on a higher tier.")
    ap.add_argument("--per-row", action="store_true",
                    help="emit one recommendation per AEO scorecard row (default: per-unique-query)")
    ap.add_argument("--limit", type=int, default=None, help="for testing — only process first N queries")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the planned matrix and exit without firing any LLM calls")
    ap.add_argument("--queries-json", default=None,
                    help="optional sibling queries.json to backfill query_id / query_category "
                         "when reading an aeo_scorecard.csv that lacks those columns")
    ap.add_argument("--raw-responses", default=None,
                    help="optional path to skill 01's raw_responses.jsonl to pull PAA / "
                         "related-questions per query. Auto-detected next to the scorecard CSV.")
    ap.add_argument("--shipped-csv", default=None,
                    help="optional path to a shipped.csv (column `query`); listed queries "
                         "are skipped. Auto-detected at output/shipped.csv next to --out.")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    # Dry-run skips the LLM entirely, so don't fail on missing keys.
    judge_mod = P.judge_provider(prefer=args.judge_provider)
    if not judge_mod and not args.dry_run:
        print("ERROR: no LLM judge available. Set ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY.",
              file=sys.stderr); sys.exit(1)
    if judge_mod and args.judge_model:
        try: judge_mod.JUDGE_MODEL = args.judge_model
        except Exception: pass

    with open(args.brand_profile, encoding="utf-8") as f:
        brand_profile = json.load(f)
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    # Load every scraped page once (shared across all queries)
    pages, homepage = load_all_pages(args.pages_dir)
    if not pages:
        print(f"ERROR: no scraped pages found in {args.pages_dir}", file=sys.stderr); sys.exit(1)

    site_pages, snippet_chars = build_site_payload(pages)
    sitemap_urls = {p["url"] for p in pages}
    ugc_urls = {p["url"] for p in pages if p["is_ugc"]}

    # Brand domain for new_article on-domain check
    bp_url = brand_profile.get("url") or homepage or ""
    brand_domain = None
    if bp_url:
        from urllib.parse import urlparse
        brand_domain = urlparse(bp_url).netloc.lower().replace("www.", "") or None

    # Optional sibling queries.json for backfilling query_id / query_category.
    # Auto-detect when the user passed a scorecard CSV — try the file next to it,
    # so the chained skill 01 -> skill 02 flow works without --queries-json.
    qid_lookup_path = args.queries_json
    if not qid_lookup_path and args.queries and args.queries.endswith(".csv"):
        sibling = Path(args.queries).parent / "queries.json"
        if sibling.exists():
            qid_lookup_path = str(sibling)
            print(f"Auto-detected sibling queries.json at {sibling} (use --queries-json to override).",
                  file=sys.stderr)

    qid_lookup = {}
    if qid_lookup_path and Path(qid_lookup_path).exists():
        with open(qid_lookup_path, encoding="utf-8") as f:
            qj = json.load(f)
        for q in qj.get("queries") or []:
            text = q.get("query")
            if text:
                qid_lookup[text] = {"query_id": q.get("id"), "query_category": q.get("category")}

    # Resolve query list
    queries_with_meta = []
    if args.queries_txt:
        for i, line in enumerate(Path(args.queries_txt).read_text(encoding="utf-8").splitlines(), start=1):
            line = line.strip()
            if line:
                queries_with_meta.append((line, {"row_id": f"Q{i:03d}",
                                                 "query_id": f"Q{i:03d}",
                                                 "aeo_signals": {}}))
    elif args.queries:
        if args.queries.endswith(".csv"):
            agg = load_aeo_scorecard(args.queries)
            if args.per_row:
                with open(args.queries, newline="", encoding="utf-8") as f:
                    for i, r in enumerate(csv.DictReader(f), start=1):
                        q = r.get("query_tested")
                        if not q:
                            continue
                        sigs = agg.get(q, {})
                        fallback = qid_lookup.get(q, {})
                        queries_with_meta.append((q, {
                            "row_id": f"R{i:03d}",
                            "query_id": r.get("query_id") or fallback.get("query_id"),
                            "query_category": r.get("query_category") or fallback.get("query_category"),
                            "aeo_signals": {k: v for k, v in sigs.items() if not k.startswith("_")},
                        }))
            else:
                for q, sigs in agg.items():
                    fallback = qid_lookup.get(q, {})
                    queries_with_meta.append((q, {
                        "row_id": sigs.get("_query_id") or fallback.get("query_id"),
                        "query_id": sigs.get("_query_id") or fallback.get("query_id"),
                        "query_category": sigs.get("_query_category") or fallback.get("query_category"),
                        "aeo_signals": {k: v for k, v in sigs.items() if not k.startswith("_")},
                    }))
        elif args.queries.endswith(".json"):
            with open(args.queries, encoding="utf-8") as f:
                qj = json.load(f)
            for q in qj.get("queries") or []:
                queries_with_meta.append((q.get("query"), {
                    "row_id": q.get("id"),
                    "query_id": q.get("id"),
                    "query_category": q.get("category"),
                    "aeo_signals": {},
                }))
        else:
            print("ERROR: --queries must be .csv or .json", file=sys.stderr); sys.exit(2)
    else:
        print("ERROR: provide --queries or --queries-txt", file=sys.stderr); sys.exit(2)

    if args.limit:
        queries_with_meta = queries_with_meta[: args.limit]
    if not queries_with_meta:
        print("ERROR: no queries resolved", file=sys.stderr); sys.exit(1)

    # Auto-detect skill 01 raw_responses.jsonl next to the scorecard
    raw_responses_path = args.raw_responses
    if not raw_responses_path and args.queries and args.queries.endswith(".csv"):
        sibling = Path(args.queries).parent / "raw_responses.jsonl"
        if sibling.exists():
            raw_responses_path = str(sibling)
            print(f"Auto-detected raw_responses.jsonl at {sibling} for PAA extraction.",
                  file=sys.stderr)
    paa_map = load_paa_from_raw_responses(raw_responses_path) if raw_responses_path else {}
    if paa_map:
        with_paa = sum(1 for q, _ in queries_with_meta if q in paa_map)
        print(f"PAA: matched {with_paa}/{len(queries_with_meta)} queries from raw_responses.jsonl",
              file=sys.stderr)

    # Auto-detect shipped.csv next to --out
    shipped_path = args.shipped_csv
    if not shipped_path:
        sibling = Path(args.out).parent / "shipped.csv"
        if sibling.exists():
            shipped_path = str(sibling)
            print(f"Auto-detected shipped.csv at {sibling}.", file=sys.stderr)
    shipped_set = load_shipped_queries(shipped_path)
    if shipped_set:
        before = len(queries_with_meta)
        queries_with_meta = [(q, m) for q, m in queries_with_meta if q not in shipped_set]
        print(f"shipped.csv: dropped {before - len(queries_with_meta)} already-shipped queries "
              f"({len(queries_with_meta)} remaining).", file=sys.stderr)

    provider_name = getattr(judge_mod, "PROVIDER_NAME", "(no LLM available)") if judge_mod else "(no LLM available)"
    rough_per_call = {"Anthropic": 0.10, "OpenAI": 0.05, "Gemini": 0.04}.get(provider_name, 0.07)
    est_cost = round(rough_per_call * len(queries_with_meta), 2)

    print(f"Plan: {len(queries_with_meta)} queries x {len(pages)} pages "
          f"(snippet ~{snippet_chars} chars/page) = {len(queries_with_meta)} LLM calls "
          f"via {provider_name}", file=sys.stderr)
    print(f"Estimated cost: ~${est_cost:.2f} (rough; actual depends on prompt size)", file=sys.stderr)
    print("Tip: re-run with --limit 3 first to spot-check before committing the full batch.",
          file=sys.stderr)

    if args.dry_run:
        print("\n--dry-run: would dispatch the following queries (first 10 shown):", file=sys.stderr)
        for q, meta in queries_with_meta[:10]:
            print(f"  {meta.get('query_id') or meta.get('row_id'):>8}  ::  {q[:90]}", file=sys.stderr)
        if len(queries_with_meta) > 10:
            print(f"  ... + {len(queries_with_meta) - 10} more.", file=sys.stderr)
        print("\nDry run complete. No LLM calls made.", file=sys.stderr)
        return

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    out_f = open(args.out, "w", encoding="utf-8")
    ok = err = 0
    counts_by_action = Counter()

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futs = [pool.submit(process_query, q, meta, site_pages, sitemap_urls, ugc_urls,
                            brand_profile, judge_mod, prompt, brand_domain, paa_map)
                for q, meta in queries_with_meta]
        for i, fut in enumerate(as_completed(futs), start=1):
            obj = fut.result()
            out_f.write(json.dumps(obj, ensure_ascii=False) + "\n")
            out_f.flush()
            if "_recommend_error" in obj:
                err += 1
            else:
                ok += 1
                counts_by_action[(obj.get("recommendation") or {}).get("action_type")] += 1
            if i % 10 == 0:
                print(f"  ... {i}/{len(queries_with_meta)}  ok={ok} err={err}  by_action={dict(counts_by_action)}",
                      file=sys.stderr)

    out_f.close()
    print(f"\nDone. ok={ok} err={err}.  Action-type breakdown: {dict(counts_by_action)}", file=sys.stderr)
    print(f"Output -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
