#!/usr/bin/env python3
"""
Phase 6 (part 2) — Render the PDF report and the markdown executive summary.

Reads the compiled XLSX scorecard + brand_profile.json + gap_rows.jsonl, generates
charts via matplotlib (saved as PNG to a temp dir), and assembles the multi-section
PDF via ReportLab Platypus flowables.

Usage:
    python render_pdf_report.py --xlsx output/aeo_scorecard.xlsx \
        --brand-profile output/brand_profile.json \
        --gaps output/gap_rows.jsonl \
        --out output/aeo_report.pdf
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
                                Table, TableStyle, PageBreak, KeepTogether)


ASSESSMENT_ORDER = ["Excellent", "Good", "Moderate", "Weak", "Not visible"]
PRIORITY_ORDER   = ["Critical", "High", "Medium", "Low"]


# ---------- aggregation ----------

def aggregate(df, brand_profile, gap_rows_by_row_id):
    # `brand_profile.json` from intake uses `target_brand.name`; older fixtures
    # may use the flat `brand_name` field. Accept either.
    target = (brand_profile.get("brand_name")
              or ((brand_profile.get("target_brand") or {}).get("name"))
              or "Target")

    n_rows = len(df)
    mention_rate = (df["brand_mentioned"].astype(bool).sum() / n_rows * 100) if n_rows else 0
    sov_avg = float(df["share_of_voice_percentage"].mean()) if n_rows else 0
    strength_avg = float(df["strength_score"].mean()) if n_rows else 0
    sentiment_avg = float(df["sentiment_direction_score"].mean()) if n_rows else 0

    # Aggregate brand counts
    brand_counter = Counter()
    for _, row in df.iterrows():
        bml = row.get("brands_mentioned_list")
        if not isinstance(bml, str):
            bml = ""
        for b in bml.split(","):
            b = b.strip()
            if b:
                brand_counter[b] += 1

    # Per-engine mention rate
    per_engine_mention = {}
    if "engine" in df.columns:
        for engine, sub in df.groupby("engine"):
            per_engine_mention[engine] = float(sub["brand_mentioned"].astype(bool).sum() / len(sub) * 100)

    # Per-category x engine SOV grid
    cat_engine_sov = defaultdict(dict)
    if "engine" in df.columns and "query_category" in df.columns:
        for (cat, engine), sub in df.groupby(["query_category", "engine"]):
            cat_engine_sov[cat][engine] = float(sub["share_of_voice_percentage"].mean())

    # Aggregate overall visibility assessment — derived from average strength
    # so the rule is the same as the per-row rubric in metrics-rubric.md
    # (Strength 8+ Excellent, 6+ Good, 3-5 Moderate, 1-2 Weak, 0 Not visible).
    # Documented in references/output-schema.md.
    asses_counts = Counter(df["overall_visibility_assessment"].dropna())
    if strength_avg >= 8:
        overall = "Excellent"
    elif strength_avg >= 6:
        overall = "Good"
    elif strength_avg >= 3:
        overall = "Moderate"
    elif strength_avg >= 1:
        overall = "Weak"
    else:
        overall = "Not visible"

    # Top actions deduplicated (sorted by priority, then by frequency)
    action_counter = Counter()
    action_priority = {}
    for _, row in df.iterrows():
        a = (row.get("optimization_action") or "").strip()
        if a:
            action_counter[a] += 1
            action_priority[a] = row.get("optimization_priority") or action_priority.get(a, "Medium")

    def priority_rank(p): return PRIORITY_ORDER.index(p) if p in PRIORITY_ORDER else 99
    sorted_actions = sorted(action_counter.items(),
                            key=lambda kv: (priority_rank(action_priority.get(kv[0], "Medium")), -kv[1]))
    top_actions = sorted_actions[:5]

    # Risks: framed as "if we do nothing, this remains broken". Pulled from
    # gap_details on the highest-severity rows, NOT from optimization_action
    # (which would just echo the action plan).
    risks = []
    seen_risk_keys = set()
    sorted_for_risk = df.sort_values(
        by=["optimization_priority", "strength_score"],
        key=lambda col: col.map(
            {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
        ) if col.name == "optimization_priority" else col
    )
    for _, row in sorted_for_risk.iterrows():
        gap = (row.get("content_gap") or "").strip()
        if not gap:
            continue
        # Use first phrase of content_gap as the risk seed (e.g. "Total Visibility Gap (Critical):")
        seed = gap.split(":", 1)[0].split(";", 1)[0].strip()
        if not seed or seed in seen_risk_keys:
            continue
        seen_risk_keys.add(seed)
        engine = row.get("engine") or ""
        category = row.get("query_category") or ""
        risks.append(
            f"If unaddressed, {seed.lower()} persists across {engine} "
            f"(seen on category-{category} queries)."
        )
        if len(risks) >= 5:
            break

    return {
        "target":             target,
        "n_rows":             n_rows,
        "mention_rate":       mention_rate,
        "sov_avg":            sov_avg,
        "strength_avg":       strength_avg,
        "sentiment_avg":      sentiment_avg,
        "brand_counter":      brand_counter,
        "per_engine_mention": per_engine_mention,
        "cat_engine_sov":     cat_engine_sov,
        "asses_counts":       asses_counts,
        "overall":            overall,
        "top_actions":        top_actions,
        "risks":              risks,
    }


# ---------- charts ----------

def chart_share_of_voice_donut(brand_counter, target, out_path):
    """SoV donut. Always include the target brand even if its slice is tiny;
    use a side legend so 8+ slices remain readable; suppress "Other" when it
    would dominate (>60%) — that's a sign too few brands cleared the noise floor
    and the chart is more honest as top-N + (target if missing) than a giant
    'Other' wedge dwarfing the real data."""
    sorted_brands = sorted(brand_counter.items(), key=lambda kv: -kv[1])
    top_n = 8
    top = sorted_brands[:top_n]
    other_total = sum(v for _, v in sorted_brands[top_n:])

    # Make sure the target brand is in the slice list even if it didn't make top_n
    if target and not any(k.lower() == target.lower() for k, _ in top):
        target_pair = next(((k, v) for k, v in sorted_brands if k.lower() == target.lower()), None)
        if target_pair:
            # Drop the smallest of top to fit the target
            top = top[:-1] + [target_pair]
            top.sort(key=lambda kv: -kv[1])

    labels = [k for k, _ in top]
    values = [v for _, v in top]
    total_top = sum(values) or 1
    other_pct = 100 * other_total / (total_top + other_total) if (total_top + other_total) else 0

    # Suppress huge "Other" — it crushes the visible data
    if other_total and other_pct < 60:
        labels.append("Other")
        values.append(other_total)

    target_idx = next((i for i, l in enumerate(labels) if l.lower() == target.lower()), None)
    explode = [0.0] * len(labels)
    if target_idx is not None:
        explode[target_idx] = 0.08

    # Color target distinctively
    cmap = plt.get_cmap("tab20")
    cols = [cmap(i % 20) for i in range(len(labels))]
    if target_idx is not None:
        cols[target_idx] = "#F8696B"      # red — easy to spot

    fig, ax = plt.subplots(figsize=(7.5, 5.5))
    wedges, _ = ax.pie(values, labels=None, startangle=90, explode=explode,
                       wedgeprops=dict(width=0.4), colors=cols)
    # Legend on the side keeps labels off the rim
    pct_total = sum(values)
    legend_labels = []
    for lab, v in zip(labels, values):
        pct = 100 * v / pct_total if pct_total else 0
        marker = " [TARGET]" if lab.lower() == (target or "").lower() else ""
        legend_labels.append(f"{lab}{marker} — {v} mentions ({pct:.1f}%)")
    ax.legend(wedges, legend_labels, loc="center left", bbox_to_anchor=(1.0, 0.5),
              fontsize=9, frameon=False)
    sub = f" (Other suppressed: ~{other_pct:.0f}%)" if other_total and other_pct >= 60 else ""
    ax.set_title(f"Share of voice — {target}{sub}")
    plt.tight_layout()
    fig.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close(fig)


def chart_per_engine_mention(per_engine, target, out_path):
    if not per_engine:
        return
    items = sorted(per_engine.items())
    labels = [k for k, _ in items]
    vals = [v for _, v in items]
    fig, ax = plt.subplots(figsize=(7, 4))
    bars = ax.bar(labels, vals, color="#4F81BD")
    ax.set_ylabel("% of queries mentioning the brand")
    ax.set_title(f"Brand mention rate by engine — {target}")
    ax.set_ylim(0, 100)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 1, f"{v:.0f}%", ha="center", fontsize=9)
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def chart_cat_engine_heatmap(cat_engine_sov, target, out_path):
    if not cat_engine_sov:
        return
    cats = sorted(cat_engine_sov.keys())
    engines = sorted({e for d in cat_engine_sov.values() for e in d.keys()})
    if not cats or not engines:
        return
    matrix = [[cat_engine_sov.get(c, {}).get(e, 0.0) for e in engines] for c in cats]

    fig, ax = plt.subplots(figsize=(7, max(3, 0.5 * len(cats) + 1)))
    im = ax.imshow(matrix, cmap="YlGn", aspect="auto", vmin=0, vmax=max(50, max(max(r) for r in matrix) if matrix else 0))
    ax.set_xticks(range(len(engines))); ax.set_xticklabels(engines, rotation=20, ha="right")
    ax.set_yticks(range(len(cats)));    ax.set_yticklabels([f"Cat {c}" for c in cats])
    for i in range(len(cats)):
        for j in range(len(engines)):
            v = matrix[i][j]
            ax.text(j, i, f"{v:.0f}", ha="center", va="center",
                    color="black" if v < 30 else "white", fontsize=8)
    ax.set_title(f"Average share-of-voice (%) — {target} by query category x engine")
    fig.colorbar(im, ax=ax, label="SoV %")
    plt.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def chart_strength_distribution(df, target, out_path):
    if df.empty: return
    fig, ax = plt.subplots(figsize=(6, 3.5))
    ax.hist(df["strength_score"].dropna(), bins=range(0, 12), color="#63BE7B", edgecolor="black")
    ax.set_xlabel("Strength score (0–10)")
    ax.set_ylabel("# rows")
    ax.set_title(f"Strength score distribution — {target}")
    ax.set_xticks(range(0, 11))
    plt.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def chart_sentiment_box(df, target, out_path):
    if df.empty or "engine" not in df.columns: return
    engines = sorted(df["engine"].dropna().unique())
    data = [df[df["engine"] == e]["sentiment_direction_score"].dropna() for e in engines]
    if not any(len(d) for d in data): return
    fig, ax = plt.subplots(figsize=(6.5, 3.8))
    try:
        ax.boxplot(data, tick_labels=engines, showmeans=True)
    except TypeError:
        ax.boxplot(data, labels=engines, showmeans=True)
    ax.set_ylabel("Sentiment (-50 to +50)")
    ax.set_title(f"Sentiment by engine — {target}")
    # Force the rubric range so a 0..3 actual range doesn't visually dominate the
    # whole canvas; gives the reader the right "yes this is near zero" intuition.
    ax.set_ylim(-50, 50)
    ax.axhline(0, color="gray", linewidth=0.8)
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


# ---------- PDF ----------

def build_pdf(out_path, df, brand_profile, agg, charts):
    doc = SimpleDocTemplate(out_path, pagesize=LETTER,
                            leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=0.6 * inch, bottomMargin=0.6 * inch)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H1Big", parent=styles["Heading1"], fontSize=20, leading=24, spaceAfter=8))
    styles.add(ParagraphStyle(name="Sub", parent=styles["Normal"], fontSize=11, textColor=colors.grey, spaceAfter=12))
    styles.add(ParagraphStyle(name="Big", parent=styles["Normal"], fontSize=14, leading=18, spaceAfter=6))
    styles.add(ParagraphStyle(name="Small", parent=styles["Normal"], fontSize=8, leading=10))
    # `Cell` is the canonical style for content INSIDE Table cells:
    # 9pt font with 11pt leading so multi-line wrapping breathes; spaceBefore/
    # spaceAfter are 0 so adjacent cells don't gain extra padding above/below
    # what the Table itself provides. Using a dedicated style fixed the
    # Country Bean "wall of black text" overlap on the action-plan / what's-bad
    # sections — those were Paragraphs flowed at the document level which let
    # ReportLab collapse leading at small sizes.
    styles.add(ParagraphStyle(name="Cell", parent=styles["Normal"],
                               fontSize=9, leading=11, spaceBefore=0, spaceAfter=0))

    story = []
    target = agg["target"]
    today = datetime.now().strftime("%Y-%m-%d")  # local date — UTC drifts a day for late-PT runs

    # Section 1 — Executive summary
    story.append(Paragraph(f"AEO Brand Visibility Report — {target}", styles["H1Big"]))
    story.append(Paragraph(f"Audited: {today}  ·  Rows: {agg['n_rows']}  ·  "
                           f"Engines: {', '.join(sorted(set(df['engine'].dropna()))) if 'engine' in df.columns else 'n/a'}",
                           styles["Sub"]))

    badge_color_hex = {"Excellent": "008000", "Good": "63BE7B", "Moderate": "B58900",
                       "Weak": "F4B084", "Not visible": "F8696B"}.get(agg["overall"], "808080")
    badge = Paragraph(f"<b>Overall visibility:</b> "
                      f"<font color='#{badge_color_hex}'><b>{agg['overall']}</b></font>",
                      styles["Big"])
    story.append(badge)

    story.append(Paragraph(
        f"<b>Top numbers:</b>  Mention rate: <b>{agg['mention_rate']:.1f}%</b>  ·  "
        f"Avg share-of-voice: <b>{agg['sov_avg']:.1f}%</b>  ·  "
        f"Avg strength: <b>{agg['strength_avg']:.1f}/10</b>  ·  "
        f"Avg sentiment: <b>{agg['sentiment_avg']:+.1f}</b>",
        styles["Normal"]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("<b>Top actions (deduplicated, by priority x frequency):</b>", styles["Cell"]))
    if agg["top_actions"]:
        # Wrap action text in Paragraph so long strings flow inside the cell
        # instead of overflowing into the neighbour column.
        rows = [[Paragraph("<b>#</b>", styles["Cell"]),
                 Paragraph("<b>Action</b>", styles["Cell"]),
                 Paragraph("<b>Affected<br/>rows</b>", styles["Cell"])]]
        for i, (a, n) in enumerate(agg["top_actions"][:6], 1):
            rows.append([Paragraph(str(i), styles["Cell"]),
                         Paragraph(a, styles["Cell"]),
                         Paragraph(str(n), styles["Cell"])])
        t = Table(rows, colWidths=[0.3 * inch, 6.0 * inch, 0.6 * inch], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                               ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 4),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                               ("TOPPADDING", (0, 0), (-1, -1), 4),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story.append(t)
    else:
        story.append(Paragraph("(no actions ranked)", styles["Cell"]))

    if agg["risks"]:
        story.append(Spacer(1, 10))
        story.append(Paragraph("<b>If we do nothing — top risks:</b>", styles["Cell"]))
        for r in agg["risks"]:
            story.append(Paragraph(f"&bull; {r}", styles["Small"]))

    story.append(PageBreak())

    # Section 2 — Charts (one per page so each gets full breathing room)
    story.append(Paragraph("Visibility at a glance", styles["Heading1"]))
    chart_titles = {
        "sov_donut":         "1. Share of voice",
        "engine_bar":        "2. Mention rate by engine",
        "category_heatmap":  "3. Share-of-voice by query category x engine",
        "strength_hist":     "4. Strength-score distribution",
        "sentiment_box":     "5. Sentiment by engine",
    }
    chart_items = [k for k in ["sov_donut", "engine_bar", "category_heatmap",
                                "strength_hist", "sentiment_box"] if charts.get(k)]
    for idx, key in enumerate(chart_items):
        story.append(Paragraph(chart_titles.get(key, key), styles["Sub"]))
        story.append(Image(charts[key], width=6.8 * inch, height=4.4 * inch, kind="proportional"))
        if idx < len(chart_items) - 1:
            story.append(Spacer(1, 18))
    story.append(PageBreak())

    # Section 3 — Competitive landscape
    story.append(Paragraph("Competitive landscape", styles["Heading1"]))
    bc = agg["brand_counter"]
    if bc:
        sorted_b = sorted(bc.items(), key=lambda kv: -kv[1])
        rows = [[Paragraph("<b>Brand</b>", styles["Cell"]),
                 Paragraph("<b>Rows<br/>mentioned in</b>", styles["Cell"]),
                 Paragraph("<b>% of<br/>total mentions</b>", styles["Cell"])]]
        total_mentions = sum(bc.values()) or 1
        for b, n in sorted_b[:20]:
            pct = 100 * n / total_mentions
            label = f"<b>{b}</b> &laquo;TARGET&raquo;" if b.lower() == target.lower() else b
            rows.append([Paragraph(label, styles["Cell"]),
                         Paragraph(str(n), styles["Cell"]),
                         Paragraph(f"{pct:.1f}%", styles["Cell"])])
        t = Table(rows, colWidths=[4.2 * inch, 1.3 * inch, 1.4 * inch], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                               ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 4),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                               ("TOPPADDING", (0, 0), (-1, -1), 3),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        story.append(t)

    # New competitors surfaced (vs known) — concrete intelligence
    known = ((brand_profile.get("competitors") or {}).get("direct") or []) + \
            ((brand_profile.get("competitors") or {}).get("indirect") or [])
    known_lower = {k.lower() for k in known}
    new_brands = sorted(
        [b for b in bc.keys() if b.lower() not in known_lower and b.lower() != target.lower()],
        key=lambda b: -bc[b],
    )
    if new_brands:
        story.append(Spacer(1, 12))
        story.append(Paragraph("<b>Brands surfaced that were NOT in the known competitor list:</b>",
                               styles["Cell"]))
        story.append(Paragraph(
            f"({len(new_brands)} surfaced, top 30 shown by mention count):",
            styles["Small"]))
        story.append(Paragraph(
            ", ".join(f"{b} ({bc[b]})" for b in new_brands[:30]),
            styles["Small"]))

    # Section 4 + 5 — What's good and What's bad — only render if non-empty.
    # (Empty sections previously left near-empty pages with one stranded sentence.)
    good = df[df["strength_score"] >= 7] if "strength_score" in df.columns else df.iloc[0:0]
    bad  = df[df["optimization_priority"] == "Critical"] if "optimization_priority" in df.columns else df.iloc[0:0]

    if len(good) or len(bad):
        story.append(PageBreak())
        story.append(Paragraph("What's good (keep doing) &nbsp; / &nbsp; What's bad (fix urgently)",
                               styles["Heading1"]))

        if len(good):
            story.append(Paragraph(
                f"<b>What's good</b> — {len(good)} row(s) scoring Strength &ge; 7:",
                styles["Cell"]))
            rows = [[Paragraph("<b>Engine</b>", styles["Cell"]),
                     Paragraph("<b>Query</b>", styles["Cell"]),
                     Paragraph("<b>Str</b>", styles["Cell"]),
                     Paragraph("<b>SoV</b>", styles["Cell"]),
                     Paragraph("<b>Sent</b>", styles["Cell"])]]
            for _, r in good.head(15).iterrows():
                rows.append([
                    Paragraph(str(r.get("engine") or ""), styles["Cell"]),
                    Paragraph(str(r.get("query_tested") or "")[:240], styles["Cell"]),
                    Paragraph(f"{r.get('strength_score', 0)}/10", styles["Cell"]),
                    Paragraph(f"{r.get('share_of_voice_percentage', 0):.1f}%", styles["Cell"]),
                    Paragraph(f"{int(r.get('sentiment_direction_score') or 0):+}", styles["Cell"]),
                ])
            t = Table(rows, colWidths=[1.0 * inch, 4.3 * inch, 0.5 * inch, 0.5 * inch, 0.6 * inch],
                      repeatRows=1)
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                                   ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 3),
                                   ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                                   ("TOPPADDING", (0, 0), (-1, -1), 3),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
            story.append(t)
            story.append(Spacer(1, 12))
        else:
            story.append(Paragraph(
                "<b>What's good</b>: no rows scored Strength &ge; 7 — the brand has no clear AEO wins this run.",
                styles["Cell"]))
            story.append(Spacer(1, 8))

        if len(bad):
            story.append(Paragraph(
                f"<b>What's bad</b> — {len(bad)} Critical-priority row(s):",
                styles["Cell"]))
            rows = [[Paragraph("<b>Engine</b>", styles["Cell"]),
                     Paragraph("<b>Query &amp; recommended action</b>", styles["Cell"])]]
            for _, r in bad.head(20).iterrows():
                cell = (
                    f"<i>{(str(r.get('query_tested') or ''))[:160]}</i><br/>"
                    f"<b>Action:</b> {(str(r.get('optimization_action') or ''))[:300]}<br/>"
                    f"<b>Why:</b> {(str(r.get('optimization_rationale') or ''))[:280]}"
                )
                rows.append([
                    Paragraph(str(r.get("engine") or ""), styles["Cell"]),
                    Paragraph(cell, styles["Cell"]),
                ])
            t = Table(rows, colWidths=[1.0 * inch, 5.9 * inch], repeatRows=1)
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                                   ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 4),
                                   ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                                   ("TOPPADDING", (0, 0), (-1, -1), 4),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
            story.append(t)

    # Section 6 — Action plan (deduplicated) — Table of (#, Action, Helps N rows)
    if agg["top_actions"]:
        story.append(PageBreak())
        story.append(Paragraph("Action plan (deduplicated)", styles["Heading1"]))
        story.append(Paragraph(
            "Per-row recommendations collapsed by exact-match. The same action appearing multiple "
            "times is shown once with the count of rows it would address.",
            styles["Cell"]))
        story.append(Spacer(1, 6))
        rows = [[Paragraph("<b>#</b>", styles["Cell"]),
                 Paragraph("<b>Recommended action</b>", styles["Cell"]),
                 Paragraph("<b>Helps</b>", styles["Cell"])]]
        for i, (a, n) in enumerate(agg["top_actions"][:20], 1):
            rows.append([
                Paragraph(str(i), styles["Cell"]),
                Paragraph(a, styles["Cell"]),
                Paragraph(f"{n} row(s)", styles["Cell"]),
            ])
        t = Table(rows, colWidths=[0.3 * inch, 5.9 * inch, 0.7 * inch], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                               ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 4),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                               ("TOPPADDING", (0, 0), (-1, -1), 4),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story.append(t)

    # Section 7 — Methodology — kept compact + factual.
    story.append(PageBreak())
    story.append(Paragraph("Methodology", styles["Heading1"]))
    eng_used = sorted(set(df["engine"].dropna())) if "engine" in df.columns else []
    cats = Counter(df["query_category"].dropna()) if "query_category" in df.columns else {}
    pri = Counter(df["optimization_priority"].dropna()) if "optimization_priority" in df.columns else {}
    asses = Counter(df["overall_visibility_assessment"].dropna()) if "overall_visibility_assessment" in df.columns else {}

    method_rows = [
        ["Engines queried", f"{len(eng_used)} ({', '.join(eng_used) or 'n/a'})"],
        ["Total rows scored", f"{len(df)}"],
        ["Brand mention rate", f"{agg['mention_rate']:.1f}% of rows"],
        ["Avg share-of-voice", f"{agg['sov_avg']:.1f}%"],
        ["Avg strength score", f"{agg['strength_avg']:.1f} / 10"],
        ["Avg sentiment",  f"{agg['sentiment_avg']:+.1f} (range -50..+50)"],
        ["Query categories", ", ".join(f"{k}={v}" for k, v in sorted(cats.items())) or "n/a"],
        ["Priority distribution", ", ".join(f"{k}={v}" for k, v in pri.most_common()) or "n/a"],
        ["Assessment distribution", ", ".join(f"{k}={v}" for k, v in asses.most_common()) or "n/a"],
    ]
    rows = [[Paragraph(f"<b>{k}</b>", styles["Cell"]),
             Paragraph(str(v), styles["Cell"])] for k, v in method_rows]
    t = Table(rows, colWidths=[1.9 * inch, 5.0 * inch])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                           ("LEFTPADDING", (0, 0), (-1, -1), 4),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                           ("TOPPADDING", (0, 0), (-1, -1), 3),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story.append(t)
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "Per-row scoring used a judge LLM following the rubric in "
        "<font face='Courier'>references/metrics-rubric.md</font> and "
        "<font face='Courier'>gap-analysis-rubric.md</font>. "
        "Spot-checks of 3-5 rows per phase are recommended before relying on the aggregate.",
        styles["Small"]))

    doc.build(story)


def write_executive_md(out_path, agg, brand_profile, df=None):
    target = agg["target"]
    lines = [
        f"# AEO Executive Summary — {target}",
        "",
        f"**Audited:** {datetime.now().strftime('%Y-%m-%d')}  ·  "
        f"**Rows scored:** {agg['n_rows']}  ·  "
        f"**Engines:** {', '.join(sorted(set(df['engine'].dropna()))) if df is not None and 'engine' in df.columns else 'n/a'}",
        "",
        f"## Headline: **{agg['overall']}**",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Mention rate          | **{agg['mention_rate']:.1f}%** of rows mentioned the brand |",
        f"| Avg share-of-voice    | **{agg['sov_avg']:.1f}%** across all brands surfaced |",
        f"| Avg strength score    | **{agg['strength_avg']:.1f} / 10**  (rubric: Leader 9, Challenger 7, Alternative 5, Niche 3) |",
        f"| Avg sentiment         | **{agg['sentiment_avg']:+.1f}**  (rubric range: -50..+50) |",
    ]

    # Competitive landscape — top 5 dominant brands
    bc = agg.get("brand_counter") or {}
    if bc:
        sorted_b = sorted(bc.items(), key=lambda kv: -kv[1])[:5]
        total = sum(bc.values()) or 1
        lines += ["", "## Who actually shows up"]
        lines += ["", "| Brand | Mentions | % |", "|---|---|---|"]
        for b, n in sorted_b:
            tag = " **(YOU)**" if b.lower() == target.lower() else ""
            lines.append(f"| {b}{tag} | {n} | {100 * n / total:.1f}% |")
        # If target is NOT in top 5, surface it explicitly
        if not any(b.lower() == target.lower() for b, _ in sorted_b):
            target_n = bc.get(target, 0)
            if target_n:
                lines.append(f"| **{target} (your brand, ranked outside top 5)** "
                             f"| {target_n} | {100 * target_n / total:.1f}% |")
            else:
                lines.append(f"| **{target} (your brand)** | 0 | not mentioned in any row |")

    # Top actions
    if agg.get("top_actions"):
        lines += ["", "## Top actions (deduplicated, by priority)"]
        for i, (a, n) in enumerate(agg["top_actions"][:5], 1):
            lines.append(f"{i}. {a}")
            lines.append(f"   _Helps {n} row(s)._")

    # Risks
    if agg.get("risks"):
        lines += ["", "## If we do nothing"]
        for r in agg["risks"]:
            lines.append(f"- {r}")

    # Coverage / methodology summary
    if df is not None and not df.empty:
        cats = Counter(df["query_category"].dropna()) if "query_category" in df.columns else {}
        pri  = Counter(df["optimization_priority"].dropna()) if "optimization_priority" in df.columns else {}
        lines += ["", "## What was queried"]
        if cats:
            lines.append("- **Query categories:** " + ", ".join(f"{k}={v}" for k, v in sorted(cats.items())))
        if pri:
            lines.append("- **Priority distribution:** " + ", ".join(f"{k}={v}" for k, v in pri.most_common()))

    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--brand-profile", required=True)
    ap.add_argument("--gaps", default=None, help="optional gap_rows.jsonl for richer details")
    ap.add_argument("--out",  required=True)
    ap.add_argument("--exec-md", default=None, help="defaults to <out_dir>/aeo_executive_summary.md")
    args = ap.parse_args()

    df = pd.read_excel(args.xlsx, sheet_name=0)
    with open(args.brand_profile, encoding="utf-8") as f:
        brand_profile = json.load(f)

    gap_rows_by_id = {}
    if args.gaps:
        with open(args.gaps, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    obj = json.loads(line)
                    if obj.get("row_id"):
                        gap_rows_by_id[obj["row_id"]] = obj

    agg = aggregate(df, brand_profile, gap_rows_by_id)

    with tempfile.TemporaryDirectory() as tmp:
        charts = {}
        chart_share_of_voice_donut(agg["brand_counter"], agg["target"], f"{tmp}/sov_donut.png")
        charts["sov_donut"] = f"{tmp}/sov_donut.png"
        chart_per_engine_mention(agg["per_engine_mention"], agg["target"], f"{tmp}/engine_bar.png")
        charts["engine_bar"] = f"{tmp}/engine_bar.png" if agg["per_engine_mention"] else None
        chart_cat_engine_heatmap(agg["cat_engine_sov"], agg["target"], f"{tmp}/category_heatmap.png")
        charts["category_heatmap"] = f"{tmp}/category_heatmap.png" if agg["cat_engine_sov"] else None
        chart_strength_distribution(df, agg["target"], f"{tmp}/strength_hist.png")
        charts["strength_hist"] = f"{tmp}/strength_hist.png"
        chart_sentiment_box(df, agg["target"], f"{tmp}/sentiment_box.png")
        charts["sentiment_box"] = f"{tmp}/sentiment_box.png" if "engine" in df.columns else None

        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        build_pdf(args.out, df, brand_profile, agg, charts)

    exec_md = args.exec_md or str(Path(args.out).parent / "aeo_executive_summary.md")
    write_executive_md(exec_md, agg, brand_profile, df=df)

    print(f"Wrote {args.out} and {exec_md}", file=sys.stderr)


if __name__ == "__main__":
    main()
