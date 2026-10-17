#!/usr/bin/env python3
"""
Phase 3 (part 1) — Flatten recommendations.jsonl into the per-query CSV/XLSX.

Joins recommendation rows with the AEO scorecard (for priority + gap_types
helper columns), validates each record, writes both CSV and XLSX with
conditional formatting.

Usage:
    python compile_recommendations_sheet.py \
        --recommendations output/recommendations.jsonl \
        --aeo-scorecard   output/aeo_scorecard.csv \
        --pages-index     output/website_pages/_index.json \
        --out-csv  output/aeo_content_recommendations.csv \
        --out-xlsx output/aeo_content_recommendations.xlsx
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Font, PatternFill

VALID_COVERAGE = ["comprehensive", "partial", "indirect", "none"]
VALID_ACTION   = ["new_article", "section_addition", "minor_optimization", "maintain"]
VALID_PRIORITY = ["Critical", "High", "Medium", "Low"]
VALID_EFFORT   = ["S", "M", "L"]

CSV_COLUMNS = [
    "query", "content_exists", "coverage_level", "current_locations",
    "action_type", "target_page", "placement", "changes",
    "seo_keywords", "article_outline",
    "internal_links", "external_links", "expected_result",
    "priority", "effort",
]
XLSX_HELPER_COLUMNS = ["query_id", "query_category", "gap_types"]


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def flatten_outline(outline):
    if not outline:
        return ""
    parts = []
    for sec in outline:
        h = (sec.get("heading") or "").strip()
        pts = sec.get("content_points") or []
        if h:
            parts.append(f"H: {h}")
        for p in pts:
            parts.append(f"  - {p}")
        parts.append("")
    return "\n".join(parts).rstrip()


def flatten_locations(locations):
    if not locations:
        return ""
    out = []
    for loc in locations:
        url = loc.get("page_url", "")
        sec = loc.get("section", "")
        if url:
            out.append(f"{url} § {sec}" if sec else url)
    return " | ".join(out)


def join_rows(records, sitemap_urls, ugc_urls):
    out = []
    skipped = []
    for obj in records:
        rid = obj.get("row_id") or obj.get("query_id") or "?"
        if "_recommend_error" in obj:
            skipped.append((rid, "recommend_error"))
            continue

        cs = obj.get("content_status") or {}
        rec = obj.get("recommendation") or {}
        sigs = obj.get("aeo_signals") or {}

        record = {
            "query_id":       obj.get("row_id") or obj.get("query_id"),
            "query_category": obj.get("query_category"),
            "gap_types":      ", ".join(sigs.get("gap_types") or []),

            "query":           obj.get("query"),
            "content_exists":  bool(cs.get("exists")),
            "coverage_level":  cs.get("coverage_level"),
            "current_locations": flatten_locations(cs.get("locations")),
            "action_type":     rec.get("action_type"),
            "target_page":     rec.get("target_page"),
            "placement":       rec.get("placement") or "",
            "changes":         rec.get("changes") or "",
            "seo_keywords":    ", ".join(rec.get("seo_keywords") or []),
            "article_outline": flatten_outline(rec.get("article_outline") or []),
            "internal_links":  "\n".join(rec.get("internal_links") or []),
            "external_links":  "\n".join(rec.get("external_links") or []),
            "expected_result": rec.get("expected_result") or "",
            "priority":        obj.get("priority") or sigs.get("priority") or "Medium",
            "effort":          obj.get("effort") or "M",
        }
        problems = validate(record, sitemap_urls, ugc_urls)
        if problems:
            skipped.append((rid, "; ".join(problems)))
            continue
        out.append(record)
    return out, skipped


def validate(rec, sitemap_urls, ugc_urls):
    problems = []
    if not rec.get("query"):
        problems.append("missing query")
    if rec.get("coverage_level") not in VALID_COVERAGE:
        problems.append(f"coverage_level invalid: {rec.get('coverage_level')}")
    if rec.get("action_type") not in VALID_ACTION:
        problems.append(f"action_type invalid: {rec.get('action_type')}")
    if rec.get("priority") not in VALID_PRIORITY:
        problems.append(f"priority invalid: {rec.get('priority')}")
    if rec.get("effort") not in VALID_EFFORT:
        problems.append(f"effort invalid: {rec.get('effort')}")

    target = rec.get("target_page") or ""
    if not target:
        problems.append("missing target_page")
    if target in ugc_urls:
        problems.append(f"target_page is a UGC URL: {target}")
    if rec.get("action_type") != "new_article" and target and target not in sitemap_urls:
        problems.append(f"target_page not on scraped site: {target}")

    # coverage -> action mapping
    allowed = {
        "comprehensive": {"minor_optimization", "maintain"},
        "partial":       {"section_addition", "minor_optimization"},
        "indirect":      {"section_addition", "minor_optimization", "new_article"},
        "none":          {"new_article"},
    }.get(rec.get("coverage_level"), set())
    if allowed and rec.get("action_type") not in allowed:
        problems.append(f"coverage_level={rec.get('coverage_level')} doesn't allow action_type={rec.get('action_type')}")

    if not rec.get("expected_result"):
        problems.append("missing expected_result")

    # Internal links: each line must be a known URL on the site (or empty)
    internal = [u.strip() for u in (rec.get("internal_links") or "").split("\n") if u.strip()]
    bad = [u for u in internal if u not in sitemap_urls]
    if bad:
        problems.append(f"internal_links not on site: {bad[:3]}{'...' if len(bad) > 3 else ''}")

    # Per-action-type field minimums (mirrors recommend_content.py validator;
    # acts as defense-in-depth so hand-edited / 3rd-party JSONL still gets caught)
    action = rec.get("action_type")
    keywords = [k.strip() for k in (rec.get("seo_keywords") or "").split(",") if k.strip()]
    external = [u.strip() for u in (rec.get("external_links") or "").split("\n") if u.strip()]
    outline = (rec.get("article_outline") or "").strip()

    if action == "new_article":
        if not outline:
            problems.append("new_article requires article_outline")
        else:
            n_sections = sum(1 for line in outline.split("\n") if line.startswith("H: "))
            if not (4 <= n_sections <= 8):
                problems.append(f"new_article article_outline has {n_sections} sections; required 4-8")
        if len(keywords) < 3:
            problems.append("new_article requires >= 3 seo_keywords")
        if len(internal) < 2:
            problems.append("new_article requires >= 2 internal_links")
        if len(external) < 1:
            problems.append("new_article requires >= 1 external_link")
        if not (rec.get("changes") or "").strip():
            problems.append("new_article requires changes (Title + Meta)")
    elif action == "section_addition":
        if not (rec.get("placement") or "").strip():
            problems.append("section_addition requires placement")
        if len(keywords) < 3:
            problems.append("section_addition requires >= 3 seo_keywords")
        if len(internal) < 1:
            problems.append("section_addition requires >= 1 internal_link")
        if len(external) < 1:
            problems.append("section_addition requires >= 1 external_link")
    elif action == "minor_optimization":
        if not (rec.get("changes") or "").strip():
            problems.append("minor_optimization requires changes")
        if len(keywords) < 2:
            problems.append("minor_optimization requires >= 2 seo_keywords")
        if len(internal) < 1:
            problems.append("minor_optimization requires >= 1 internal_link")

    return problems


def write_csv(records, path):
    df = pd.DataFrame(records, columns=CSV_COLUMNS)
    df.to_csv(path, index=False, encoding="utf-8")


def write_xlsx(records, path):
    cols = XLSX_HELPER_COLUMNS + CSV_COLUMNS
    df = pd.DataFrame(records, columns=cols)
    df.to_excel(path, index=False, sheet_name="AEO Content Recommendations")
    _format(path)


def _format(path):
    wb = load_workbook(path)
    ws = wb.active
    ws.freeze_panes = "A2"
    bold = Font(bold=True)
    for c in ws[1]:
        c.font = bold

    def fill(color):
        return PatternFill(start_color=color, end_color=color, fill_type="solid")

    headers = {c.value: c.column_letter for c in ws[1]}
    n_rows = ws.max_row
    has_data_rows = n_rows >= 2

    enum_colors = {
        "priority": {
            "Critical": "F8696B", "High": "F4B084", "Medium": "FFEB9C", "Low": "D9D9D9",
        },
        "action_type": {
            "new_article":         "BDD7EE",
            "section_addition":    "B4C7E7",
            "minor_optimization":  "C6EFCE",
            "maintain":            "D9D9D9",
        },
        "coverage_level": {
            "comprehensive": "C6EFCE",
            "partial":       "FFEB9C",
            "indirect":      "F4B084",
            "none":          "F8696B",
        },
        "effort": {
            "S": "C6EFCE", "M": "FFEB9C", "L": "F8696B",
        },
    }
    if has_data_rows:
        for col_name, color_map in enum_colors.items():
            col_letter = headers.get(col_name)
            if not col_letter:
                continue
            for value, color in color_map.items():
                rule = CellIsRule(operator="equal", formula=[f'"{value}"'], fill=fill(color))
                ws.conditional_formatting.add(f"{col_letter}2:{col_letter}{n_rows}", rule)

    # Autosize columns (rough)
    for c in ws[1]:
        col_letter = c.column_letter
        max_len = len(str(c.value or ""))
        for cell in ws[col_letter][1:]:
            v = str(cell.value) if cell.value is not None else ""
            if "\n" in v:
                v = max(v.split("\n"), key=len, default="")
            if len(v) > max_len:
                max_len = min(len(v), 80)
        ws.column_dimensions[col_letter].width = min(max(max_len + 2, 14), 80)

    wb.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recommendations", required=True)
    ap.add_argument("--aeo-scorecard", default=None,
                    help="optional — used only for sanity checks; helper columns come from recommendations.jsonl")
    ap.add_argument("--pages-index", required=True,
                    help="path to output/website_pages/_index.json (validates target_page)")
    ap.add_argument("--out-csv", required=True)
    ap.add_argument("--out-xlsx", required=True)
    args = ap.parse_args()

    recs = load_jsonl(args.recommendations)
    with open(args.pages_index, encoding="utf-8") as f:
        site = json.load(f)
    pages = site.get("pages") or []
    sitemap_urls = {p["url"] for p in pages if p.get("scraped_ok")}
    ugc_urls = {p["url"] for p in pages if p.get("scraped_ok") and p.get("is_ugc")}

    records, skipped = join_rows(recs, sitemap_urls, ugc_urls)
    print(f"Joined {len(records)} valid records; skipped {len(skipped)}.", file=sys.stderr)
    if skipped[:10]:
        print("First 10 skipped:", file=sys.stderr)
        for rid, why in skipped[:10]:
            print(f"  - {rid}: {why}", file=sys.stderr)

    Path(args.out_csv).parent.mkdir(parents=True, exist_ok=True)
    write_csv(records, args.out_csv)
    write_xlsx(records, args.out_xlsx)
    print(f"Wrote {args.out_csv} and {args.out_xlsx}", file=sys.stderr)


if __name__ == "__main__":
    main()
