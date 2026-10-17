---
name: aeo-content-attribution
description: Attribute content interventions (LLMs.txt, schema, FAQ, advertorial, blog) to brand visibility changes in AEO/LLM responses. Reads a Google Sheet (or local CSV) content planner, joins it against historical AEO scored runs, computes cluster-level and brand-wide lift, and emits a strategy-events JSON the AEO dashboard renders as labeled callouts on the % presence chart. Use when the user asks "did our content move the needle in LLM answers", "attribute content to AEO visibility", or "show which interventions caused the lift".
---

# AEO-04: Content Attribution

## What this skill does

Joins a **content planner** (publish dates, content type, target query cluster) against **historical AEO scored runs** (per-date brand presence) and produces:

1. `attributions.json`, per-content-piece attribution with status, lift, and confidence
2. `strategy_events.json`, annotations in the schema `render_dashboard.py` expects
3. Annotated AEO dashboard rendered with both the `% Presence Over Time` chart and labeled callouts pinning impl. + attr. dates

## Inputs

### Content planner (Google Sheet OR local CSV)

Required columns (header names exact match):

| Column | Type | Example |
|---|---|---|
| Publish Date | YYYY-MM-DD | 2026-05-01 |
| Content Type | string | LLMs.txt, Schema, FAQ, Advertorial, Blog, Press |
| Title / URL | string | https://example.com/llms.txt |
| Target Query or Cluster | string (comma-separated keywords) | organic whey protein, whey isolate Germany |
| Expected Attribution Lag (days) | int | 14 |
| Status | string | live, planned, paused |

Only rows with `Status = live` participate in attribution. `planned` rows are rendered as faint forward-looking pins (no attr. date).

### AEO run history

A directory containing one or more `scored_rows.jsonl` files, each named or foldered by date:

```
runs/
  2025-06-02/scored_rows.jsonl
  2025-06-16/scored_rows.jsonl
  ...
  2026-05-06/scored_rows.jsonl
```

Each scored row must include: `query_id`, `query_tested`, `brands_mentioned_list`.

### Brand profile

Standard `brand_profile.json` from AEO-01 (target brand name + competitors).

## Attribution model

Three signals computed for each `live` content row:

1. **Cluster lift**: target brand presence delta in queries matching `Target Query or Cluster`, from `publish_date` to `publish_date + lag`. Matching is case-insensitive substring against `query_tested`.
2. **Overall lift**: target brand presence delta brand-wide over the same window.
3. **Breakout**: any single-period overall jump > 3pp gets a `⚡ BREAKOUT X%` badge anchored to the attribution date.

Attribution status per row:

| Status | Condition |
|---|---|
| `strong` | cluster_lift > overall_lift + 2pp |
| `moderate` | cluster_lift > overall_lift (positive) |
| `weak` | cluster_lift positive but ≤ overall_lift |
| `none` | cluster_lift ≤ 0 |

### Same-date tie-breaker

When two `live` rows share a publish date, primary attribution goes to the row with the higher cluster_lift. The losing row is marked `contributing` (shown faintly). This is the closest proxy to "which intervention was cited as a source" given AEO-01 currently does not capture per-response cited URLs.

## Outputs

```
output/{brand_slug}/
  attributions.json         # per-row attribution detail
  strategy_events.json      # annotations consumed by render_dashboard.py
  attribution_report.html   # standalone narrative report
```

## Run

```bash
# Local CSV mode (simplest, used by sample/demo runs)
python3 "AEO skills/04-aeo-content-attribution/scripts/attribute_content.py" \
  --content-planner "AEO skills/04-aeo-content-attribution/examples/sample_content_planner.csv" \
  --runs-dir "AEO skills/04-aeo-content-attribution/examples/sample_runs" \
  --brand-profile "AEO skills/04-aeo-content-attribution/examples/sample_brand_profile.json" \
  --output-dir "AEO skills/04-aeo-content-attribution/output/sample"

# Google Sheet mode
python3 "AEO skills/04-aeo-content-attribution/scripts/attribute_content.py" \
  --sheet-id 1AbCdEfGhIjKlMnOpQrStUvWxYz \
  --sheet-tab "Table1" \
  --service-account-json /path/to/service-account.json \
  --runs-dir "AEO skills/01-aeo-brand-visibility-analysis/runs" \
  --brand-profile "AEO skills/01-aeo-brand-visibility-analysis/output/gymshark/brand_profile.json" \
  --output-dir "AEO skills/04-aeo-content-attribution/output/gymshark"
```

Then render the dashboard with annotations:

```bash
python3 "AEO skills/01-aeo-brand-visibility-analysis/scripts/render_dashboard.py" \
  --rows "AEO skills/01-aeo-brand-visibility-analysis/output/gymshark/scored_rows.jsonl" \
  --queries "AEO skills/01-aeo-brand-visibility-analysis/output/gymshark/queries.json" \
  --brand-profile "AEO skills/01-aeo-brand-visibility-analysis/output/gymshark/brand_profile.json" \
  --strategy-events "AEO skills/04-aeo-content-attribution/output/gymshark/strategy_events.json" \
  --output "company docs/Gymshark/Gymshark_aeo_dashboard.html"
```

## Color scheme

| Content Type | Hex | Reason |
|---|---|---|
| LLMs.txt | `#7ba05b` | light green (technical/structural) |
| Schema | `#386641` | dark green (technical/structural) |
| FAQ | `#2d6a4f` | teal-green (on-site optimization) |
| Advertorial | `#8b6f47` | tan/brown (external earned media) |
| Blog | `#a04545` | red-brown (owned content) |
| Press | `#9c6644` | darker brown (earned PR) |
| Breakout badge | `#2d6a4f` with ⚡ | bright marker |

## Limits

- Only handles cluster-level lift. URL-level citation tracking would require extending AEO-01 to capture cited sources per LLM response.
- Requires ≥ 2 historical AEO runs to compute any delta. Single-run mode disables attribution and emits an empty `strategy_events.json`.
- Cluster matching is substring-based, case-insensitive. Synonyms/aliases not handled, extend with an alias map if needed.
