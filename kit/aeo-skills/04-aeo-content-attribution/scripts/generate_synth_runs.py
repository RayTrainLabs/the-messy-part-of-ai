#!/usr/bin/env python3
"""
generate_synth_runs.py — Synthesize an AEO run history from a config file.

Brand-agnostic. Reads:
  - A config JSON describing target brand curve, competitors, per-query boosts,
    optional citation pool, biweekly start date, and number of run dates
  - A queries.json (standard AEO-01 schema)

Writes per-date scored_rows.jsonl into the output dir. Used to seed demos and
to test the AEO-04 attribution pipeline end-to-end without waiting weeks for
real biweekly AEO-01 runs to accumulate.

Usage:
    python3 generate_synth_runs.py \\
      --config   examples/gymshark/synth_config.json \\
      --queries  /path/to/queries.json \\
      --out-dir  examples/gymshark/runs
"""

import argparse
import json
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


REQUIRED_CONFIG_KEYS = {
    "target_brand",
    "competitors",
    "target_curve",
    "start_date",
    "engines",
}


def load_config(path: Path) -> dict[str, Any]:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    missing = REQUIRED_CONFIG_KEYS - set(cfg.keys())
    if missing:
        print(f"ERROR: config missing keys: {sorted(missing)}", file=sys.stderr)
        sys.exit(1)
    return cfg


def biweekly_dates(start_iso: str, n: int) -> list[date]:
    start = datetime.strptime(start_iso, "%Y-%m-%d").date()
    return [start + timedelta(days=14 * i) for i in range(n)]


def query_boost(boosts_cfg: dict[str, Any], q_id: str, date_idx: int) -> float:
    """boosts_cfg is { q_id: [[start_idx, boost], ...] }"""
    total = 0.0
    for entry in (boosts_cfg.get(q_id) or []):
        start_idx, boost = entry[0], entry[1]
        if date_idx >= start_idx:
            total += float(boost)
    return total


def build_row(date_idx: int, q_id: str, q_text: str, engine: str, rng: random.Random,
              target_brand: str, target_prob: float,
              comp_targets: list[tuple[str, float]], citation_pool: dict[str, Any]) -> dict[str, Any]:
    mentioned = []
    if rng.random() < target_prob:
        mentioned.append(target_brand)
    for brand, pct in comp_targets:
        if rng.random() < pct / 100.0:
            mentioned.append(brand)
    target_in = target_brand in mentioned

    cited_urls = []
    if target_in and citation_pool:
        relevant = citation_pool.get(q_id, [])
        for entry in relevant:
            url, available_from_idx = entry[0], entry[1]
            if date_idx >= available_from_idx and rng.random() < 0.4:
                cited_urls.append(url)
                if len(cited_urls) >= 2:
                    break

    return {
        "row_id":     f"{date_idx:02d}-{q_id}-{engine}",
        "query_id":   q_id,
        "query_tested": q_text,
        "engine":     engine,
        "response_summary": "Synthetic response (demo).",
        "brand_mentioned": target_in,
        "brands_mentioned_list": mentioned,
        "citation_frequency_score": rng.randint(1, 8) if target_in else 0,
        "share_of_voice_percentage": round(rng.uniform(15, 40), 1) if target_in else 0.0,
        "positional_authority_score": rng.randint(50, 85) if target_in else 0,
        "sentiment_direction_score": rng.randint(5, 25) if target_in else 0,
        "response_relevance_score": rng.randint(60, 95) if target_in else 30,
        "market_position_type": "Recommended" if target_in else "Not mentioned",
        "discovery_role": "recommended" if target_in else "absent",
        "positioning_narrative": "",
        "strength_score": rng.randint(50, 90) if target_in else 0,
        "schema_presence_observed": rng.choice([True, False]),
        "_brand_mention_counts": {b: 1 for b in mentioned},
        "cited_urls": cited_urls,
    }


def compute_comp_targets(cfg: dict[str, Any], idx: int) -> list[tuple[str, float]]:
    """Per-date competitor presence percentages.

    Each competitor entry can be:
      {"name": "Lululemon", "baseline": 45, "drift": -0.2}   # linear drift per period
      {"name": "Nike",      "baseline": 42, "series": [..]}  # explicit per-period series
    """
    out = []
    for c in cfg["competitors"]:
        if "series" in c and idx < len(c["series"]):
            pct = max(0.0, float(c["series"][idx]))
        else:
            base  = float(c["baseline"])
            drift = float(c.get("drift", 0.0))
            pct = max(0.0, base + drift * idx)
        out.append((c["name"], pct))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config",  required=True, help="Synth config JSON")
    ap.add_argument("--queries", required=True, help="queries.json (AEO-01 schema)")
    ap.add_argument("--out-dir", required=True, help="Output directory for runs/")
    ap.add_argument("--seed",    type=int, default=7)
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    queries = json.loads(Path(args.queries).read_text(encoding="utf-8")).get("queries", [])
    if not queries:
        print("ERROR: queries.json has no 'queries' array", file=sys.stderr)
        sys.exit(1)

    rng = random.Random(args.seed)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    target_brand = cfg["target_brand"]
    curve        = cfg["target_curve"]
    engines      = cfg["engines"]
    boosts       = cfg.get("query_boosts", {})
    citation     = cfg.get("citation_pool", {})

    dates = biweekly_dates(cfg["start_date"], len(curve))
    print(f"Generating {len(dates)} biweekly runs from {dates[0]} to {dates[-1]} for {target_brand}.")

    for idx, d in enumerate(dates):
        comp_targets = compute_comp_targets(cfg, idx)
        run_dir = out_dir / d.isoformat()
        run_dir.mkdir(parents=True, exist_ok=True)
        rows = []
        for q in queries:
            target_prob = min(0.95, curve[idx] / 100.0 + query_boost(boosts, q["id"], idx))
            for engine in engines:
                rows.append(build_row(idx, q["id"], q.get("query", q.get("text", "")),
                                      engine, rng, target_brand, target_prob,
                                      comp_targets, citation))
        with (run_dir / "scored_rows.jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        actual = sum(1 for r in rows if target_brand in r["brands_mentioned_list"]) / max(1, len(rows)) * 100
        print(f"  {d.isoformat()}  target_presence={actual:.1f}%  (curve={curve[idx]}%)")

    print(f"\nDone → {out_dir}")


if __name__ == "__main__":
    main()
