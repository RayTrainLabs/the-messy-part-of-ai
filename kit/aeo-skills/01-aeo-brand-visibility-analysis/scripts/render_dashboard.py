#!/usr/bin/env python3
"""
render_dashboard.py  --  Generate a self-contained LLM Brand Presence Dashboard HTML.

Usage (from the skill root  AEO skills/01-aeo-brand-visibility-analysis/):

    python scripts/render_dashboard.py
    python scripts/render_dashboard.py \\
        --scored   output/scored_rows.jsonl \\
        --brand-profile output/brand_profile.json \\
        --queries  output/queries.json \\
        --runs-dir runs/ \\
        --strategy-events output/strategy_events.json \\
        --out      output/brand_presence_dashboard.html

When scored_rows.jsonl is absent the script generates deterministic demo data
so the dashboard can be previewed immediately.

Python 3.9+, stdlib only.
"""

import argparse
import json
import logging
import math
import os
import random
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path


logger = logging.getLogger("render_dashboard")


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts":     datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level":  record.levelname,
            "logger": record.name,
            "msg":    record.getMessage(),
        }
        step = getattr(record, "step", None)
        if step:
            payload["step"] = step
        return json.dumps(payload, ensure_ascii=False)


def _configure_logging(verbose: bool, log_format: str = "text") -> None:
    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(stream=sys.stderr)
    if log_format == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(level)

# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------
TARGET_COLOR = "#bc4749"
COMP_COLORS = [
    "#d4a373", "#2d6a4f", "#6a994e", "#81b29a",
    "#9c6644", "#b08968", "#adc178", "#f2cc8f", "#386641",
]

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Render AEO brand presence dashboard HTML.")
    skill_root = Path(__file__).resolve().parent.parent
    p.add_argument("--scored",
                   default=str(skill_root / "output" / "scored_rows.jsonl"),
                   help="Path to scored_rows.jsonl (Phase 4 output)")
    p.add_argument("--brand-profile",
                   default=str(skill_root / "output" / "brand_profile.json"),
                   help="Path to brand_profile.json")
    p.add_argument("--queries",
                   default=str(skill_root / "output" / "queries.json"),
                   help="Path to queries.json")
    p.add_argument("--runs-dir",
                   default=str(skill_root / "runs"),
                   help="Directory containing YYYY-MM-DD/scored_rows.jsonl subdirs")
    p.add_argument("--strategy-events",
                   default=str(skill_root / "output" / "strategy_events.json"),
                   help="Optional JSON file with strategy annotation events")
    p.add_argument("--out",
                   default=str(skill_root / "output" / "brand_presence_dashboard.html"),
                   help="Output HTML path")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Enable debug-level logging.")
    p.add_argument("--log-format", choices=["text", "json"], default="text",
                   help="Log output format. 'text' (default) or 'json' for structured single-line JSON.")
    return p.parse_args()

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def strip_brand_name(raw):
    """
    'Naturtreu (naturtreu.de) -- German DTC...' -> 'Naturtreu'
    'H&M Sport / Primark Active — fast-fashion...' -> 'H&M Sport / Primark Active'
    """
    name = raw.split(" (")[0].strip()
    name = name.split(" —")[0].strip()   # em dash separator
    name = name.split(" -- ")[0].strip()       # double-hyphen separator
    return name


def build_brand_map(brand_profile):
    """
    Returns:
        target_name  str
        all_brands   list[str]   target first, then competitors
        brand_colors dict[str, str]
        is_target_fn callable(str) -> bool
    """
    target_name = brand_profile["brand_name"]
    aliases = set(a.lower() for a in brand_profile.get("brand_aliases", []))
    aliases.add(target_name.lower())

    direct = [strip_brand_name(c) for c in brand_profile.get("competitors", {}).get("direct", [])]
    indirect = [strip_brand_name(c) for c in brand_profile.get("competitors", {}).get("indirect", [])]
    competitors = direct + indirect

    # deduplicate while preserving order
    seen = set()
    competitors_dedup = []
    for c in competitors:
        if c.lower() not in seen:
            seen.add(c.lower())
            competitors_dedup.append(c)

    all_brands = [target_name] + competitors_dedup

    colors = {target_name: TARGET_COLOR}
    for i, comp in enumerate(competitors_dedup):
        colors[comp] = COMP_COLORS[i % len(COMP_COLORS)]

    def is_target(name_str):
        return name_str.lower() in aliases

    return target_name, all_brands, colors, is_target


def canonical_brand_name(raw, all_brands, is_target):
    """Map a raw brand string to the configured canonical dashboard brand."""
    raw_l = str(raw).lower().strip()
    if not raw_l:
        return None
    if is_target(raw_l):
        return all_brands[0]
    for brand in all_brands[1:]:
        brand_l = brand.lower()
        if raw_l == brand_l or raw_l in brand_l or brand_l in raw_l:
            return brand
    return None


def normalize_brands_in_row(row, all_brands, is_target):
    """
    Map raw brand strings in brands_mentioned_list to canonical brand names.
    Returns a set of canonical brand names mentioned in this row.
    """
    mentioned_raw = row.get("brands_mentioned_list", [])
    mentioned = set()
    for raw in mentioned_raw:
        brand = canonical_brand_name(raw, all_brands, is_target)
        if brand:
            mentioned.add(brand)
    return mentioned


def normalize_brand_mention_counts(row, all_brands, is_target, mentioned):
    """Return canonical per-brand total mention counts for SOV aggregation."""
    counts = defaultdict(float)
    raw_counts = row.get("_brand_mention_counts") or {}
    if isinstance(raw_counts, dict):
        for raw_brand, metrics in raw_counts.items():
            brand = canonical_brand_name(raw_brand, all_brands, is_target)
            if not brand:
                continue
            if isinstance(metrics, dict):
                total_mentions = metrics.get("total_mentions", 0)
            else:
                total_mentions = metrics
            try:
                total_mentions = float(total_mentions or 0)
            except (TypeError, ValueError):
                total_mentions = 0.0
            if total_mentions > 0:
                counts[brand] += total_mentions

    if counts:
        return dict(counts)

    # Demo/legacy rows may only have a deduplicated mentioned set. Treat each
    # listed brand as one mention instead of reusing the target brand's row SOV.
    return {brand: 1.0 for brand in mentioned if brand in all_brands}


def load_scored_rows(path, all_brands, is_target):
    """Load and normalize a scored_rows.jsonl file."""
    raw_rows = load_jsonl(path)
    normalized = []
    for row in raw_rows:
        mentioned = normalize_brands_in_row(row, all_brands, is_target)
        mention_counts = normalize_brand_mention_counts(row, all_brands, is_target, mentioned)
        normalized.append({
            "query_id": row.get("query_id", ""),
            "engine": row.get("engine", ""),
            "mentioned": mentioned,
            "mention_counts": mention_counts,
            "sov": row.get("share_of_voice_percentage", 0) or 0,
            "sentiment": row.get("sentiment_direction_score", 0) or 0,
            "discovery_role": row.get("discovery_role", "absent"),
        })
    return normalized


# ---------------------------------------------------------------------------
# Demo time-series data: 25 biweekly dates telling the strategy story
# Values mirror the reference dashboard narrative (baseline -> interventions -> breakout)
# ---------------------------------------------------------------------------

DEMO_DATES = [
    "Jul 7", "Jul 21", "Aug 4", "Aug 18", "Sep 1",
    "Sep 15", "Sep 29", "Oct 13", "Oct 27", "Nov 10",
    "Nov 24", "Dec 8", "Dec 22", "Jan 5'26", "Jan 19'26",
    "Feb 2'26", "Feb 16'26", "Mar 2'26", "Mar 16'26", "Mar 30'26",
    "Apr 13'26", "Apr 27'26", "May 6'26",
]

# Presence % per date index for up to 10 brands (index 0 = main_brand)
# Story: main_brand is a late mover, invisible for months, then executes
# a three-phase AEO program and overtakes the incumbent by April
DEMO_PRESENCE_CURVES = [
    # main_brand: near-zero baseline, sharp climb from Nov onward
    [1.2, 1.4, 1.1, 1.5, 1.3, 1.6, 1.4, 1.2, 1.5,
     4.8, 7.3, 11.6, 14.2, 21.7, 24.0,
     26.3, 27.8, 29.4, 31.1, 32.6, 34.0, 33.5, 34.8],
    # comp_brand_1: entrenched leader, starts high, erodes slowly
    [61.4, 60.8, 61.2, 60.5, 59.9, 60.3, 59.7, 58.6, 57.4,
     56.2, 54.8, 52.1, 49.7, 46.3, 43.9,
     41.2, 38.6, 36.1, 34.0, 32.5, 30.8, 30.2, 29.7],
    # comp_brand_2: rising challenger, also investing in AEO
    [14.6, 15.1, 15.8, 16.4, 17.0, 17.8, 18.5, 19.2, 20.0,
     21.1, 22.4, 23.8, 25.4, 27.0, 28.6,
     30.2, 31.9, 33.5, 35.2, 36.8, 37.4, 36.9, 37.5],
    # comp_brand_3: volatile, spikes around product launches
    [11.3, 10.9, 22.7, 11.4, 11.0, 10.8, 23.1, 11.2, 10.7,
     11.5, 10.9, 22.4, 11.3, 11.0, 10.6,
     10.9, 22.8, 11.1, 10.8, 10.5, 11.2, 10.7, 10.9],
    # comp_brand_4: steady mid-tier, very slight decline
    [17.2, 17.0, 16.8, 16.6, 16.4, 16.2, 16.0, 15.8, 15.5,
     15.3, 15.0, 14.7, 14.4, 14.1, 13.8,
     13.5, 13.2, 12.8, 12.5, 12.2, 11.9, 11.6, 11.3],
    # comp_brand_5: declining, losing ground to AEO entrants
    [13.8, 13.4, 13.0, 12.5, 12.1, 11.6, 11.1, 10.6, 10.1,
     9.6, 9.0, 8.5, 7.9, 7.4, 6.8,
     6.3, 5.8, 5.3, 4.9, 4.5, 4.1, 3.8, 3.6],
    # comp_brand_6: small player, flat then fades
    [8.9, 8.7, 8.5, 8.3, 8.1, 7.9, 7.7, 7.4, 7.2,
     6.9, 6.7, 6.4, 6.1, 5.9, 5.6,
     5.3, 5.1, 4.8, 4.5, 4.3, 4.0, 3.8, 3.6],
    # comp_brand_7: niche, barely registers
    [5.4, 5.2, 5.5, 5.1, 5.3, 5.0, 5.2, 4.9, 5.1,
     4.8, 4.6, 4.4, 4.2, 4.0, 3.8,
     3.6, 3.4, 3.2, 3.0, 2.8, 2.7, 2.5, 2.4],
    # comp_brand_8: near-invisible, stable low
    [3.1, 3.0, 3.2, 2.9, 3.1, 2.8, 3.0, 2.7, 2.9,
     2.6, 2.5, 2.3, 2.2, 2.1, 2.0,
     1.9, 1.8, 1.7, 1.6, 1.5, 1.5, 1.4, 1.4],
    # comp_brand_9: trace presence only
    [1.8, 1.7, 1.9, 1.6, 1.8, 1.5, 1.7, 1.4, 1.6,
     1.4, 1.3, 1.2, 1.1, 1.0, 1.0,
     0.9, 0.9, 0.8, 0.8, 0.7, 0.7, 0.7, 0.6],
]

DEMO_STRATEGY_EVENTS = [
    {"date": "Oct 27",     "label": "llms.txt live",        "color": "#6a994e", "row": 0},
    {"date": "Nov 10",     "label": "FAQ + schema deploy",  "color": "#386641", "row": 1},
    {"date": "Nov 24",     "label": "Editorial push x4",    "color": "#bc4749", "row": 2},
    {"date": "Dec 8",      "label": "AI cited: 3 outlets",  "color": "#9c6644", "row": 3},
    {"date": "Jan 5'26",   "label": "BREAKOUT 21.7%",       "color": "#2d6a4f", "row": 0},
    {"date": "Feb 16'26",  "label": "Perplexity #2 slot",   "color": "#6a994e", "row": 1},
    {"date": "Apr 13'26",  "label": "Category leader",      "color": "#2d6a4f", "row": 2},
]


def generate_demo_runs(all_brands, queries_data):
    """
    Build synthetic historical runs for demo mode.
    Returns list of (date_label, rows) matching the DEMO_DATES narrative.
    Rows use canonical mentioned sets so compute_presence() produces the target values.
    """
    queries = queries_data.get("queries", [])
    engines = ["llm_openai", "llm_gemini"]
    n_rows = len(queries) * len(engines)
    rng = random.Random(99)
    runs = []
    for date_idx, date_label in enumerate(DEMO_DATES):
        rows = []
        # Pre-compute how many rows each brand should appear in
        brand_row_counts = {}
        for b_idx, brand in enumerate(all_brands):
            curve = DEMO_PRESENCE_CURVES[b_idx] if b_idx < len(DEMO_PRESENCE_CURVES) else [3.0] * 25
            target_pct = curve[date_idx]
            brand_row_counts[brand] = max(0, round(target_pct / 100 * n_rows))
        # Assign brands to rows deterministically
        row_brand_sets = [set() for _ in range(n_rows)]
        for brand, count in brand_row_counts.items():
            indices = list(range(n_rows))
            rng.shuffle(indices)
            for i in indices[:count]:
                row_brand_sets[i].add(brand)
        for row_idx, (q, eng) in enumerate([(q, e) for q in queries for e in engines]):
            mentioned = list(row_brand_sets[row_idx])
            is_tgt = all_brands[0] in mentioned
            rows.append({
                "query_id": q["id"],
                "engine": eng,
                "mentioned": set(mentioned),
                "mention_counts": {brand: 1.0 for brand in mentioned},
                "sov": rng.uniform(15, 45) if is_tgt else rng.uniform(0, 5),
                "sentiment": rng.randint(5, 25) if is_tgt else rng.randint(-5, 10),
                "positional_authority": rng.randint(55, 80) if is_tgt else rng.randint(20, 60),
                "market_position": "challenger" if is_tgt else "leader",
                "discovery_role": rng.choice(["recommended", "listed"]) if is_tgt else rng.choice(["listed", "cited", "absent"]),
            })
        runs.append((date_label, rows))
    return runs


def generate_demo_rows(brand_profile, queries_data, all_brands, is_target):
    """
    Generate reproducible demo rows when scored_rows.jsonl is absent.
    Uses random.seed(42) for determinism.
    """
    rng = random.Random(42)
    target_name = all_brands[0]
    competitors = all_brands[1:]
    engines = ["llm_openai", "llm_gemini"]
    queries = queries_data.get("queries", [])
    roles = ["recommended", "listed", "cited", "absent"]
    rows = []
    for q in queries:
        for engine in engines:
            # Decide mentions
            mentioned = set()
            # Target brand: 20-40% chance
            if rng.random() < rng.uniform(0.20, 0.40):
                mentioned.add(target_name)
            # Competitors
            for comp in competitors[:6]:
                if rng.random() < rng.uniform(0.10, 0.55):
                    mentioned.add(comp)
            sov = rng.uniform(10, 50) if target_name in mentioned else 0
            sentiment = rng.randint(-10, 30) if target_name in mentioned else 0
            discovery = rng.choice(roles[:3]) if target_name in mentioned else "absent"
            rows.append({
                "query_id": q["id"],
                "engine": engine,
                "mentioned": mentioned,
                "mention_counts": {brand: 1.0 for brand in mentioned},
                "sov": sov,
                "sentiment": float(sentiment),
                "discovery_role": discovery,
            })
    return rows

# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------

def compute_presence(rows, all_brands, filter_fn=None):
    """
    Returns dict[brand_name, float] percent presence.
    filter_fn(row) -> bool  (optional filter on rows)
    """
    if filter_fn:
        rows = [r for r in rows if filter_fn(r)]
    total = len(rows)
    if total == 0:
        return {b: 0.0 for b in all_brands}
    counts = {b: 0 for b in all_brands}
    for row in rows:
        for b in row["mentioned"]:
            if b in counts:
                counts[b] += 1
    return {b: counts[b] / total * 100 for b in all_brands}


def compute_sov(rows, all_brands):
    """Share of voice per brand as % of total brand mentions."""
    mention_sum = {b: 0.0 for b in all_brands}
    total_mentions = 0.0
    for row in rows:
        mention_counts = row.get("mention_counts") or {
            b: 1.0 for b in row.get("mentioned", set()) if b in mention_sum
        }
        for brand, count in mention_counts.items():
            if brand not in mention_sum:
                continue
            try:
                count = float(count or 0)
            except (TypeError, ValueError):
                continue
            if count <= 0:
                continue
            mention_sum[brand] += count
            total_mentions += count
    if total_mentions == 0:
        return {b: 0.0 for b in all_brands}
    return {b: mention_sum[b] / total_mentions * 100 for b in all_brands}


def compute_discovery(rows, target_name):
    """Count of rows for target brand by discovery role."""
    counts = defaultdict(int)
    for row in rows:
        if target_name in row["mentioned"]:
            role = row.get("discovery_role", "absent")
            counts[role] += 1
    return dict(counts)


def get_engines(rows):
    seen = []
    for r in rows:
        if r["engine"] not in seen:
            seen.append(r["engine"])
    return seen


def engine_display_name(engine_key):
    """'llm_openai' -> 'OpenAI'"""
    name = engine_key.replace("llm_", "").replace("serp_", "").replace("_", " ")
    return name.title()


def engine_row_count(rows, engine):
    return sum(1 for r in rows if r["engine"] == engine)

# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def heatmap_style(pct, is_target):
    if is_target:
        if pct >= 20:
            return "background:#bc4749;color:white;font-weight:700;"
        elif pct > 0:
            return "background:#f2cc8f;color:var(--c2);font-weight:700;"
        else:
            return "background:#e8f5e9;color:#2d6a4f;font-weight:700;"
    if pct >= 50:
        return "background:#2d6a4f;color:white;"
    if pct >= 40:
        return "background:#386641;color:white;"
    if pct >= 25:
        return "background:#6a994e;color:white;"
    if pct >= 15:
        return "background:#adc178;"
    if pct >= 5:
        return "background:#d4a373;"
    return "background:#e8f5e9;"


def html_escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def render_filter_bar(items):
    """items = list of (label, value)"""
    parts = []
    for label, value in items:
        parts.append(f"""      <div class="filter-item">
        <span class="filter-label">{html_escape(label)}</span>
        <span class="filter-value">{html_escape(str(value))}</span>
      </div>""")
    return '<div class="filter-bar">\n' + "\n".join(parts) + "\n    </div>"


def render_ranking_table(title, presence, all_brands, target_name, max_rows=10):
    """Render a .panel containing a ranking-table."""
    ranked = sorted(all_brands, key=lambda b: presence.get(b, 0), reverse=True)
    target_rank = None
    for i, b in enumerate(ranked):
        if b == target_name:
            target_rank = i + 1
            break

    rows_html = []
    shown = 0
    target_shown = False
    for rank, brand in enumerate(ranked, 1):
        if shown >= max_rows:
            break
        cls = ' class="highlight"' if brand == target_name else ""
        pct = presence.get(brand, 0)
        rows_html.append(
            f'<tr{cls}><td>{rank}</td><td>{html_escape(brand)}</td><td>{pct:.1f}%</td></tr>'
        )
        if brand == target_name:
            target_shown = True
        shown += 1

    if not target_shown and target_rank is not None:
        pct = presence.get(target_name, 0)
        note = f" (rank {target_rank})"
        rows_html.append(
            f'<tr class="highlight"><td>{target_rank}{note}</td>'
            f'<td>{html_escape(target_name)}</td><td>{pct:.1f}%</td></tr>'
        )

    rows_str = "\n            ".join(rows_html)
    return f"""<div class="panel">
        <div class="panel-title">{html_escape(title)}</div>
        <table class="ranking-table">
          <thead><tr><th>Rank</th><th>Brand</th><th>%</th></tr></thead>
          <tbody>
            {rows_str}
          </tbody>
        </table>
      </div>"""


def render_legend(series_list):
    items = []
    for s in series_list:
        name = html_escape(s["name"])
        color = s["color"]
        bold = " font-weight:700;" if s.get("highlight") else ""
        items.append(
            f'<div class="legend-item"><span class="legend-swatch"'
            f' style="background:{color};height:{"4px" if s.get("highlight") else "2px"};{bold}"></span>'
            f'<span style="color:{color};{bold}">{name}</span></div>'
        )
    return '<div class="legend">' + "".join(items) + "</div>"


def render_heatmap(
    title,
    runs,          # list of (date_label, rows) sorted by date
    all_brands,
    target_name,
    strategy_events=None,
    filter_fn=None,
):
    """
    runs: list of (date_label str, iso_date str, rows list); legacy 2-tuples accepted.
    Returns HTML string for a full heatmap panel.
    """
    # Normalize legacy 2-tuples to triples with empty iso_date
    runs = [(t[0], t[1], t[2]) if len(t) == 3 else (t[0], "", t[1]) for t in runs]
    if filter_fn:
        runs = [(dl, iso, [r for r in rows if filter_fn(r)]) for dl, iso, rows in runs]

    date_labels = [dl for dl, _, _ in runs]
    date_labels_iso = [iso for _, iso, _ in runs]
    iso_to_idx = {iso: i for i, iso in enumerate(date_labels_iso) if iso}
    n_dates = len(date_labels)

    # Build callout rows — one HTML <tr> per content-type lane (per `row` field on events).
    # Each event sits in its own date column, on its type's lane → no overlap.
    callout_row_html = ""
    if strategy_events:
        # Group: lane_index -> { date_label -> [event,...] }
        # Prefer iso_date matching when present; fall back to legacy date-label match.
        def _ev_date_key(ev):
            ev_iso = ev.get("iso_date")
            if ev_iso and ev_iso in iso_to_idx:
                return date_labels[iso_to_idx[ev_iso]]
            return ev.get("date", "")

        lanes = {}
        for ev in strategy_events:
            lane = ev.get("row", 0)
            date_key = _ev_date_key(ev)
            lanes.setdefault(lane, {}).setdefault(date_key, []).append(ev)

        # Lane label + color from first event in each lane
        lane_labels = {}
        lane_colors = {}
        for lane, by_date in lanes.items():
            for evs in by_date.values():
                t = evs[0].get("type", "")
                if t:
                    lane_labels[lane] = t
                    lane_colors[lane] = evs[0].get("color", "#56635e")
                    break

        # Pair → impl_idx + attr_idx (snapped to date_labels)
        # ISO-first lookup with legacy date-label fallback.
        date_idx_map = {dl: i for i, dl in enumerate(date_labels)}
        pair_info = {}
        for ev in strategy_events:
            pid = ev.get("pair_id")
            if not pid:
                continue
            ev_iso = ev.get("iso_date")
            if ev_iso and ev_iso in iso_to_idx:
                di = iso_to_idx[ev_iso]
            else:
                di = date_idx_map.get(ev.get("date", ""))
            if di is None:
                continue
            p = pair_info.setdefault(pid, {"lane": ev.get("row", 0), "color": ev.get("color", "#999"), "type": ev.get("type", "")})
            p[ev.get("kind", "")] = di

        # Per-lane: complete pairs as (impl_idx, attr_idx, color, type, pair_num)
        # Number them per lane so "Blog 1", "Blog 2" etc. label inside the bar
        pairs_by_lane = {}
        for pid, p in pair_info.items():
            if "impl" not in p or "attr" not in p:
                continue
            lane = p["lane"]
            pairs_by_lane.setdefault(lane, []).append({
                "impl_idx": p["impl"], "attr_idx": p["attr"],
                "color": p["color"], "type": p["type"],
            })
        for lane, pairs in pairs_by_lane.items():
            pairs.sort(key=lambda x: (min(x["impl_idx"], x["attr_idx"]), max(x["impl_idx"], x["attr_idx"])))
            for i, p in enumerate(pairs, start=1):
                p["num"] = i

        # Greedy interval scheduling per lane: assign each pair a sublane index
        # such that no two pairs in the same sublane overlap. Sublane 0 is the
        # primary row (carries the lane label). Same-day same-type events get
        # different sublanes instead of overlapping.
        sublane_count_by_lane = {}
        for lane, pairs in pairs_by_lane.items():
            sublane_last_end = []  # list of last hi per sublane
            for p in pairs:
                lo = min(p["impl_idx"], p["attr_idx"])
                hi = max(p["impl_idx"], p["attr_idx"])
                placed = False
                for si, last_hi in enumerate(sublane_last_end):
                    if last_hi < lo:
                        p["sublane"] = si
                        sublane_last_end[si] = hi
                        placed = True
                        break
                if not placed:
                    p["sublane"] = len(sublane_last_end)
                    sublane_last_end.append(hi)
            sublane_count_by_lane[lane] = max(1, len(sublane_last_end))

        lane_rows = []
        for lane in sorted(lanes.keys()):
            lbl = html_escape(lane_labels.get(lane, ""))
            color = lane_colors.get(lane, "#56635e")
            lane_pairs = pairs_by_lane.get(lane, [])
            n_sub = sublane_count_by_lane.get(lane, 1)

            # Group pairs by their sublane
            pairs_by_sublane = {}
            for p in lane_pairs:
                pairs_by_sublane.setdefault(p.get("sublane", 0), []).append(p)

            for sub in range(n_sub):
                # Lane label cell: only on the first sublane row
                if sub == 0:
                    cells = [f'<th class="brand-col callout-lane-label" style="color:{color};">{lbl}</th>']
                else:
                    cells = ['<th class="brand-col callout-lane-label"></th>']

                sub_pairs = pairs_by_sublane.get(sub, [])
                pair_start = {}
                covered = set()
                for p in sub_pairs:
                    lo, hi = sorted([p["impl_idx"], p["attr_idx"]])
                    span = hi - lo + 1
                    if lo in covered:
                        continue
                    pair_start[lo] = {"span": span, "color": p["color"], "type": p["type"], "num": p["num"]}
                    for x in range(lo, hi + 1):
                        covered.add(x)

                di = 0
                while di < len(date_labels):
                    if di in pair_start:
                        info = pair_start[di]
                        span = info["span"]
                        bar_lbl = f'<span class="bar-edge">▸</span><span class="bar-label">{html_escape(info["type"])} {info["num"]}</span><span class="bar-edge">◂</span>'
                        cells.append(
                            f'<th class="pair-bar" colspan="{span}" style="background:{info["color"]};">{bar_lbl}</th>'
                        )
                        di += span
                        continue
                    if di in covered:
                        di += 1
                        continue
                    # Breakouts render only on the first sublane row to avoid duplication
                    if sub == 0:
                        evs = lanes[lane].get(date_labels[di]) or []
                        show_evs = [e for e in evs if not e.get("pair_id") and e.get("kind") == "breakout"]
                        if show_evs:
                            bits = []
                            for ev in show_evs:
                                bg = ev.get("color", "#bc4749")
                                elbl = html_escape(ev.get("label", ""))
                                bits.append(f'<span class="callout-pin" style="background:{bg};">{elbl}</span>')
                            cells.append(f'<th>{"".join(bits)}</th>')
                        else:
                            cells.append('<th></th>')
                    else:
                        cells.append('<th></th>')
                    di += 1
                lane_rows.append('<tr class="callout-row">' + "".join(cells) + "</tr>")
        callout_row_html = "\n          ".join(lane_rows)

    # Header row
    header_ths = ['<th class="brand-col">Brand</th>']
    for dl in date_labels:
        header_ths.append(f"<th>{html_escape(dl)}</th>")
    header_row = "<tr>" + "".join(header_ths) + "</tr>"

    # Data rows
    body_rows = []
    for brand in all_brands:
        is_t = brand == target_name
        brand_cell_class = 'brand-cell main' if is_t else 'brand-cell'
        cells = [f'<td class="{brand_cell_class}">{html_escape(brand)}</td>']
        for _, _, run_rows in runs:
            total = len(run_rows)
            if total == 0:
                pct = 0.0
            else:
                count = sum(1 for r in run_rows if brand in r["mentioned"])
                pct = count / total * 100
            style = heatmap_style(pct, is_t)
            cells.append(f'<td style="{style}">{pct:.1f}%</td>')
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    body_html = "\n          ".join(body_rows)
    thead_html = callout_row_html + "\n          " + header_row

    return f"""<div class="panel">
      <div class="panel-title">{html_escape(title)}</div>
      <div class="heatmap-wrap">
      <table class="heatmap">
        <thead>
          {thead_html}
        </thead>
        <tbody>
          {body_html}
        </tbody>
      </table>
      </div>
    </div>"""


def render_funnel_bars(category_counts, queries_data):
    """
    Horizontal funnel bars showing query count per category.
    category_counts: dict[category_name, int]
    """
    if not category_counts:
        return "<p>No category data.</p>"
    max_count = max(category_counts.values()) or 1
    colors = ["#2d6a4f", "#6a994e", "#adc178", "#d4a373", "#9c6644", "#bc4749", "#81b29a", "#b08968", "#386641"]
    bars = []
    for i, (cat_name, count) in enumerate(sorted(category_counts.items(), key=lambda x: -x[1])):
        pct = count / max_count * 100
        color = colors[i % len(colors)]
        bars.append(
            f'<div class="funnel-row">'
            f'<div class="funnel-label">{html_escape(cat_name)}</div>'
            f'<div class="funnel-bar">'
            f'<div class="funnel-fill" style="width:{pct:.1f}%;background:{color};">{count}</div>'
            f'</div>'
            f'</div>'
        )
    return "\n".join(bars)


def render_engine_panel(engines, rows):
    """Engines panel with row counts and inline bars."""
    if not engines:
        return "<p>No engine data.</p>"
    counts = {e: engine_row_count(rows, e) for e in engines}
    max_count = max(counts.values()) or 1
    items = []
    for engine in engines:
        count = counts[engine]
        items.append(
            f'<div class="provider-row">'
            f'<span class="provider-name">{html_escape(engine_display_name(engine))}</span>'
            f'<span class="provider-count">{count}</span>'
            f'</div>'
        )
    # SVG bars
    bar_h = 22
    svg_h = max(70, len(engines) * (bar_h + 6))
    svg_bars = []
    for i, engine in enumerate(engines):
        count = counts[engine]
        w = max(5, int(180 * count / max_count))
        y = 10 + i * (bar_h + 4)
        color = ["#2d6a4f", "#6a994e", "#adc178", "#d4a373"][i % 4]
        label = f"{engine_display_name(engine)} {count}"
        svg_bars.append(
            f'<rect x="10" y="{y}" width="{w}" height="{bar_h}" fill="{color}" />'
            f'<text x="16" y="{y + bar_h - 6}" fill="white" font-size="10" font-weight="700">'
            f'{html_escape(label)}</text>'
        )
    svg_content = "\n          ".join(svg_bars)
    return (
        "\n".join(items)
        + f'\n<svg viewBox="0 0 200 {svg_h}" style="width:100%;height:{svg_h}px;margin-top:12px;">'
        + "\n          " + svg_content
        + "\n          </svg>"
    )


def render_kw_bars(queries_in_cat, presence_by_query, target_name):
    """Keyword-level presence bars (sorted ascending by presence)."""
    items = []
    data = []
    for q in queries_in_cat:
        pct = presence_by_query.get(q["id"], {}).get(target_name, 0)
        data.append((q["query"][:60], pct))
    data.sort(key=lambda x: x[1])
    colors = ["#81b29a", "#6a994e", "#2d6a4f", "#386641"]
    for label, pct in data:
        w = min(100, pct)
        color_idx = 0 if pct < 25 else (1 if pct < 40 else (2 if pct < 60 else 3))
        color = colors[color_idx]
        items.append(
            f'<div class="kw-row">'
            f'<div class="kw-label" title="{html_escape(label)}">'
            f'{html_escape(label[:50])}{"..." if len(label) > 50 else ""}</div>'
            f'<div class="kw-bar">'
            f'<div class="kw-fill" style="width:{w:.1f}%;background:{color};">'
            f'{pct:.1f}%</div></div></div>'
        )
    return '<div class="keyword-bars">' + "\n".join(items) + "</div>"


# ---------------------------------------------------------------------------
# Time-series helpers
# ---------------------------------------------------------------------------

def load_historical_runs(runs_dir, all_brands, is_target):
    """
    Scans runs_dir for YYYY-MM-DD subdirs containing scored_rows.jsonl.
    Returns list of (date_label str, iso_date str, rows list) sorted chronologically.
    """
    runs_path = Path(runs_dir)
    result = []
    if not runs_path.exists():
        return result
    for subdir in sorted(runs_path.iterdir()):
        if not subdir.is_dir():
            continue
        scored = subdir / "scored_rows.jsonl"
        if not scored.exists():
            continue
        try:
            dt = datetime.strptime(subdir.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        rows = load_scored_rows(str(scored), all_brands, is_target)
        label = dt.strftime("%b %-d'%y") if sys.platform != "win32" else dt.strftime("%b %d'%y").lstrip("0")
        result.append((label, dt.isoformat(), rows))
    return result


def build_series_from_runs(runs, all_brands, target_name, colors, filter_fn=None):
    """
    runs: list of (date_label, iso_date, rows); legacy 2-tuples accepted.
    Returns (dates_list, dates_iso_list, series_list) for renderChart.
    """
    runs = [(t[0], t[1], t[2]) if len(t) == 3 else (t[0], "", t[1]) for t in runs]
    dates = [dl for dl, _, _ in runs]
    dates_iso = [iso for _, iso, _ in runs]
    brand_values = {b: [] for b in all_brands}
    for _, _, run_rows in runs:
        if filter_fn:
            run_rows = [r for r in run_rows if filter_fn(r)]
        presence = compute_presence(run_rows, all_brands)
        for b in all_brands:
            brand_values[b].append(round(presence.get(b, 0), 1))

    series = []
    # Target brand first
    series.append({
        "name": target_name,
        "color": TARGET_COLOR,
        "highlight": True,
        "values": brand_values[target_name],
    })
    for b in all_brands[1:]:
        series.append({
            "name": b,
            "color": colors.get(b, "#aaa"),
            "values": brand_values[b],
        })
    return dates, dates_iso, series


# ---------------------------------------------------------------------------
# Main HTML builder
# ---------------------------------------------------------------------------

CSS = """\
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

  :root {
    --bg:          #f4f2ee;
    --panel:       #ffffff;
    --ink:         #0f1f1a;
    --ink-mid:     #374740;
    --ink-soft:    #6b7a74;
    --line:        #e0dbd0;
    --line-strong: #c8c1b4;

    /* Primary brand */
    --c1:  #1a6b4a;
    --c1d: #124d35;
    --c1l: #e6f4ed;

    /* Signal / alert */
    --c2:  #be123c;
    --c2l: #fff1f3;

    /* Warm amber */
    --c3:  #b45309;
    --c3l: #fef3e2;

    /* Sky */
    --c4:  #0369a1;
    --c4l: #e0f2fe;

    /* Violet */
    --c5:  #6d28d9;
    --c5l: #f5f3ff;

    /* Sage */
    --c6:  #4d7c0f;
    --c6l: #f7fee7;

    /* Warm tan */
    --c7:  #92400e;
    --c7l: #fff7ed;

    /* Teal */
    --c8:  #0f766e;
    --c8l: #f0fdfa;

    /* Honey highlight */
    --c9:  #fde68a;

    /* Deep forest */
    --c10: #14532d;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  html, body { background: var(--bg); }

  body {
    font-family: 'Inter', 'Helvetica Neue', Helvetica, Arial, sans-serif;
    color: var(--ink);
    font-size: 11px;
    line-height: 1.65;
    min-height: 100vh;
  }

  /* ─── App shell ─── */
  .app { max-width: 1440px; margin: 0 auto; padding: 20px; }

  .app-header {
    background: linear-gradient(135deg, var(--c1d) 0%, #1a7a6e 100%);
    border-radius: 10px 10px 0 0;
    padding: 20px 24px 0;
    color: white;
  }
  .app-title {
    font-size: 22px;
    font-weight: 800;
    letter-spacing: -0.3px;
    color: white;
  }
  .app-subtitle {
    font-size: 10px;
    opacity: 0.6;
    margin-top: 3px;
    margin-bottom: 18px;
    font-weight: 500;
    letter-spacing: 0.03em;
  }

  /* ─── Tabs ─── */
  .tabs {
    display: flex;
    gap: 2px;
    border-bottom: none;
    padding-top: 4px;
  }
  .tab {
    padding: 9px 22px;
    cursor: pointer;
    font-size: 11px;
    font-weight: 600;
    color: rgba(255,255,255,0.65);
    background: rgba(255,255,255,0.1);
    border: 1px solid rgba(255,255,255,0.15);
    border-bottom: none;
    border-radius: 6px 6px 0 0;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    transition: background 0.15s, color 0.15s;
    user-select: none;
  }
  .tab:hover { background: rgba(255,255,255,0.18); color: white; }
  .tab.active {
    background: var(--panel);
    color: var(--c1);
    border-color: var(--line);
    border-bottom-color: var(--panel);
  }

  /* ─── Tab content ─── */
  .tab-content {
    background: var(--panel);
    border: 1px solid var(--line);
    border-top: none;
    border-radius: 0 0 10px 10px;
    padding: 20px;
    display: none;
    box-shadow: 0 4px 16px rgba(0,0,0,0.06);
  }
  .tab-content.active { display: block; }

  /* ─── Filter bar ─── */
  .filter-bar {
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
    padding: 10px 14px;
    background: var(--bg);
    border: 1px solid var(--line);
    border-radius: 6px;
    margin-bottom: 16px;
    align-items: center;
  }
  .filter-item { display: flex; flex-direction: column; gap: 3px; font-size: 10px; }
  .filter-label {
    color: var(--ink-soft);
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 9px;
  }
  .filter-value {
    background: white;
    border: 1px solid var(--line-strong);
    border-radius: 4px;
    padding: 5px 10px;
    min-width: 100px;
    font-weight: 600;
    color: var(--ink);
  }

  /* ─── Panel cards ─── */
  .panel {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 8px;
    padding: 16px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.05);
  }
  .panel-title {
    font-size: 10px;
    font-weight: 800;
    color: var(--ink-soft);
    margin-bottom: 14px;
    padding-bottom: 8px;
    border-bottom: 2px solid var(--line);
    text-transform: uppercase;
    letter-spacing: 0.1em;
  }

  /* ─── Grid layouts ─── */
  .top-row-3 {
    display: grid;
    grid-template-columns: 2fr 1.1fr 1.3fr;
    gap: 14px;
    margin-bottom: 14px;
  }
  .top-row-2 {
    display: grid;
    grid-template-columns: 1.5fr 1fr;
    gap: 14px;
    margin-bottom: 14px;
  }
  .three-col {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 14px;
    margin-bottom: 14px;
  }

  /* ─── Funnel bars ─── */
  .funnel-row {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 7px;
  }
  .funnel-label {
    width: 170px;
    font-weight: 600;
    color: var(--ink-mid);
    font-size: 10px;
  }
  .funnel-bar {
    flex: 1;
    height: 22px;
    background: var(--bg);
    position: relative;
    border-radius: 3px;
    overflow: hidden;
    border: 1px solid var(--line);
  }
  .funnel-fill {
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: flex-end;
    padding-right: 8px;
    color: white;
    font-weight: 700;
    font-size: 10px;
    border-radius: 3px;
  }

  /* ─── Provider list ─── */
  .provider-row {
    display: flex;
    justify-content: space-between;
    padding: 7px 10px;
    border-bottom: 1px solid var(--line);
    align-items: center;
    font-size: 10px;
    border-radius: 4px;
    margin-bottom: 2px;
    background: var(--bg);
  }
  .provider-row:last-child { border-bottom: none; margin-bottom: 0; }
  .provider-name { font-weight: 700; color: var(--ink-mid); }
  .provider-count {
    font-weight: 800;
    color: var(--c2);
    font-variant-numeric: tabular-nums;
  }

  /* ─── Ranking table ─── */
  .ranking-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 10px;
    border-radius: 6px;
    overflow: hidden;
  }
  .ranking-table th {
    text-align: left;
    padding: 7px 10px;
    background: var(--c1d);
    color: white;
    font-weight: 700;
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .ranking-table th:last-child { text-align: right; }
  .ranking-table td {
    padding: 6px 10px;
    border-bottom: 1px solid var(--line);
    color: var(--ink-mid);
  }
  .ranking-table td:last-child {
    text-align: right;
    font-weight: 800;
    color: var(--ink);
    font-variant-numeric: tabular-nums;
  }
  .ranking-table tr:nth-child(even) td { background: #f9f7f3; }
  .ranking-table tr.highlight td {
    background: var(--c1l);
    color: var(--c1);
    font-weight: 700;
  }
  .ranking-table tr.highlight td:first-child::before {
    content: "▶ ";
    color: var(--c1);
    font-size: 8px;
  }

  /* ─── Legend ─── */
  .legend {
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
    margin-bottom: 12px;
    font-size: 9px;
    align-items: center;
  }
  .legend-item { display: flex; align-items: center; gap: 6px; }
  .legend-swatch { width: 16px; height: 3px; border-radius: 2px; }

  /* ─── Heatmap ─── */
  .heatmap-wrap { overflow-x: auto; border-radius: 6px; }
  .heatmap {
    width: 100%;
    border-collapse: collapse;
    font-size: 9px;
    min-width: 800px;
  }
  .heatmap th {
    padding: 5px 6px;
    background: var(--c1d);
    border: 1px solid rgba(255,255,255,0.15);
    color: rgba(255,255,255,0.8);
    font-weight: 600;
    font-size: 8px;
    white-space: nowrap;
  }
  .heatmap th.brand-col { text-align: left; padding-left: 10px; min-width: 140px; color: white; }
  .heatmap td {
    padding: 5px 4px;
    border: 1px solid var(--line);
    text-align: center;
    font-size: 9px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }
  .heatmap td.brand-cell {
    text-align: left;
    font-weight: 700;
    background: var(--bg);
    padding-left: 10px;
    color: var(--ink-mid);
  }
  .heatmap td.brand-cell.main {
    background: var(--c9);
    color: var(--c1d);
    font-weight: 800;
  }
  .heatmap .callout-row th {
    background: white;
    border: none;
    padding: 1px 2px;
    height: 22px;
    vertical-align: middle;
    position: relative;
  }
  .heatmap .callout-row th.pair-bar {
    border-radius: 4px;
    color: white;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.4px;
    text-transform: uppercase;
    padding: 2px 6px;
    white-space: nowrap;
    height: 18px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.15);
  }
  .callout-row th.pair-bar .bar-edge {
    display: inline-block;
    font-size: 11px;
    opacity: 0.85;
    margin: 0 4px;
    vertical-align: middle;
  }
  .callout-row th.pair-bar .bar-label {
    display: inline-block;
    vertical-align: middle;
  }
  .callout-row .impl-block {
    display: block;
    width: 80%;
    height: 14px;
    margin: 0 auto;
    border-radius: 3px;
    opacity: 0.7;
    box-shadow: 0 1px 2px rgba(0,0,0,0.1);
  }
  .heatmap th.brand-col.callout-lane-label {
    text-align: right;
    padding-right: 8px;
    font-size: 9px;
    font-weight: 700;
    color: #56635e;
    background: white;
    text-transform: uppercase;
    letter-spacing: 0.4px;
    min-width: 90px;
  }
  .callout-pin {
    display: inline-block;
    background: var(--c2);
    color: white;
    font-size: 8.5px;
    font-weight: 700;
    padding: 2px 5px;
    border-radius: 3px;
    line-height: 1.2;
    text-transform: uppercase;
    letter-spacing: 0.3px;
    white-space: nowrap;
    max-width: 110px;
    overflow: hidden;
    text-overflow: ellipsis;
    text-align: center;
    box-shadow: 0 1px 3px rgba(0,0,0,0.15);
    margin: 0 1px;
  }
  .heatmap-legend {
    display: flex;
    gap: 14px;
    margin-top: 10px;
    flex-wrap: wrap;
    font-size: 9px;
    color: var(--ink-soft);
    align-items: center;
  }
  .heatmap-legend-item { display: flex; align-items: center; gap: 5px; }
  .heatmap-legend-swatch { width: 10px; height: 10px; border-radius: 2px; }

  /* ─── Keyword bars ─── */
  .keyword-bars { display: flex; flex-direction: column; gap: 6px; }
  .kw-row { display: flex; align-items: center; gap: 8px; font-size: 10px; }
  .kw-label {
    width: 220px;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    color: var(--ink-mid);
  }
  .kw-bar {
    flex: 1;
    height: 20px;
    background: var(--bg);
    border: 1px solid var(--line);
    border-radius: 3px;
    overflow: hidden;
    position: relative;
  }
  .kw-fill {
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: flex-end;
    padding-right: 7px;
    color: white;
    font-weight: 700;
    font-size: 9px;
    border-radius: 3px;
  }

  /* ─── Footer ─── */
  .footer {
    margin-top: 16px;
    padding: 14px 16px;
    border: 1px solid var(--line);
    border-radius: 6px;
    background: var(--bg);
    font-size: 9px;
    color: var(--ink-soft);
    line-height: 1.65;
  }
  .footer strong { color: var(--c1); }
  .footer-title {
    font-weight: 800;
    color: var(--ink-mid);
    margin-bottom: 6px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-size: 9px;
  }

  /* ─── Charts ─── */
  .single-kw-chart { width: 100%; height: 200px; }
  .chart-container {
    width: 100%;
    background: white;
    border-radius: 4px;
    position: relative;
  }
  .chart-container svg { display: block; width: 100%; height: auto; }

  .chart-toggle {
    display: inline-flex;
    margin-bottom: 12px;
    border-radius: 6px;
    overflow: hidden;
    border: 1px solid var(--line-strong);
  }
  .chart-toggle button {
    padding: 5px 16px;
    background: var(--bg);
    border: none;
    border-right: 1px solid var(--line-strong);
    cursor: pointer;
    font-size: 10px;
    font-weight: 700;
    color: var(--ink-soft);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-family: inherit;
    transition: background 0.12s, color 0.12s;
  }
  .chart-toggle button:last-child { border-right: none; }
  .chart-toggle button:hover { background: var(--c1l); color: var(--c1); }
  .chart-toggle button.active {
    background: var(--c1);
    color: white;
  }

  .chart-tooltip {
    position: absolute;
    background: var(--ink);
    color: white;
    padding: 6px 11px;
    font-size: 10px;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.1s;
    border-radius: 4px;
    white-space: nowrap;
    z-index: 100;
    font-weight: 600;
    box-shadow: 0 4px 12px rgba(0,0,0,0.25);
  }

  /* ─── Donut charts ─── */
  .donut-wrap { display: flex; gap: 20px; align-items: center; flex-wrap: wrap; }
  .donut-legend { display: flex; flex-direction: column; gap: 5px; font-size: 10px; }
  .donut-legend-item { display: flex; align-items: center; gap: 7px; }
  .donut-legend-swatch { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
  .donut-label { font-weight: 600; color: var(--ink-mid); }
  .donut-pct { color: var(--ink-soft); }
"""

JS_RENDER_CHART = """\
  function renderChart(containerId, dates, series, options) {
    options = options || {};
    const container = document.getElementById(containerId);
    if (!container) return;

    const yMax    = options.yMax    || 100;
    const W       = 1200;
    const H       = options.height  || 400;
    const padL    = options.padL    || ((options.annotations || []).length ? 100 : 52);
    const padR    = options.padR || 80;
    const padT    = options.padT    || 40;
    const padB    = 44;
    const plotW   = W - padL - padR;
    const plotH     = H - padT - padB;
    const n         = dates.length;
    const stepX     = plotW / Math.max(1, n - 1);
    const barStepX  = plotW / Math.max(1, n);
    const yToPx     = function(v)  { return padT + plotH - (v / yMax) * plotH; };
    const xToPx     = function(i)  { return padL + i * stepX; };
    const barXToPx  = function(i)  { return padL + (i + 0.5) * barStepX; };

    const annotations  = options.annotations  || [];
    const datesIso     = options.datesIso     || [];
    const labelIndices = new Set(options.labelIndices || []);

    const initialMode = options.initialMode || 'line';
    container.innerHTML =
      '<div class="chart-toggle" data-chart="' + containerId + '">' +
      '<button class="' + (initialMode === 'line' ? 'active' : '') + '" data-mode="line">Line</button>' +
      '<button class="' + (initialMode === 'bar'  ? 'active' : '') + '" data-mode="bar">Grouped Bar</button>' +
      '</div>' +
      '<div class="chart-tooltip" id="' + containerId + '-tooltip"></div>' +
      '<svg id="' + containerId + '-svg" viewBox="0 0 ' + W + ' ' + H + '"' +
      ' style="display:block;width:100%;height:auto;overflow:visible;"></svg>';

    const svg     = document.getElementById(containerId + '-svg');
    const tooltip = document.getElementById(containerId + '-tooltip');
    const NS      = 'http://www.w3.org/2000/svg';

    function el(tag, attrs, text) {
      const e = document.createElementNS(NS, tag);
      for (const k in attrs) e.setAttribute(k, attrs[k]);
      if (text != null) e.textContent = text;
      svg.appendChild(e);
      return e;
    }

    function showTip(evt, text) {
      tooltip.textContent = text;
      tooltip.style.opacity = 1;
      const r = container.getBoundingClientRect();
      tooltip.style.left = (evt.clientX - r.left + 12) + 'px';
      tooltip.style.top  = (evt.clientY - r.top  - 10) + 'px';
    }
    function hideTip() { tooltip.style.opacity = 0; }

    function draw(mode) {
      svg.innerHTML = '';

      if (mode === 'line' && annotations.length) {
        // Lane-based layout: each annotation has a `row` field naming its lane.
        const activeLanes = Array.from(new Set(annotations.map(function(a){ return a.row || 0; }))).sort(function(a,b){ return a-b; });
        const laneIndex = {};
        activeLanes.forEach(function(l, i){ laneIndex[l] = i; });
        const maxPillW = Math.max(20, stepX - 2);
        // Reserved label gutter — pills must not extend into this zone
        const LABEL_GUTTER_END = padL - 4;

        // Lane label + color, taken from first event in each lane
        const laneLabel = {};
        const laneColor = {};
        annotations.forEach(function(a) {
          if (laneLabel[(a.row || 0)] == null) {
            laneLabel[(a.row || 0)] = a.type || '';
            laneColor[(a.row || 0)] = a.color;
          }
        });

        // Build paired bars + unpaired singletons + breakouts
        const byPair = {};
        const unpaired = [];   // events without a pair_id (or breakouts) — render as compact markers
        annotations.forEach(function(a) {
          let idx = -1;
          if (a.iso_date && datesIso.length) {
            idx = datesIso.indexOf(a.iso_date);
          }
          if (idx === -1) idx = dates.indexOf(a.date);
          if (idx === -1) return;
          if (a.pair_id) {
            if (!byPair[a.pair_id]) byPair[a.pair_id] = { color: a.color, type: a.type, lane: laneIndex[(a.row || 0)] };
            byPair[a.pair_id][a.kind] = idx;
          } else {
            unpaired.push({ idx: idx, lane: laneIndex[(a.row || 0)], color: a.color,
                            type: a.type, kind: a.kind, label: a.label });
          }
        });

        // Number pairs per lane so the bar can say "Blog 1", "Blog 2", etc.
        const laneCounters = {};
        const pairList = [];
        Object.keys(byPair).sort().forEach(function(pid) {
          const p = byPair[pid];
          if (p.impl == null || p.attr == null) {
            // Incomplete pair — treat impl as unpaired dot
            if (p.impl != null) {
              unpaired.push({ idx: p.impl, lane: p.lane, color: p.color, type: p.type, kind: 'impl', label: 'impl.' });
            }
            return;
          }
          const lo = Math.min(p.impl, p.attr);
          const hi = Math.max(p.impl, p.attr);
          const num = (laneCounters[p.lane] = (laneCounters[p.lane] || 0) + 1);
          pairList.push({ lo: lo, hi: hi, lane: p.lane, color: p.color, type: p.type, num: num });
        });

        // Greedy interval scheduling per lane: assign each pair (and breakout
        // marker) a sublane index so overlapping items don't collide. Pairs are
        // scheduled first (sorted by lo) since they occupy more horizontal space.
        const subCountByLane = {};
        const itemsByLane = {};
        pairList.forEach(function(b) {
          (itemsByLane[b.lane] = itemsByLane[b.lane] || { pairs: [], breakouts: [] }).pairs.push(b);
        });
        unpaired.forEach(function(u) {
          if (u.kind !== 'breakout') return;
          (itemsByLane[u.lane] = itemsByLane[u.lane] || { pairs: [], breakouts: [] }).breakouts.push(u);
        });
        activeLanes.forEach(function(_, laneIdx) {
          const bucket = itemsByLane[laneIdx] || { pairs: [], breakouts: [] };
          const sortedPairs = bucket.pairs.slice().sort(function(a, b){ return a.lo - b.lo; });
          const sortedBreakouts = bucket.breakouts.slice().sort(function(a, b){ return a.idx - b.idx; });
          const lastEnd = []; // last hi per sublane
          function assign(lo, hi, item) {
            for (let si = 0; si < lastEnd.length; si++) {
              if (lastEnd[si] < lo) { item.sublane = si; lastEnd[si] = hi; return; }
            }
            item.sublane = lastEnd.length;
            lastEnd.push(hi);
          }
          sortedPairs.forEach(function(b){ assign(b.lo, b.hi, b); });
          sortedBreakouts.forEach(function(u){ assign(u.idx, u.idx, u); });
          subCountByLane[laneIdx] = Math.max(1, lastEnd.length);
        });

        // Total sublanes across all lanes drive the row-height denominator
        let totalSub = 0;
        activeLanes.forEach(function(_, i){ totalSub += subCountByLane[i] || 1; });
        const subRowH = Math.max(8, Math.floor((padT - 6) / Math.max(1, totalSub)));
        // Lane start Y (cumulative sublane heights above)
        const laneStartY = {};
        let acc = 2;
        activeLanes.forEach(function(_, i) {
          laneStartY[i] = acc;
          acc += subRowH * (subCountByLane[i] || 1);
        });

        // Draw lane labels in the gutter (right-aligned at LABEL_GUTTER_END).
        // Label anchored to the FIRST sublane row of each lane.
        activeLanes.forEach(function(lane, i) {
          const y0 = laneStartY[i];
          const label = laneLabel[lane] || '';
          el('text', { x: LABEL_GUTTER_END, y: y0 + subRowH - 7,
                       'text-anchor': 'end',
                       'font-size': Math.min(9.5, subRowH - 6),
                       'font-weight': 700,
                       fill: laneColor[lane] || '#56635e',
                       'letter-spacing': '0.3' }, label);
        });

        // Draw vertical guide lines from each pair endpoint down through the plot.
        // Drop lines start at the BOTTOM of the lane (all sublanes combined).
        pairList.forEach(function(b) {
          const laneBottom = laneStartY[b.lane] + subRowH * (subCountByLane[b.lane] || 1);
          const x1 = xToPx(b.lo);
          const x2 = xToPx(b.hi);
          el('line', { x1: x1, y1: laneBottom, x2: x1, y2: H - padB,
                       stroke: b.color, 'stroke-width': 1.2,
                       'stroke-dasharray': '4,3', opacity: 0.32 });
          el('line', { x1: x2, y1: laneBottom, x2: x2, y2: H - padB,
                       stroke: b.color, 'stroke-width': 1.2,
                       'stroke-dasharray': '4,3', opacity: 0.32 });
        });

        // Draw span bars per pair (positioned at its sublane within the lane)
        pairList.forEach(function(b) {
          const y0 = laneStartY[b.lane] + (b.sublane || 0) * subRowH;
          const x1 = xToPx(b.lo);
          const x2 = xToPx(b.hi);
          const barX = x1 - 6;
          const barW = (x2 - x1) + 12;
          // Clamp to gutter
          const left = Math.max(barX, LABEL_GUTTER_END + 2);
          const width = Math.max(20, barW - (left - barX));
          el('rect', { x: left, y: y0, width: width, height: subRowH - 3,
                       fill: b.color, rx: 3, opacity: 0.9 });
          // Edge caret marks
          const cy = y0 + subRowH / 2 + 2.5;
          el('text', { x: left + 6, y: cy, 'text-anchor': 'start',
                       'font-size': 10, 'font-weight': 700, fill: 'white' }, '▸');
          el('text', { x: left + width - 6, y: cy, 'text-anchor': 'end',
                       'font-size': 10, 'font-weight': 700, fill: 'white' }, '◂');
          // Center label "Type N"
          const lblText = (b.type || '') + ' ' + b.num;
          el('text', { x: left + width / 2, y: cy, 'text-anchor': 'middle',
                       'font-size': Math.min(9, subRowH - 6), 'font-weight': 700, fill: 'white' }, lblText);
        });

        // Draw unpaired markers — only breakouts. Non-primary impls are intentionally
        // omitted from the chart to reduce clutter (still present in attributions.json).
        unpaired.forEach(function(u) {
          if (u.kind !== 'breakout') return;
          const x    = xToPx(u.idx);
          const y0   = laneStartY[u.lane] + (u.sublane || 0) * subRowH;
          const laneBottom = laneStartY[u.lane] + subRowH * (subCountByLane[u.lane] || 1);
          const fontSize = Math.min(9, subRowH - 5);
          const desired = u.label.length * (fontSize * 0.55) + 8;
          const lw = Math.min(maxPillW, desired);
          let rectX = x - lw / 2;
          if (rectX < LABEL_GUTTER_END + 2) rectX = LABEL_GUTTER_END + 2;
          el('rect', { x: rectX, y: y0, width: lw, height: subRowH - 3,
                       fill: u.color, rx: 2 });
          el('text', { x: rectX + lw / 2, y: y0 + subRowH - 6, 'text-anchor': 'middle',
                       'font-size': fontSize, 'font-weight': 700, fill: 'white' }, u.label);
          el('line', { x1: x, y1: laneBottom, x2: x, y2: H - padB,
                       stroke: u.color, 'stroke-width': 1.2,
                       'stroke-dasharray': '4,3', opacity: 0.35 });
        });
      }

      const ySteps = 5;
      for (let i = 0; i <= ySteps; i++) {
        const v = (yMax / ySteps) * i;
        const y = yToPx(v);
        el('line', { x1: padL, y1: y, x2: W - padR, y2: y,
                     stroke: i === 0 ? '#1a2f2a' : '#e3ddd0',
                     'stroke-dasharray': i === 0 ? 'none' : '2,2',
                     'stroke-width': i === 0 ? 1.5 : 1 });
        el('text', { x: padL - 6, y: y + 4, 'font-size': 10, fill: '#56635e',
                     'text-anchor': 'end', 'font-weight': 600 }, v.toFixed(0) + '%');
      }
      el('line', { x1: padL, y1: padT, x2: padL, y2: H - padB,
                   stroke: '#1a2f2a', 'stroke-width': 1.5 });

      const xLabel = mode === 'bar' ? barXToPx : xToPx;
      dates.forEach(function(d, i) {
        el('text', { x: xLabel(i), y: H - padB + 14,
                     'font-size': 9.5, fill: '#56635e', 'text-anchor': 'middle' }, d);
      });

      if (mode === 'line') {
        const comps = series.filter(function(s) { return !s.highlight; });
        const main  = series.find(function(s)  { return  s.highlight; });

        comps.forEach(function(s) {
          const pts = s.values.map(function(v, i) {
            return xToPx(i).toFixed(1) + ',' + yToPx(v).toFixed(1);
          }).join(' ');
          el('polyline', { fill: 'none', stroke: s.color, 'stroke-width': 1.5,
                           'stroke-opacity': 0.5, points: pts,
                           'stroke-linecap': 'round', 'stroke-linejoin': 'round' });
          s.values.forEach(function(v, i) {
            const cx = xToPx(i), cy = yToPx(v);
            const c = el('circle', { cx: cx, cy: cy, r: 3, fill: 'white',
                                     stroke: s.color, 'stroke-width': 1.2,
                                     'stroke-opacity': 0.6, style: 'cursor:pointer' });
            c.addEventListener('mouseenter', function(e) { showTip(e, s.name + ' · ' + dates[i] + ' · ' + v.toFixed(1) + '%'); });
            c.addEventListener('mouseleave', hideTip);
          });
          const lastV = s.values[s.values.length - 1];
          const lx    = xToPx(s.values.length - 1) + 6;
          const ly    = yToPx(lastV) + 4;
          el('text', { x: lx, y: ly, 'font-size': 9, fill: s.color,
                       'font-weight': 600, opacity: 0.8 }, lastV.toFixed(1) + '%');
        });

        if (main) {
          const pts = main.values.map(function(v, i) {
            return xToPx(i).toFixed(1) + ',' + yToPx(v).toFixed(1);
          }).join(' ');
          el('polyline', { fill: 'none', stroke: main.color, 'stroke-width': 4,
                           points: pts, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' });
          main.values.forEach(function(v, i) {
            const cx = xToPx(i), cy = yToPx(v);
            const isLabel = labelIndices.has(i) || i === 0 || i === main.values.length - 1;
            const c = el('circle', { cx: cx, cy: cy, r: isLabel ? 5 : 4,
                                     fill: main.color, stroke: 'white', 'stroke-width': 1.8,
                                     style: 'cursor:pointer' });
            c.addEventListener('mouseenter', function(e) { showTip(e, main.name + ' · ' + dates[i] + ' · ' + v.toFixed(1) + '%'); });
            c.addEventListener('mouseleave', hideTip);
            if (isLabel) {
              const above = cy > padT + 20;
              const ly2   = above ? cy - 10 : cy + 17;
              const lw    = (v.toFixed(1) + '%').length * 5.8 + 8;
              el('rect', { x: cx - lw/2, y: ly2 - 11, width: lw, height: 13,
                           fill: 'white', opacity: 0.9, rx: 2 });
              el('text', { x: cx, y: ly2, 'font-size': 10, fill: main.color,
                           'text-anchor': 'middle', 'font-weight': 800 }, v.toFixed(1) + '%');
            }
          });
        }
      } else {
        const groupW = barStepX * 0.82;
        const barW   = Math.max(2, groupW / series.length - 1);
        dates.forEach(function(d, i) {
          const gx = barXToPx(i) - groupW / 2;
          series.forEach(function(s, si) {
            const v  = s.values[i];
            const x  = gx + si * (barW + 1);
            const y  = yToPx(v);
            const h  = (H - padB) - y;
            const r  = el('rect', { x: x, y: y, width: barW, height: h,
                                    fill: s.color, opacity: s.highlight ? 1 : 0.7,
                                    style: 'cursor:pointer' });
            r.addEventListener('mouseenter', function(e) { showTip(e, s.name + ' · ' + d + ' · ' + v.toFixed(1) + '%'); });
            r.addEventListener('mouseleave', hideTip);
            if (s.highlight && barW > 6) {
              el('text', { x: x + barW/2, y: y - 3, 'font-size': 9,
                           fill: s.color, 'text-anchor': 'middle', 'font-weight': 700 }, v.toFixed(0));
            }
          });
        });
      }
    }

    draw(initialMode);

    container.querySelectorAll('.chart-toggle button').forEach(function(btn) {
      btn.addEventListener('click', function() {
        container.querySelectorAll('.chart-toggle button').forEach(function(b) { b.classList.remove('active'); });
        btn.classList.add('active');
        draw(btn.getAttribute('data-mode'));
      });
    });
  }
"""

JS_RENDER_DONUT = """\
  function renderDonut(containerId, segments, options) {
    options = options || {};
    const container = document.getElementById(containerId);
    if (!container) return;
    const size = options.size || 160;
    const ir   = options.innerRadius || 0.6;
    const cx   = size / 2, cy = size / 2, r = size / 2 - 4;
    const total = segments.reduce(function(s, seg) { return s + seg.value; }, 0);
    if (!total) {
      container.innerHTML = '<p style="color:var(--ink-soft);font-size:10px">No data</p>';
      return;
    }
    const NS  = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 ' + size + ' ' + size);
    svg.setAttribute('width', size);
    svg.setAttribute('height', size);
    let startAngle = -Math.PI / 2;
    const tooltip = document.createElement('div');
    tooltip.className = 'chart-tooltip';
    tooltip.style.position = 'absolute';
    container.style.position = 'relative';
    container.appendChild(tooltip);
    segments.forEach(function(seg) {
      const angle    = (seg.value / total) * 2 * Math.PI;
      const endAngle = startAngle + angle;
      const x1  = cx + r    * Math.cos(startAngle);
      const y1  = cy + r    * Math.sin(startAngle);
      const x2  = cx + r    * Math.cos(endAngle);
      const y2  = cy + r    * Math.sin(endAngle);
      const ir2 = r * ir;
      const xi1 = cx + ir2  * Math.cos(endAngle);
      const yi1 = cy + ir2  * Math.sin(endAngle);
      const xi2 = cx + ir2  * Math.cos(startAngle);
      const yi2 = cy + ir2  * Math.sin(startAngle);
      const large = angle > Math.PI ? 1 : 0;
      const path  = document.createElementNS(NS, 'path');
      const d = 'M ' + x1 + ' ' + y1 +
                ' A ' + r + ' ' + r + ' 0 ' + large + ' 1 ' + x2 + ' ' + y2 +
                ' L ' + xi1 + ' ' + yi1 +
                ' A ' + ir2 + ' ' + ir2 + ' 0 ' + large + ' 0 ' + xi2 + ' ' + yi2 + ' Z';
      path.setAttribute('d', d);
      path.setAttribute('fill', seg.color);
      path.setAttribute('stroke', 'white');
      path.setAttribute('stroke-width', '1.5');
      path.style.cursor = 'pointer';
      const pct = ((seg.value / total) * 100).toFixed(1);
      path.addEventListener('mouseenter', function(e) {
        tooltip.textContent = seg.label + ': ' + pct + '%';
        tooltip.style.opacity = 1;
        tooltip.style.left = (e.offsetX + 10) + 'px';
        tooltip.style.top  = (e.offsetY - 10) + 'px';
      });
      path.addEventListener('mouseleave', function() { tooltip.style.opacity = 0; });
      svg.appendChild(path);
      startAngle = endAngle;
    });
    if (options.centerLabel) {
      const t = document.createElementNS(NS, 'text');
      t.setAttribute('x', cx); t.setAttribute('y', cy + 4);
      t.setAttribute('text-anchor', 'middle');
      t.setAttribute('font-size', '10'); t.setAttribute('font-weight', '700');
      t.setAttribute('fill', 'var(--ink)');
      t.textContent = options.centerLabel;
      svg.appendChild(t);
    }
    container.appendChild(svg);
  }
"""


def donut_legend_html(segments):
    items = []
    for seg in segments:
        lbl = html_escape(seg["label"])
        color = seg["color"]
        val = seg["value"]
        items.append(
            f'<div class="donut-legend-item">'
            f'<span class="donut-legend-swatch" style="background:{color};"></span>'
            f'<span class="donut-label">{lbl}</span>'
            f'<span class="donut-pct">&nbsp;{val:.1f}</span>'
            f'</div>'
        )
    return '<div class="donut-legend">' + "\n".join(items) + "</div>"


def build_single_run_series(rows, all_brands, target_name, colors):
    """
    When only one run exists, build a bar-chart-friendly series
    with dates = brand names and a single series for that run.
    """
    presence = compute_presence(rows, all_brands)
    sorted_brands = sorted(all_brands, key=lambda b: presence.get(b, 0), reverse=True)
    dates = sorted_brands
    values = [round(presence.get(b, 0), 1) for b in sorted_brands]
    series = [
        {
            "name": "% Presence",
            "color": TARGET_COLOR,
            "highlight": True,
            "values": values,
        }
    ]
    return dates, [""] * len(dates), series


def footer_html(brand_name, is_demo):
    demo_note = (
        '<br><strong>Note:</strong> Showing demo data. '
        'Run Phase 3 and Phase 4 to populate with real scored responses.'
    ) if is_demo else ""
    return f"""<div class="footer">
      <div class="footer-title">Dashboard Description</div>
      <strong>Purpose:</strong> Review and improve {html_escape(brand_name)}'s brand visibility in the LLM environment.<br>
      <strong>Brand presence %:</strong> The share of (query, engine) rows in which the brand appears in the response. 100% means the brand appeared in every tested response.<br>
      <strong>Share of voice %:</strong> Proportion of total brand mentions attributable to each brand across all rows.<br>
      <strong>Discovery role:</strong> recommended = named as a top choice; listed = included in a list; cited = referenced; absent = not mentioned.{demo_note}
    </div>"""


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

def build_html(
    rows,
    all_brands,
    target_name,
    colors,
    queries_data,
    runs,             # list of (date_label, iso_date, rows) for time-series
    strategy_events,
    is_demo,
    today_label,
    today_iso="",
):
    single_run_mode = len(runs) <= 1
    queries = queries_data.get("queries", [])
    query_map = {q["id"]: q for q in queries}

    # Category info
    cat_names = {}
    cat_queries = defaultdict(list)
    for q in queries:
        cat_names[q["category"]] = q["category_name"]
        cat_queries[q["category_name"]].append(q)

    # Sort categories alphabetically
    sorted_cats = sorted(cat_queries.keys())
    default_cat = sorted_cats[0] if sorted_cats else ""
    def _query_target_presence(q):
        qrows = [r for r in rows if r["query_id"] == q["id"]]
        return compute_presence(qrows, all_brands).get(target_name, 0)
    default_query = max(queries, key=_query_target_presence) if queries else {}

    # Engines
    engines = get_engines(rows)
    e1 = engines[0] if len(engines) > 0 else "Engine 1"
    e2 = engines[1] if len(engines) > 1 else "Engine 2"
    e1_name = engine_display_name(e1)
    e2_name = engine_display_name(e2)

    # --- Overview metrics ---
    presence_all = compute_presence(rows, all_brands)
    presence_e1 = compute_presence(rows, all_brands, filter_fn=lambda r: r["engine"] == e1)
    presence_e2 = compute_presence(rows, all_brands, filter_fn=lambda r: r["engine"] == e2)
    sov = compute_sov(rows, all_brands)
    discovery = compute_discovery(rows, target_name)

    # SOV segments for donut
    sov_segments = []
    for brand in all_brands:
        v = sov.get(brand, 0)
        if v > 0.1:
            sov_segments.append({"label": brand, "value": v, "color": colors.get(brand, "#aaa")})
    if not sov_segments:
        sov_segments = [{"label": brand, "value": 1, "color": colors.get(brand, "#aaa")} for brand in all_brands[:4]]

    # Discovery segments for donut
    disc_colors = {
        "recommended": "#2d6a4f",
        "listed":      "#6a994e",
        "cited":       "#adc178",
        "absent":      "#e3ddd0",
    }
    discovery_segments = []
    for role in ["recommended", "listed", "cited", "absent"]:
        count = discovery.get(role, 0)
        if count > 0:
            discovery_segments.append({
                "label": role.title(),
                "value": count,
                "color": disc_colors[role],
            })

    # Category distribution
    cat_counts = {}
    for cat_name, qs in cat_queries.items():
        cat_counts[cat_name] = len(qs)

    # Per-query presence for target brand
    presence_by_query = {}
    for q in queries:
        qid = q["id"]
        pres = compute_presence(rows, all_brands, filter_fn=lambda r, qid=qid: r["query_id"] == qid)
        presence_by_query[qid] = pres

    # Per-category presence
    presence_by_cat = {}
    for cat_name, qs in cat_queries.items():
        qids = {q["id"] for q in qs}
        pres = compute_presence(rows, all_brands, filter_fn=lambda r, qids=qids: r["query_id"] in qids)
        presence_by_cat[cat_name] = pres

    # Category donut for target: presence across categories
    cat_donut_segments = []
    cat_donut_colors = ["#2d6a4f", "#6a994e", "#adc178", "#d4a373", "#9c6644", "#81b29a", "#b08968", "#386641", "#bc4749"]
    for idx, cat_name in enumerate(sorted_cats):
        pct = presence_by_cat.get(cat_name, {}).get(target_name, 0)
        cat_donut_segments.append({
            "label": cat_name,
            "value": max(pct, 0.01),
            "color": cat_donut_colors[idx % len(cat_donut_colors)],
        })

    # Time-series data for charts
    if len(runs) > 1:
        ov_dates, ov_dates_iso, ov_series = build_series_from_runs(runs, all_brands, target_name, colors)
        cat_dates, cat_dates_iso, cat_series = build_series_from_runs(
            runs, all_brands, target_name, colors,
            filter_fn=lambda r: query_map.get(r["query_id"], {}).get("category_name", "") == default_cat,
        )
        kw_dates, kw_dates_iso, kw_series = build_series_from_runs(
            runs, all_brands, target_name, colors,
            filter_fn=lambda r: r["query_id"] == (default_query.get("id", "") if default_query else ""),
        )
    else:
        ov_dates, ov_dates_iso, ov_series = build_single_run_series(rows, all_brands, target_name, colors)
        cat_rows = [r for r in rows if query_map.get(r["query_id"], {}).get("category_name", "") == default_cat]
        cat_dates, cat_dates_iso, cat_series = build_single_run_series(cat_rows, all_brands, target_name, colors)
        kw_qid = default_query.get("id", "") if default_query else ""
        kw_rows = [r for r in rows if r["query_id"] == kw_qid]
        kw_dates, kw_dates_iso, kw_series = build_single_run_series(kw_rows, all_brands, target_name, colors)

    def _nice_ymax(raw_max):
        raw = max(raw_max * 1.15, 10)
        return math.ceil(raw / 5) * 5

    ov_ymax  = _nice_ymax(max((max(s["values"]) for s in ov_series  if s["values"]), default=100))
    cat_ymax = _nice_ymax(max((max(s["values"]) for s in cat_series if s["values"]), default=100))
    kw_ymax  = _nice_ymax(max((max(s["values"]) for s in kw_series  if s["values"]), default=100))

    # Annotations
    annotations = strategy_events or []

    # Full runs list for heatmaps (add current run if not already present)
    full_runs = list(runs)
    if not runs or runs[-1][0] != today_label:
        full_runs = list(runs) + [(today_label, today_iso, rows)]

    # Single-run heatmap (just today)
    single_run = [(today_label, today_iso, rows)]

    # -------------------------------------------------------------------------
    # Build HTML sections
    # -------------------------------------------------------------------------

    # Filter bar overview
    fb_overview = render_filter_bar([
        ("Brand", target_name),
        ("Engines", str(len(engines))),
        ("Queries", str(len(queries))),
        ("Run date", today_label),
        ("Data", "DEMO" if is_demo else "Live"),
    ])

    fb_category = render_filter_bar([
        ("Brand", target_name),
        ("Category", default_cat),
        ("Engines", str(len(engines))),
        ("Data", "DEMO" if is_demo else "Live"),
    ])

    fb_keyword = render_filter_bar([
        ("Brand", target_name),
        ("Query", (default_query.get("query", "")[:60] + "...") if default_query else ""),
        ("Engines", str(len(engines))),
        ("Data", "DEMO" if is_demo else "Live"),
    ])

    # Ranking tables: overview
    ranking_all = render_ranking_table(f"All Engines: % Presence", presence_all, all_brands, target_name)
    ranking_e1  = render_ranking_table(f"{e1_name}: % Presence", presence_e1, all_brands, target_name)
    ranking_e2  = render_ranking_table(f"{e2_name}: % Presence", presence_e2, all_brands, target_name)

    # Ranking tables: category
    cat_e_all = compute_presence(rows, all_brands, filter_fn=lambda r: query_map.get(r["query_id"], {}).get("category_name", "") == default_cat)
    cat_e1    = compute_presence(rows, all_brands, filter_fn=lambda r: r["engine"] == e1 and query_map.get(r["query_id"], {}).get("category_name", "") == default_cat)
    cat_e2    = compute_presence(rows, all_brands, filter_fn=lambda r: r["engine"] == e2 and query_map.get(r["query_id"], {}).get("category_name", "") == default_cat)
    ranking_cat_all = render_ranking_table(f"All Engines: % Presence", cat_e_all, all_brands, target_name)
    ranking_cat_e1  = render_ranking_table(f"{e1_name}: % Presence", cat_e1, all_brands, target_name)
    ranking_cat_e2  = render_ranking_table(f"{e2_name}: % Presence", cat_e2, all_brands, target_name)

    # Ranking tables: keyword
    kw_qid = default_query.get("id", "") if default_query else ""
    kw_e_all = compute_presence(rows, all_brands, filter_fn=lambda r, qid=kw_qid: r["query_id"] == qid)
    kw_e1    = compute_presence(rows, all_brands, filter_fn=lambda r, qid=kw_qid: r["engine"] == e1 and r["query_id"] == qid)
    kw_e2    = compute_presence(rows, all_brands, filter_fn=lambda r, qid=kw_qid: r["engine"] == e2 and r["query_id"] == qid)
    ranking_kw_all = render_ranking_table("All Engines: % Presence", kw_e_all, all_brands, target_name)
    ranking_kw_e1  = render_ranking_table(f"{e1_name}: % Presence", kw_e1, all_brands, target_name)
    ranking_kw_e2  = render_ranking_table(f"{e2_name}: % Presence", kw_e2, all_brands, target_name)

    # Category keyword bars
    kw_bars_html = render_kw_bars(cat_queries.get(default_cat, []), presence_by_query, target_name)

    # Heatmaps
    heatmap_overview = render_heatmap(
        f"Time-Series: % Presence per Brand -- {today_label}",
        full_runs,
        all_brands,
        target_name,
        strategy_events=strategy_events,
    )
    heatmap_category = render_heatmap(
        f"Time-Series: % Presence per Brand -- {default_cat}",
        full_runs,
        all_brands,
        target_name,
        strategy_events=strategy_events,
        filter_fn=lambda r: query_map.get(r["query_id"], {}).get("category_name", "") == default_cat,
    )
    heatmap_keyword = render_heatmap(
        f"Time-Series: % Presence per Brand -- {default_query.get('query', '')[:60] if default_query else ''}",
        full_runs,
        all_brands,
        target_name,
        filter_fn=lambda r, qid=kw_qid: r["query_id"] == qid,
    )

    # Legend
    legend_series = [{"name": b, "color": colors.get(b, "#aaa"), "highlight": b == target_name} for b in all_brands[:8]]
    legend_html = render_legend(legend_series)

    # Funnel bars
    funnel_html = render_funnel_bars(cat_counts, queries_data)

    # Engine panel
    engine_panel_html = render_engine_panel(engines, rows)

    # SOV donut legend
    sov_legend = donut_legend_html(sov_segments[:8])
    disc_legend = donut_legend_html(discovery_segments)
    cat_donut_legend = donut_legend_html(cat_donut_segments)

    dq_text = html_escape(default_query.get("query", "")[:80] + "..." if default_query and len(default_query.get("query", "")) > 80 else default_query.get("query", "") if default_query else "")
    # Panel title strings — different wording for single-run vs multi-run
    ov_chart_title = "% Presence by Brand — Single Run" if single_run_mode else "% Presence Over Time"
    cat_chart_title = f"% Presence by Brand — {html_escape(default_cat)}" if single_run_mode else f"Category Trend: % Presence Over Time — {html_escape(default_cat)}"
    kw_chart_title_prefix = "% Presence by Brand (Query: " if single_run_mode else "% Presence Over Time (Query: "

    single_run_note = ""
    if single_run_mode and not is_demo:
        single_run_note = (
            '<div style="background:#f0f7f4;border-left:4px solid #2d6a4f;padding:10px 14px;'
            'font-size:10px;color:#2d6a4f;font-weight:600;margin-bottom:14px;">'
            'Single run — charts show brand ranking for this run. '
            'Save runs to <code>runs/YYYY-MM-DD/scored_rows.jsonl</code> over time to enable trend lines.'
            '</div>'
        )

    demo_banner = ""
    if is_demo:
        demo_banner = (
            '<div style="background:#fff8e8;border-left:4px solid #bc4749;padding:10px 14px;'
            'font-size:10px;color:#bc4749;font-weight:700;margin-bottom:14px;">'
            'DEMO DATA: scored_rows.jsonl not found. Run Phase 3 and Phase 4 to replace with real data.'
            '</div>'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>LLM Brand Presence Dashboard — {html_escape(target_name)}</title>
<style>
{CSS}
</style>
</head>
<body>
<div class="app">

  <div class="app-header">
    <div class="app-title">LLM BRAND PRESENCE DASHBOARD</div>
    <div class="app-subtitle">Tracking brand visibility across generative AI providers for {html_escape(target_name)} -- Generated: {today_label}</div>
    <div class="tabs">
      <div class="tab active" data-tab="overview">Overview</div>
      <div class="tab" data-tab="category">By Category</div>
      <div class="tab" data-tab="keyword">By Keyword</div>
    </div>
  </div>

  <!-- TAB 1: OVERVIEW -->
  <div class="tab-content active" id="tab-overview">
    {demo_banner}
    {single_run_note}
    {fb_overview}

    <div class="top-row-3">
      <div class="panel">
        <div class="panel-title">Query Category Distribution</div>
        {funnel_html}
      </div>
      <div class="panel">
        <div class="panel-title">Engines This Run</div>
        {engine_panel_html}
      </div>
      <div class="panel">
        <div class="panel-title">Share of Voice</div>
        <div class="donut-wrap">
          <div id="donut-sov"></div>
          {sov_legend}
        </div>
      </div>
    </div>

    <div class="three-col">
      {ranking_all}
      {ranking_e1}
      {ranking_e2}
    </div>

    <div class="panel" style="margin-bottom:14px;">
      <div class="panel-title">Discovery Role -- {html_escape(target_name)}</div>
      <div class="donut-wrap">
        <div id="donut-discovery"></div>
        {disc_legend}
      </div>
    </div>

    <div class="panel" style="margin-bottom:14px;">
      <div class="panel-title">{ov_chart_title}</div>
      {legend_html}
      <div id="chart-overview" class="chart-container"></div>
    </div>

    {heatmap_overview}

    {footer_html(target_name, is_demo)}
  </div>

  <!-- TAB 2: BY CATEGORY -->
  <div class="tab-content" id="tab-category">
    {demo_banner}
    {fb_category}

    <div class="three-col">
      {ranking_cat_all}
      {ranking_cat_e1}
      {ranking_cat_e2}
    </div>

    <div class="panel" style="margin-bottom:14px;">
      <div class="panel-title">Query-level Analysis: % Presence within {html_escape(default_cat)}</div>
      {kw_bars_html}
    </div>

    <div class="panel" style="margin-bottom:14px;">
      <div class="panel-title">% Presence per Category -- {html_escape(target_name)}</div>
      <div class="donut-wrap">
        <div id="donut-category"></div>
        {cat_donut_legend}
      </div>
    </div>

    <div class="panel" style="margin-bottom:14px;">
      <div class="panel-title">{cat_chart_title}</div>
      {legend_html}
      <div id="chart-category" class="chart-container"></div>
    </div>

    {heatmap_category}

    {footer_html(target_name, is_demo)}
  </div>

  <!-- TAB 3: BY KEYWORD -->
  <div class="tab-content" id="tab-keyword">
    {demo_banner}
    {fb_keyword}

    <div class="three-col">
      {ranking_kw_all}
      {ranking_kw_e1}
      {ranking_kw_e2}
    </div>

    <div class="panel" style="margin-bottom:14px;">
      <div class="panel-title">{kw_chart_title_prefix}{dq_text})</div>
      {legend_html}
      <div id="chart-keyword" class="chart-container"></div>
    </div>

    {heatmap_keyword}

    {footer_html(target_name, is_demo)}
  </div>

</div>

<script>
  // ============ TAB SWITCHING ============
  const tabs     = document.querySelectorAll('.tab');
  const contents = document.querySelectorAll('.tab-content');
  tabs.forEach(function(tab) {{
    tab.addEventListener('click', function() {{
      tabs.forEach(function(t)     {{ t.classList.remove('active'); }});
      contents.forEach(function(c) {{ c.classList.remove('active'); }});
      tab.classList.add('active');
      document.getElementById('tab-' + tab.getAttribute('data-tab')).classList.add('active');
    }});
  }});

{JS_RENDER_CHART}
{JS_RENDER_DONUT}

  // ============ DATA ============
  const overviewDates       = {json.dumps(ov_dates)};
  const overviewDatesIso    = {json.dumps(ov_dates_iso)};
  const overviewSeries      = {json.dumps(ov_series)};
  const overviewAnnotations = {json.dumps(annotations)};
  const keywordAnnotations  = {json.dumps(annotations)};

  const categoryDates    = {json.dumps(cat_dates)};
  const categoryDatesIso = {json.dumps(cat_dates_iso)};
  const categorySeries   = {json.dumps(cat_series)};

  const keywordDates    = {json.dumps(kw_dates)};
  const keywordDatesIso = {json.dumps(kw_dates_iso)};
  const keywordSeries   = {json.dumps(kw_series)};

  const sovSegments       = {json.dumps(sov_segments)};
  const discoverySegments = {json.dumps(discovery_segments)};
  const catDonutSegments  = {json.dumps(cat_donut_segments)};

  // ============ RENDER ============
  renderChart('chart-overview', overviewDates, overviewSeries, {{
    yMax: {round(ov_ymax, 1)},
    height: 560,
    padT: 170,
    padR: 90,
    annotations: overviewAnnotations,
    datesIso: overviewDatesIso,
    initialMode: {"'bar'" if single_run_mode else "'line'"}
  }});

  renderChart('chart-category', categoryDates, categorySeries, {{
    yMax: {round(cat_ymax, 1)},
    height: 360,
    padR: 60,
    datesIso: categoryDatesIso,
    initialMode: {"'bar'" if single_run_mode else "'line'"}
  }});

  renderChart('chart-keyword', keywordDates, keywordSeries, {{
    yMax: {round(kw_ymax, 1)},
    height: 440,
    padT: 170,
    padR: 60,
    annotations: keywordAnnotations,
    datesIso: keywordDatesIso,
    initialMode: {"'bar'" if single_run_mode else "'line'"}
  }});

  renderDonut('donut-sov',       sovSegments,       {{ size: 160, innerRadius: 0.6, centerLabel: 'SOV' }});
  renderDonut('donut-discovery', discoverySegments, {{ size: 160, innerRadius: 0.6, centerLabel: 'Role' }});
  renderDonut('donut-category',  catDonutSegments,  {{ size: 160, innerRadius: 0.6, centerLabel: 'Cat.' }});
</script>
</body>
</html>"""

    return html


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    _configure_logging(args.verbose, args.log_format)

    # Load brand profile
    if not Path(args.brand_profile).exists():
        logger.error("brand_profile.json not found at %s", args.brand_profile)
        sys.exit(1)
    brand_profile = load_json(args.brand_profile)

    # Load queries
    if not Path(args.queries).exists():
        logger.error("queries.json not found at %s", args.queries)
        sys.exit(1)
    queries_data = load_json(args.queries)

    # Build brand map
    target_name, all_brands, colors, is_target = build_brand_map(brand_profile)

    # Load or generate scored rows
    is_demo = False
    scored_path = Path(args.scored)
    if scored_path.exists():
        rows = load_scored_rows(str(scored_path), all_brands, is_target)
        logger.info("Loaded %d rows from %s", len(rows), scored_path)
    else:
        logger.warning("scored_rows.jsonl not found at %s, using demo data for preview", scored_path)
        # Replace real brand names with generic placeholders for demo mode
        n_comps = len(all_brands) - 1
        demo_target = "main_brand"
        demo_competitors = [f"comp_brand_{i+1}" for i in range(n_comps)]
        demo_all_brands = [demo_target] + demo_competitors
        demo_colors = {demo_target: TARGET_COLOR}
        for i, comp in enumerate(demo_competitors):
            demo_colors[comp] = COMP_COLORS[i % len(COMP_COLORS)]
        def demo_is_target(name_str):
            return name_str.lower() == demo_target.lower()
        # Remap real brand names in generated rows to generic names
        brand_remap = {b.lower(): demo_all_brands[i] for i, b in enumerate(all_brands)}
        rows_real = generate_demo_rows(brand_profile, queries_data, all_brands, is_target)
        rows = []
        for r in rows_real:
            new_r = dict(r)
            remapped_mentioned = {
                brand_remap.get(b.lower(), b) for b in r.get("mentioned", set())
            }
            new_r["mentioned"] = remapped_mentioned
            new_r["brands_mentioned_list"] = sorted(remapped_mentioned)
            new_r["mention_counts"] = {brand: 1.0 for brand in remapped_mentioned}
            rows.append(new_r)
        target_name = demo_target
        all_brands = demo_all_brands
        colors = demo_colors
        is_target = demo_is_target
        is_demo = True
        logger.info("Generated %d demo rows.", len(rows))

    # Load historical runs for time-series
    runs = load_historical_runs(args.runs_dir, all_brands, is_target)
    if runs:
        logger.info("Loaded %d historical run(s) from %s", len(runs), args.runs_dir)

    # In demo mode: inject synthetic historical runs and strategy events
    if is_demo and not runs:
        runs = generate_demo_runs(all_brands, queries_data)
        logger.info("Generated %d demo historical run(s) for time-series.", len(runs))

    # Load strategy events (optional). Accept both shapes:
    #   1. Legacy: a JSON array of events
    #   2. Wrapped: {"_schema_version": "...", "events": [...]}
    strategy_events = None
    ev_path = Path(args.strategy_events)
    if ev_path.exists():
        try:
            data = load_json(str(ev_path))
            if isinstance(data, dict) and "events" in data:
                strategy_events = data["events"]
                schema = data.get("_schema_version", "unknown")
                logger.info("Loaded %d strategy event(s) [schema %s].", len(strategy_events), schema)
            elif isinstance(data, list):
                strategy_events = data
                logger.info("Loaded %d strategy event(s) [legacy format].", len(strategy_events))
            else:
                logger.warning("strategy_events.json has unexpected shape; ignoring.")
        except Exception as e:
            logger.warning("Could not load strategy_events.json: %s", e)

    # In demo mode: inject demo strategy events if none provided
    if is_demo and strategy_events is None:
        strategy_events = DEMO_STRATEGY_EVENTS
        logger.info("Using %d demo strategy events.", len(strategy_events))

    today_label = date.today().strftime("%b %-d'%y") if sys.platform != "win32" else date.today().strftime("%b %d'%y").lstrip("0")
    today_iso = date.today().isoformat()

    # Build HTML
    html = build_html(
        rows=rows,
        all_brands=all_brands,
        target_name=target_name,
        colors=colors,
        queries_data=queries_data,
        runs=runs,
        strategy_events=strategy_events,
        is_demo=is_demo,
        today_label=today_label,
        today_iso=today_iso,
    )

    # Write output
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    size_kb = out_path.stat().st_size / 1024
    logger.info("Dashboard written to: %s (%.1f KB)", out_path, size_kb)


if __name__ == "__main__":
    main()
