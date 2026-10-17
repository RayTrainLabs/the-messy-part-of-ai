#!/usr/bin/env python3
"""Cross-run trend diff for AEO brand visibility.

Reads two scorecard CSVs (typically two consecutive weekly runs) and emits:
  - trend.csv  : per-(query, engine) deltas of the key numeric metrics
  - trend.md   : top movers up + down + new gaps + closed gaps

Usage:
    python trend.py --before runs/2026-04-15/scorecard.csv \
                    --after  runs/2026-04-29/scorecard.csv \
                    --out-csv runs/2026-04-29/trend.csv \
                    --out-md  runs/2026-04-29/trend.md
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

NUMERIC_METRICS = [
    ("citation_frequency_score",   True),
    ("share_of_voice_percentage",  True),
    ("positional_authority_score", True),
    ("sentiment_direction_score",  True),
    ("response_relevance_score",   True),
    ("strength_score",             True),
]
KEY_COLS = ["query_tested", "engine"]
PRIMARY_RANK_METRIC = "strength_score"


def load_scorecard(path):
    df = pd.read_csv(path)
    if "engine" not in df.columns:
        df["engine"] = "(all)"
    return df


def diff(before, after):
    keep_cols = KEY_COLS + [c for c, _ in NUMERIC_METRICS]
    keep_cols = [c for c in keep_cols if c in before.columns and c in after.columns]
    b = before[keep_cols].copy()
    a = after[keep_cols].copy()
    merged = a.merge(b, on=KEY_COLS, how="outer", suffixes=("_after", "_before"), indicator=True)

    rows = []
    for _, r in merged.iterrows():
        rec = {"query_tested": r["query_tested"], "engine": r["engine"],
               "in_before": r["_merge"] in ("both", "right_only"),
               "in_after":  r["_merge"] in ("both", "left_only")}
        for col, _ in NUMERIC_METRICS:
            b_val = r.get(f"{col}_before")
            a_val = r.get(f"{col}_after")
            try:
                delta = float(a_val) - float(b_val) if pd.notna(a_val) and pd.notna(b_val) else None
            except (TypeError, ValueError):
                delta = None
            rec[f"{col}_before"] = b_val
            rec[f"{col}_after"]  = a_val
            rec[f"{col}_delta"]  = delta
        rows.append(rec)
    return pd.DataFrame(rows)


def render_md(df, primary=PRIMARY_RANK_METRIC, top_n=10):
    delta_col = f"{primary}_delta"
    movers = df.dropna(subset=[delta_col]).sort_values(delta_col, ascending=False)
    new_q = df[df["in_before"] == False]
    dropped_q = df[df["in_after"] == False]

    parts = [f"# AEO trend report\n",
             f"Primary movement metric: **{primary}** (delta = after - before).\n",
             f"## Top {top_n} improvements\n",
             _md_table(movers.head(top_n), primary),
             f"\n## Top {top_n} regressions\n",
             _md_table(movers.tail(top_n).iloc[::-1], primary),
             f"\n## New queries (in after, not before): {len(new_q)}\n"]
    if not new_q.empty:
        parts.append(_md_table(new_q.head(top_n), primary, show_delta=False))
    parts.append(f"\n## Dropped queries (in before, not after): {len(dropped_q)}\n")
    if not dropped_q.empty:
        parts.append(_md_table(dropped_q.head(top_n), primary, show_delta=False))
    return "\n".join(parts)


def _md_table(df, primary, show_delta=True):
    if df.empty:
        return "_(none)_\n"
    cols = ["query_tested", "engine", f"{primary}_before", f"{primary}_after"]
    if show_delta:
        cols.append(f"{primary}_delta")
    sub = df[cols].copy()
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"] * len(cols)) + " |"
    body = ["| " + " | ".join(str(r[c]) for c in cols) + " |" for _, r in sub.iterrows()]
    return "\n".join([header, sep, *body])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True, help="earlier scorecard CSV")
    ap.add_argument("--after", required=True, help="later scorecard CSV")
    ap.add_argument("--out-csv", required=True)
    ap.add_argument("--out-md", required=True)
    args = ap.parse_args()

    before = load_scorecard(args.before)
    after = load_scorecard(args.after)
    print(f"loaded {len(before)} before rows, {len(after)} after rows", file=sys.stderr)

    out = diff(before, after)
    Path(args.out_csv).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out_csv, index=False)

    md = render_md(out)
    Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_md).write_text(md, encoding="utf-8")

    print(f"trend CSV -> {args.out_csv}", file=sys.stderr)
    print(f"trend MD  -> {args.out_md}", file=sys.stderr)


if __name__ == "__main__":
    main()
