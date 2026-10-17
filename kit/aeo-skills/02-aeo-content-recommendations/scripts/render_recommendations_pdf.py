#!/usr/bin/env python3
"""
Phase 3 (part 2) — Render the content roadmap PDF and exec summary markdown.

Reads:
  - aeo_content_recommendations.xlsx (compiled per-query roadmap)
  - recommendations.jsonl (full nested form, used for cluster + outline visualization)
  - brand_profile.json
  - website_pages/_index.json (page-type breakdown)
  - aeo_scorecard.csv (optional, used for "what's good" cross-reference)

Writes:
  - aeo_content_roadmap.pdf
  - aeo_content_executive_summary.md

Usage:
    python render_recommendations_pdf.py \
        --xlsx output/aeo_content_recommendations.xlsx \
        --recommendations output/recommendations.jsonl \
        --brand-profile output/brand_profile.json \
        --pages-index output/website_pages/_index.json \
        --aeo-scorecard output/aeo_scorecard.csv \
        --out output/aeo_content_roadmap.pdf
"""

import argparse
import json
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Image,
                                Table, TableStyle, PageBreak)


PRIORITY_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
EFFORT_WEIGHT = {"S": 1, "M": 3, "L": 8}


# ---------- aggregation ----------

def aggregate(df, recommendations, site):
    target = (site or {}).get("homepage") or ""
    n_rows = len(df)
    by_action = Counter(df.get("action_type", pd.Series([])).dropna())
    by_priority = Counter(df.get("priority", pd.Series([])).dropna())
    by_effort = Counter(df.get("effort", pd.Series([])).dropna())
    by_coverage = Counter(df.get("coverage_level", pd.Series([])).dropna())

    # Total effort
    total_effort = sum(EFFORT_WEIGHT.get(e, 0) * c for e, c in by_effort.items())

    # Top actions by priority then by frequency of target_page (cluster signal)
    df_sorted = df.copy()
    df_sorted["_p_rank"] = df_sorted["priority"].map(PRIORITY_RANK).fillna(99)
    df_sorted = df_sorted.sort_values(["_p_rank", "target_page"])

    # Content clusters: same target_page across multiple rows
    cluster_rows = defaultdict(list)
    for _, r in df.iterrows():
        tp = r.get("target_page")
        if tp:
            cluster_rows[tp].append(r)
    clusters = []
    for tp, rows in cluster_rows.items():
        if len(rows) >= 2:
            sample = rows[0]
            clusters.append({
                "target_page": tp,
                "query_count": len(rows),
                "action_type": sample.get("action_type"),
                "priority":    sorted([r.get("priority") for r in rows], key=lambda p: PRIORITY_RANK.get(p, 99))[0],
                "effort":      sample.get("effort"),
                "queries":     [r.get("query") for r in rows],
            })
    clusters.sort(key=lambda c: -c["query_count"])

    # Top backlog
    backlog = []
    for _, r in df_sorted.iterrows():
        backlog.append({
            "priority":     r.get("priority"),
            "action_type":  r.get("action_type"),
            "target_page":  r.get("target_page"),
            "query":        r.get("query"),
            "expected":     r.get("expected_result"),
        })

    # Maintain rows = the "what's good"
    maintain_rows = df[df["action_type"] == "maintain"]

    # Top-3 actions for executive summary
    top3 = backlog[:3]

    return {
        "target":      target,
        "n_rows":      n_rows,
        "by_action":   by_action,
        "by_priority": by_priority,
        "by_effort":   by_effort,
        "by_coverage": by_coverage,
        "total_effort_weight": total_effort,
        "clusters":    clusters,
        "backlog":     backlog,
        "maintain":    maintain_rows,
        "top3":        top3,
    }


# ---------- charts ----------

def chart_action_donut(by_action, out_path):
    if not by_action: return
    items = sorted(by_action.items())
    labels = [k for k, _ in items]
    values = [v for _, v in items]
    color_map = {"new_article": "#4F81BD", "section_addition": "#5CB6BA",
                 "minor_optimization": "#63BE7B", "maintain": "#BFBFBF"}
    cols = [color_map.get(k, "#CCCCCC") for k in labels]
    fig, ax = plt.subplots(figsize=(5.5, 5.5))
    ax.pie(values, labels=labels, autopct="%1.0f", startangle=90,
           wedgeprops=dict(width=0.4), colors=cols)
    ax.set_title("Recommendations by action type")
    plt.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def chart_priority_bar(by_priority, out_path):
    if not by_priority: return
    order = ["Critical", "High", "Medium", "Low"]
    values = [by_priority.get(p, 0) for p in order]
    color_map = {"Critical": "#F8696B", "High": "#F4B084", "Medium": "#FFEB9C", "Low": "#D9D9D9"}
    cols = [color_map[p] for p in order]
    fig, ax = plt.subplots(figsize=(6, 3.5))
    bars = ax.bar(order, values, color=cols, edgecolor="black")
    ax.set_ylabel("# recommendations")
    ax.set_title("Recommendations by priority")
    for b, v in zip(bars, values):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.1, str(v), ha="center")
    plt.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def chart_effort_bar(by_effort, out_path):
    if not by_effort: return
    order = ["S", "M", "L"]
    values = [by_effort.get(p, 0) for p in order]
    color_map = {"S": "#C6EFCE", "M": "#FFEB9C", "L": "#F8696B"}
    cols = [color_map[p] for p in order]
    fig, ax = plt.subplots(figsize=(7, 3.5))
    bars = ax.bar(order, values, color=cols, edgecolor="black")
    ax.set_ylabel("# recommendations")
    # Title was previously "...M=half-day to day, L=multi-day)" which got
    # truncated to "...L=multi-da" by tight_layout when rendered. Shortened.
    ax.set_title("Recommendations by effort  (S=hours,  M=half-day,  L=multi-day)")
    for b, v in zip(bars, values):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.1, str(v), ha="center")
    plt.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def chart_coverage_donut(by_coverage, out_path):
    if not by_coverage: return
    order = ["comprehensive", "partial", "indirect", "none"]
    values = [by_coverage.get(p, 0) for p in order]
    if sum(values) == 0: return
    color_map = {"comprehensive": "#63BE7B", "partial": "#FFEB9C", "indirect": "#F4B084", "none": "#F8696B"}
    cols = [color_map[p] for p in order]
    fig, ax = plt.subplots(figsize=(5.5, 5.5))
    ax.pie(values, labels=order, autopct="%1.0f", startangle=90,
           wedgeprops=dict(width=0.4), colors=cols)
    ax.set_title("Pre-recommendation coverage by query")
    plt.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


# ---------- PDF ----------

def build_pdf(out_path, df, agg, site, brand_profile, charts):
    doc = SimpleDocTemplate(out_path, pagesize=LETTER,
                            leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=0.6 * inch, bottomMargin=0.6 * inch)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H1Big", parent=styles["Heading1"], fontSize=20, leading=24, spaceAfter=8))
    styles.add(ParagraphStyle(name="Sub", parent=styles["Normal"], fontSize=11, textColor=colors.grey, spaceAfter=12))
    styles.add(ParagraphStyle(name="Big", parent=styles["Normal"], fontSize=14, leading=18, spaceAfter=6))
    styles.add(ParagraphStyle(name="Small", parent=styles["Normal"], fontSize=8, leading=10))
    # Cell style — used inside Tables so multi-line wrapping breathes properly.
    styles.add(ParagraphStyle(name="Cell", parent=styles["Normal"],
                               fontSize=9, leading=11, spaceBefore=0, spaceAfter=0))

    story = []
    today = datetime.now().strftime("%Y-%m-%d")
    target = (brand_profile.get("brand_name")
              or ((brand_profile.get("target_brand") or {}).get("name"))
              or agg["target"] or "Brand")

    # Section 1 — Executive summary
    story.append(Paragraph(f"AEO Content Roadmap — {target}", styles["H1Big"]))
    pages_count = (site or {}).get("page_count", 0)
    sprint_weeks = round(agg["total_effort_weight"] / 12.0, 1)  # ~12 weight units per sprint-week
    story.append(Paragraph(
        f"Audit date: {today}  ·  Recommendations: {agg['n_rows']}  ·  Pages scraped: {pages_count}  ·  "
        f"Effort: {agg['by_effort'].get('S', 0)} S + {agg['by_effort'].get('M', 0)} M + "
        f"{agg['by_effort'].get('L', 0)} L "
        f"(weight {agg['total_effort_weight']} ≈ {sprint_weeks} sprint-weeks of writer time)",
        styles["Sub"]))

    actions = agg["by_action"]
    summary = (f"new_article: {actions.get('new_article', 0)} · "
               f"section_addition: {actions.get('section_addition', 0)} · "
               f"minor_optimization: {actions.get('minor_optimization', 0)} · "
               f"maintain: {actions.get('maintain', 0)}")
    story.append(Paragraph(f"<b>Action-type breakdown:</b> {summary}", styles["Big"]))

    story.append(Paragraph("<b>Top 5 priorities:</b>", styles["Cell"]))
    if agg["backlog"]:
        rows = [[Paragraph("<b>#</b>", styles["Cell"]),
                 Paragraph("<b>Pri</b>", styles["Cell"]),
                 Paragraph("<b>Action</b>", styles["Cell"]),
                 Paragraph("<b>Target page</b>", styles["Cell"]),
                 Paragraph("<b>Why (query)</b>", styles["Cell"])]]
        for i, r in enumerate(agg["backlog"][:5], 1):
            rows.append([
                Paragraph(str(i), styles["Cell"]),
                Paragraph(str(r.get("priority") or ""), styles["Cell"]),
                Paragraph(str(r.get("action_type") or "")[:24], styles["Cell"]),
                Paragraph(str(r.get("target_page") or ""), styles["Cell"]),
                Paragraph(str(r.get("query") or ""), styles["Cell"]),
            ])
        t = Table(rows, colWidths=[0.3 * inch, 0.55 * inch, 1.0 * inch, 2.5 * inch, 2.55 * inch],
                  repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                               ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 4),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                               ("TOPPADDING", (0, 0), (-1, -1), 3),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        story.append(t)

    story.append(PageBreak())

    # Section 2 — Charts (each titled, breathing room between)
    story.append(Paragraph("Roadmap at a glance", styles["Heading1"]))
    chart_titles = {
        "action_donut":     "1. Recommendations by action type",
        "priority_bar":     "2. Recommendations by priority",
        "effort_bar":       "3. Recommendations by effort",
        "coverage_donut":   "4. Pre-recommendation coverage",
    }
    chart_items = [k for k in ["action_donut", "priority_bar", "effort_bar", "coverage_donut"]
                   if charts.get(k)]
    for idx, key in enumerate(chart_items):
        story.append(Paragraph(chart_titles.get(key, key), styles["Sub"]))
        story.append(Image(charts[key], width=6.8 * inch, height=4.2 * inch, kind="proportional"))
        if idx < len(chart_items) - 1:
            story.append(Spacer(1, 16))
    story.append(PageBreak())

    # Section 3 — Content clusters (only render the section if there are clusters;
    # the previous "no clusters" page wasted a whole page on one sentence).
    if agg["clusters"]:
        story.append(Paragraph("Content clusters (high-leverage)", styles["Heading1"]))
        story.append(Paragraph(
            "Each cluster is a single proposed page that, when shipped, helps multiple queries. "
            "Ship the cluster, not the individual rows.", styles["Cell"]))
        story.append(Spacer(1, 6))
        rows = [[Paragraph("<b>Target page</b>", styles["Cell"]),
                 Paragraph("<b>Helps</b>", styles["Cell"]),
                 Paragraph("<b>Action</b>", styles["Cell"]),
                 Paragraph("<b>Pri</b>", styles["Cell"]),
                 Paragraph("<b>Eff</b>", styles["Cell"])]]
        for c in agg["clusters"][:15]:
            rows.append([
                Paragraph(c["target_page"], styles["Cell"]),
                Paragraph(f"{c['query_count']} q", styles["Cell"]),
                Paragraph(c["action_type"], styles["Cell"]),
                Paragraph(c["priority"], styles["Cell"]),
                Paragraph(c["effort"], styles["Cell"]),
            ])
        t = Table(rows, colWidths=[3.3 * inch, 0.7 * inch, 1.4 * inch, 0.8 * inch, 0.7 * inch],
                  repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                               ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 4),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                               ("TOPPADDING", (0, 0), (-1, -1), 3),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        story.append(t)
        story.append(PageBreak())

    # Section 4 — Priority backlog (full table; readable rows, repeats header on page-break)
    story.append(Paragraph("Priority backlog", styles["Heading1"]))
    if agg["backlog"]:
        rows = [[Paragraph("<b>#</b>", styles["Cell"]),
                 Paragraph("<b>Pri</b>", styles["Cell"]),
                 Paragraph("<b>Action</b>", styles["Cell"]),
                 Paragraph("<b>Target page</b>", styles["Cell"]),
                 Paragraph("<b>Query &rarr; Expected result</b>", styles["Cell"])]]
        for i, r in enumerate(agg["backlog"][:30], 1):
            cell_qr = (
                f"<b>Q:</b> {(str(r.get('query') or ''))[:200]}<br/>"
                f"<b>Result:</b> {(str(r.get('expected') or ''))[:280]}"
            )
            rows.append([
                Paragraph(str(i), styles["Cell"]),
                Paragraph(str(r.get("priority") or ""), styles["Cell"]),
                Paragraph(str(r.get("action_type") or "")[:22], styles["Cell"]),
                Paragraph(str(r.get("target_page") or ""), styles["Cell"]),
                Paragraph(cell_qr, styles["Cell"]),
            ])
        t = Table(rows, colWidths=[0.3 * inch, 0.55 * inch, 1.0 * inch, 2.0 * inch, 3.05 * inch],
                  repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                               ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 3),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                               ("TOPPADDING", (0, 0), (-1, -1), 3),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        story.append(t)
    story.append(PageBreak())

    # Section 5 — What's good (only rendered if there ARE maintain rows; previously
    # it left a near-empty page when none existed).
    if len(agg["maintain"]):
        story.append(Paragraph("What's good — don't break this", styles["Heading1"]))
        groups = defaultdict(list)
        for _, r in agg["maintain"].iterrows():
            groups[r.get("target_page") or ""].append(r)
        story.append(Paragraph(
            f"<b>{len(groups)}</b> winning pages cover <b>{len(agg['maintain'])}</b> queries. "
            "Future redesigns must preserve these.", styles["Cell"]))
        story.append(Spacer(1, 6))
        rows = [[Paragraph("<b>Target page</b>", styles["Cell"]),
                 Paragraph("<b>Q's</b>", styles["Cell"]),
                 Paragraph("<b>Why preserve</b>", styles["Cell"])]]
        for tp, gp in groups.items():
            why = (gp[0].get("expected_result") or "")[:340]
            rows.append([
                Paragraph(tp, styles["Cell"]),
                Paragraph(str(len(gp)), styles["Cell"]),
                Paragraph(why, styles["Cell"]),
            ])
        t = Table(rows, colWidths=[2.6 * inch, 0.5 * inch, 3.8 * inch], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                               ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 4),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                               ("TOPPADDING", (0, 0), (-1, -1), 3),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        story.append(t)
        story.append(PageBreak())

    # Section 6 — What's bad (visibility holes) — readable Paragraph cells
    story.append(Paragraph("What's bad — visibility holes", styles["Heading1"]))
    none_rows = df[df["coverage_level"] == "none"]
    crit_rows = df[df["priority"] == "Critical"]
    holes = pd.concat([none_rows, crit_rows]).drop_duplicates(subset=["query"])
    if len(holes):
        story.append(Paragraph(
            f"<b>{len(holes)}</b> queries have either zero coverage on the current site "
            "OR Critical priority. These are the 'if we do nothing' picture.",
            styles["Cell"]))
        story.append(Spacer(1, 6))
        rows = [[Paragraph("<b>Coverage</b>", styles["Cell"]),
                 Paragraph("<b>Pri</b>", styles["Cell"]),
                 Paragraph("<b>Query</b>", styles["Cell"]),
                 Paragraph("<b>Recommended action</b>", styles["Cell"])]]
        for _, r in holes.head(20).iterrows():
            rows.append([
                Paragraph(str(r.get("coverage_level") or ""), styles["Cell"]),
                Paragraph(str(r.get("priority") or ""), styles["Cell"]),
                Paragraph(str(r.get("query") or ""), styles["Cell"]),
                Paragraph(
                    f"<b>{r.get('action_type') or ''}</b><br/>{r.get('target_page') or ''}",
                    styles["Cell"]),
            ])
        t = Table(rows, colWidths=[0.85 * inch, 0.5 * inch, 3.0 * inch, 2.55 * inch], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                               ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 4),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                               ("TOPPADDING", (0, 0), (-1, -1), 3),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        story.append(t)
    else:
        story.append(Paragraph("No coverage=none or Critical-priority queries — no urgent holes.",
                               styles["Cell"]))
    story.append(PageBreak())

    # Section 7 — Per-action-type playbooks (Table form so each row stays a unit
    # and tighter wrapping doesn't collapse the leading)
    story.append(Paragraph("Per-action-type playbooks", styles["Heading1"]))
    playbooks = [
        ("new_article",
         "What: a brand-new page on the brand's domain answering a query the site doesn't cover today.",
         "Why for AEO: AI engines cite long-form, well-structured pages with question-headed sections + direct answers + comparison tables.",
         "How: 4-8 sections, first 60 words = direct answer, FAQ + HowTo schema, &ge; 2 internal links + &ge; 1 authoritative external link."),
        ("section_addition",
         "What: a new 150-400 word section inserted into an existing page that already partially covers the topic.",
         "Why for AEO: leverages the existing page's authority while filling the specific subtopic the LLM is looking for.",
         "How: heading phrased as a question, 60-word direct answer in the first paragraph, 1 internal + 1 external link, in the brand's voice."),
        ("minor_optimization",
         "What: 1-3 sentences of new copy + a few keyword/format tweaks on an existing page.",
         "Why for AEO: surgical edits often unlock featured-snippet eligibility without rewriting the whole page.",
         "How: replace or add 1-3 sentences focused on direct-answer pattern + keyword integration; &ge; 1 internal link."),
        ("maintain",
         "What: explicit 'do nothing' for pages already winning the query.",
         "Why for AEO: site redesigns regularly regress winning pages because nobody named them.",
         "How: record the page + the patterns that are working (numbered list, dedicated URL, schema, etc.) for redesign briefs."),
    ]
    pb_rows = [[Paragraph("<b>Action type</b>", styles["Cell"]),
                Paragraph("<b>What / Why / How</b>", styles["Cell"])]]
    for name, what, why, how in playbooks:
        body = f"<b>What:</b> {what[6:]}<br/><b>Why:</b> {why[14:]}<br/><b>How:</b> {how[5:]}"
        pb_rows.append([Paragraph(f"<b>{name}</b>", styles["Cell"]),
                         Paragraph(body, styles["Cell"])])
    t = Table(pb_rows, colWidths=[1.4 * inch, 5.5 * inch], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                           ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 4),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                           ("TOPPADDING", (0, 0), (-1, -1), 4),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.append(t)
    story.append(PageBreak())

    # Section 8 — Methodology — denser, more useful
    story.append(Paragraph("Methodology", styles["Heading1"]))
    by_cov = ", ".join(f"{k}={v}" for k, v in agg["by_coverage"].items()) or "n/a"
    by_pri = ", ".join(f"{k}={v}" for k, v in agg["by_priority"].most_common()) or "n/a"
    by_eff = ", ".join(f"{k}={v}" for k, v in agg["by_effort"].items()) or "n/a"
    by_act = ", ".join(f"{k}={v}" for k, v in agg["by_action"].most_common()) or "n/a"

    method_rows = [
        ["Pages scraped",            f"{pages_count}  (mode: {(site or {}).get('mode') or 'n/a'})"],
        ["Recommendations produced", f"{agg['n_rows']}"],
        ["Action-type breakdown",    by_act],
        ["Priority distribution",    by_pri],
        ["Effort distribution",      by_eff + f"  (weight {agg['total_effort_weight']} ~= {sprint_weeks} sprint-weeks)"],
        ["Pre-recommendation coverage", by_cov],
        ["Content clusters detected", f"{len(agg['clusters'])} cluster(s) of >= 2 queries"],
        ["Maintain rows",             f"{len(agg['maintain'])}"],
    ]
    rows = [[Paragraph(f"<b>{k}</b>", styles["Cell"]),
             Paragraph(str(v), styles["Cell"])] for k, v in method_rows]
    t = Table(rows, colWidths=[2.0 * inch, 4.9 * inch])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                           ("LEFTPADDING", (0, 0), (-1, -1), 4),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                           ("TOPPADDING", (0, 0), (-1, -1), 3),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story.append(t)
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Per-query recommendation generated by an LLM judge using the rubric in "
        "<font face='Courier'>references/output-schema.md</font>, "
        "<font face='Courier'>action-types.md</font>, and "
        "<font face='Courier'>seo-aeo-best-practices.md</font>. "
        "Spot-checks of 3-5 rows are recommended before shipping the roadmap to a content team.",
        styles["Small"]))

    doc.build(story)


def write_executive_md(out_path, agg, brand_profile, site=None):
    target = (brand_profile.get("brand_name")
              or ((brand_profile.get("target_brand") or {}).get("name"))
              or "Brand")
    today = datetime.now().strftime("%Y-%m-%d")
    actions = agg["by_action"]
    sprint_weeks = round(agg["total_effort_weight"] / 12.0, 1)
    pages_count = (site or {}).get("page_count") if site else None

    lines = [
        f"# AEO Content Roadmap — Executive Summary — {target}",
        "",
        f"**Audit date:** {today}  ·  "
        f"**Recommendations:** {agg['n_rows']}  ·  "
        + (f"**Pages scraped:** {pages_count}  ·  " if pages_count is not None else "")
        + f"**Effort:** {agg['by_effort'].get('S', 0)} S + {agg['by_effort'].get('M', 0)} M + "
          f"{agg['by_effort'].get('L', 0)} L "
          f"(weight {agg['total_effort_weight']} ~= {sprint_weeks} sprint-weeks)",
        "",
        "## Headline",
        f"- **{actions.get('new_article', 0)} new articles** to write",
        f"- **{actions.get('section_addition', 0)} section additions** to existing pages",
        f"- **{actions.get('minor_optimization', 0)} minor optimizations** (1-3 sentence tweaks)",
        f"- **{actions.get('maintain', 0)} maintain rows** (pages already winning — don't break)",
    ]

    # Priority distribution
    by_pri = agg.get("by_priority")
    if by_pri:
        lines += ["",
                  "**Priority distribution:** "
                  + ", ".join(f"{k}={v}" for k, v in by_pri.most_common())]

    # Coverage distribution
    by_cov = agg.get("by_coverage")
    if by_cov:
        lines += ["",
                  "**Pre-recommendation coverage:** "
                  + ", ".join(f"{k}={v}" for k, v in by_cov.items())]

    # Top 5 priorities
    lines += ["", "## Top 5 priorities"]
    for i, r in enumerate(agg["backlog"][:5], 1):
        lines.append(f"{i}. **{r.get('priority')}** &middot; `{r.get('action_type')}` "
                     f"&middot; {(r.get('target_page') or '')}")
        if r.get("query"):
            lines.append(f"   _Query: {(r.get('query') or '')[:200]}_")
        if r.get("expected"):
            lines.append(f"   _Expected: {(r.get('expected') or '')[:200]}_")
        lines.append("")

    # Content clusters
    if agg.get("clusters"):
        lines += ["## Content clusters (high-leverage)"]
        for c in agg["clusters"][:5]:
            lines.append(f"- **{c['target_page']}** &rarr; covers **{c['query_count']} queries** "
                         f"(action: `{c['action_type']}`, priority {c['priority']}, effort {c['effort']})")
        if len(agg["clusters"]) > 5:
            lines.append(f"_(... +{len(agg['clusters']) - 5} more clusters in the full PDF.)_")

    # Maintain rows
    if hasattr(agg.get("maintain"), "__len__") and len(agg["maintain"]):
        from collections import defaultdict
        groups = defaultdict(list)
        for _, r in agg["maintain"].iterrows():
            groups[r.get("target_page") or ""].append(r)
        lines += ["", "## What's already winning (don't break)"]
        for tp, gp in list(groups.items())[:5]:
            lines.append(f"- {tp}  _({len(gp)} queries)_")

    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--recommendations", required=True)
    ap.add_argument("--brand-profile", required=True)
    ap.add_argument("--pages-index", required=True)
    ap.add_argument("--aeo-scorecard", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--exec-md", default=None)
    args = ap.parse_args()

    df = pd.read_excel(args.xlsx, sheet_name=0)
    with open(args.brand_profile, encoding="utf-8") as f:
        brand_profile = json.load(f)
    with open(args.pages_index, encoding="utf-8") as f:
        site = json.load(f)
    recs = []
    with open(args.recommendations, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recs.append(json.loads(line))

    agg = aggregate(df, recs, site)

    with tempfile.TemporaryDirectory() as tmp:
        charts = {}
        chart_action_donut(agg["by_action"], f"{tmp}/action_donut.png")
        charts["action_donut"] = f"{tmp}/action_donut.png" if agg["by_action"] else None
        chart_priority_bar(agg["by_priority"], f"{tmp}/priority_bar.png")
        charts["priority_bar"] = f"{tmp}/priority_bar.png" if agg["by_priority"] else None
        chart_effort_bar(agg["by_effort"], f"{tmp}/effort_bar.png")
        charts["effort_bar"] = f"{tmp}/effort_bar.png" if agg["by_effort"] else None
        chart_coverage_donut(agg["by_coverage"], f"{tmp}/coverage_donut.png")
        charts["coverage_donut"] = f"{tmp}/coverage_donut.png" if agg["by_coverage"] else None

        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        build_pdf(args.out, df, agg, site, brand_profile, charts)

    exec_md = args.exec_md or str(Path(args.out).parent / "aeo_content_executive_summary.md")
    write_executive_md(exec_md, agg, brand_profile, site=site)

    print(f"Wrote {args.out} and {exec_md}", file=sys.stderr)


if __name__ == "__main__":
    main()
