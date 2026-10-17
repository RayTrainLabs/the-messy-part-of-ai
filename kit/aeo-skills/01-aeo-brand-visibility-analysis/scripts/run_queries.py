#!/usr/bin/env python3
"""
Phase 3 — Query execution.

Fan-out every query in queries.json across every available engine. Save raw payloads
to output/raw/ and append unified rows to output/raw_responses.jsonl.

Usage:
    python run_queries.py --check-providers
    python run_queries.py --queries output/queries.json --brand "Acme" \
        --concurrency 4 --out output/raw_responses.jsonl --raw-dir output/raw/
    python run_queries.py --queries output/queries.json --brand "Acme" --resume \
        --out output/raw_responses.jsonl --raw-dir output/raw/
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

THIS_DIR = Path(__file__).parent
sys.path.insert(0, str(THIS_DIR))

import providers as P  # noqa: E402


def check_providers():
    # Plain ASCII glyphs only — Windows default console (cp1252) cannot encode
    # the Unicode check / cross marks and crashes with UnicodeEncodeError.
    print("Provider availability:")
    for engine_id, mod in [
        ("serp_google (SerpApi)", P.serpapi_client),
        ("serp_google (Apify)",   P.apify_client),
        ("llm_openai",            P.openai_client),
        ("llm_anthropic",         P.anthropic_client),
        ("llm_perplexity",        P.perplexity_client),
        ("llm_gemini",            P.gemini_client),
    ]:
        ok = mod.is_available()
        mark = "OK " if ok else " - "
        why = "" if ok else f"  ({_missing_env(mod.PROVIDER_NAME)} not set)"
        print(f"  [{mark}]  {engine_id}{why}")

    chosen = P.available_engines()
    print()
    print(f"Will use {len(chosen)} engines this run:")
    for eid, mod in chosen:
        print(f"  - {eid}  via {mod.PROVIDER_NAME}")

    if not any(eid == "serp_google" for eid, _ in chosen):
        print("\nERROR: at least one SERP source (SERPAPI_KEY or APIFY_TOKEN) is required.", file=sys.stderr)
        sys.exit(1)


def _missing_env(provider_name):
    return {
        "SerpApi":    "SERPAPI_KEY",
        "Apify":      "APIFY_TOKEN",
        "OpenAI":     "OPENAI_API_KEY",
        "Anthropic":  "ANTHROPIC_API_KEY",
        "Perplexity": "PERPLEXITY_API_KEY",
        "Gemini":     "GEMINI_API_KEY",
    }.get(provider_name, "(env var)")


def estimate_cost(engines, n_queries):
    rough = {
        "SerpApi":    0.008,
        "Apify":      0.010,
        "OpenAI":     0.035,
        "Anthropic":  0.075,
        "Perplexity": 0.008,
        "Gemini":     0.020,
    }
    total = 0.0
    breakdown = {}
    for _, mod in engines:
        per = rough.get(mod.PROVIDER_NAME, 0.02)
        cost = per * n_queries
        breakdown[mod.PROVIDER_NAME] = round(cost, 2)
        total += cost
    return total, breakdown


def run_one(query_record, engine_id, provider_mod, brand_profile, raw_dir):
    qid = query_record["id"]
    query = query_record["query"]
    row_id = f"{qid}__{engine_id}"

    started = time.time()
    result = provider_mod.call(query, brand_profile=brand_profile)
    elapsed = round(time.time() - started, 2)

    row = {
        "row_id": row_id,
        "query_id": qid,
        "query_tested": query,
        "category": query_record.get("category"),
        "engine": engine_id,
        "engine_type": result.get("engine_type"),
        "model": result.get("model"),
        "web_search_enabled": result.get("web_search_enabled"),
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "elapsed_s": elapsed,
        "ok": result.get("ok", False),
        "error": result.get("error"),
        "llm_answer_text": result.get("llm_answer_text"),
        "citation_urls": result.get("citation_urls") or [],
        "serp_results": result.get("serp_results"),
        "serp_organic_count": result.get("serp_organic_count"),
        "serp_ai_overview": result.get("serp_ai_overview"),
        "raw_response_path": None,
    }

    if raw_dir and result.get("raw") is not None:
        raw_path = Path(raw_dir) / f"{row_id}.json"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(result["raw"], f, indent=2, ensure_ascii=False)
        row["raw_response_path"] = str(raw_path)

    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", help="path to queries.json")
    ap.add_argument("--brand", help="target brand name (must match brand_profile)")
    ap.add_argument("--brand-profile", default=None, help="optional path to brand_profile.json (used for geo cues)")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--out", default="output/raw_responses.jsonl")
    ap.add_argument("--raw-dir", default="output/raw/")
    ap.add_argument("--check-providers", action="store_true")
    ap.add_argument("--resume", action="store_true",
                    help="skip rows already present in --out")
    ap.add_argument("--yes", action="store_true",
                    help="skip cost-confirmation prompt (for non-interactive runs)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the planned (query x engine) matrix and cost estimate, "
                         "then exit without firing any API calls")
    ap.add_argument("--max-queries", type=int, default=None,
                    help="cap the run at the first N queries (useful for cost-capped smoke tests)")
    args = ap.parse_args()

    if args.check_providers:
        check_providers()
        return

    if not args.queries or not args.brand:
        print("ERROR: --queries and --brand are required", file=sys.stderr)
        sys.exit(2)

    with open(args.queries, encoding="utf-8") as f:
        qobj = json.load(f)
    queries = qobj.get("queries") or []
    if not queries:
        print("ERROR: no queries found in input", file=sys.stderr); sys.exit(1)

    if args.max_queries:
        queries = queries[: args.max_queries]
        print(f"--max-queries={args.max_queries} -> capping to first {len(queries)} queries", file=sys.stderr)

    brand_profile = None
    if args.brand_profile:
        with open(args.brand_profile, encoding="utf-8") as f:
            brand_profile = json.load(f)

    engines = P.available_engines()
    if not any(eid == "serp_google" for eid, _ in engines):
        print("ERROR: no SERP source configured (set SERPAPI_KEY or APIFY_TOKEN).", file=sys.stderr)
        sys.exit(1)

    total_calls = len(queries) * len(engines)
    cost, breakdown = estimate_cost(engines, len(queries))
    print(f"Plan: {len(queries)} queries x {len(engines)} engines = {total_calls} API calls", file=sys.stderr)
    print(f"Engines: {[eid for eid, _ in engines]}", file=sys.stderr)
    print(f"Estimated cost: ~${cost:.2f}  breakdown={breakdown}", file=sys.stderr)

    if args.dry_run:
        print("\n--dry-run: would dispatch the following (query x engine) matrix:", file=sys.stderr)
        for q in queries[:10]:
            for eid, _ in engines:
                print(f"  {q['id']}__{eid}  ::  {q['query'][:80]}", file=sys.stderr)
        if len(queries) > 10:
            print(f"  ... + {(len(queries) - 10) * len(engines)} more rows not shown.", file=sys.stderr)
        print("\nDry run complete. No API calls made.", file=sys.stderr)
        return

    if not args.yes:
        if not sys.stdin.isatty():
            print("ERROR: stdin is not a TTY and --yes was not passed; aborting.\n"
                  "Re-run with --yes to skip the cost-confirmation prompt.",
                  file=sys.stderr)
            sys.exit(1)
        print("Proceed? (y/n) ", end="", flush=True)
        try:
            ans = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nNo confirmation received (non-interactive stdin). "
                  "Re-run with --yes to skip the prompt.", file=sys.stderr)
            sys.exit(1)
        if ans != "y":
            print("Aborted.", file=sys.stderr); sys.exit(0)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.raw_dir).mkdir(parents=True, exist_ok=True)

    done_ids = set()
    if args.resume and Path(args.out).exists():
        with open(args.out, encoding="utf-8") as f:
            for line in f:
                try:
                    done_ids.add(json.loads(line).get("row_id"))
                except Exception:
                    pass
        print(f"Resume mode: {len(done_ids)} rows already complete; skipping them.", file=sys.stderr)

    work = []
    for q in queries:
        for eid, mod in engines:
            row_id = f"{q['id']}__{eid}"
            if row_id in done_ids:
                continue
            work.append((q, eid, mod))

    print(f"Dispatching {len(work)} (query x engine) calls with concurrency={args.concurrency} ...", file=sys.stderr)

    succeeded = 0
    failed = 0
    failures = []
    out_f = open(args.out, "a", encoding="utf-8")

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futs = [pool.submit(run_one, q, eid, mod, brand_profile, args.raw_dir)
                for q, eid, mod in work]
        for i, fut in enumerate(as_completed(futs), start=1):
            row = fut.result()
            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            out_f.flush()
            if row["ok"]:
                succeeded += 1
            else:
                failed += 1
                failures.append((row["row_id"], row["error"]))
            if i % 10 == 0:
                print(f"  ... {i}/{len(work)}  ok={succeeded} fail={failed}", file=sys.stderr)

    out_f.close()

    print(f"\nDone. Total {succeeded + failed} rows. Successful: {succeeded}. Failed: {failed}.", file=sys.stderr)
    if failures:
        print("Failures:", file=sys.stderr)
        for fid, err in failures[:20]:
            print(f"  - {fid}: {err}", file=sys.stderr)
        if len(failures) > 20:
            print(f"  ... and {len(failures) - 20} more", file=sys.stderr)

    print(f"\nOutput -> {args.out}", file=sys.stderr)
    print(f"Raw payloads -> {args.raw_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
