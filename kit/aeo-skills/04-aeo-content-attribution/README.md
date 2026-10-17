# AEO-04 Content Attribution

Attribute content interventions (LLMs.txt, schema, FAQ, advertorial, blog, press) to brand visibility changes in AEO/LLM responses. The skill joins a content planner against historical AEO scored runs, computes cluster-level and brand-wide lift, checks for direct URL citations, and emits a strategy-events file that the AEO-01 dashboard renders as labeled callouts on the % Presence Over Time chart.

## What this skill does

Reads a content planner (Google Sheet or CSV) and a directory of dated `scored_rows.jsonl` files from AEO-01. For every `live` planner row it compares brand presence in the matched query cluster before and after the publish date, looks for direct citations of the content URL inside the attribution window, classifies the result, and emits per-row attribution records plus dashboard annotations. Output drops straight into AEO-01's `render_dashboard.py`.

## When to use it

- "Did our content move the needle in LLM answers."
- "Attribute our last quarter of content publishing to AEO visibility."
- "Show which interventions caused the lift on the dashboard."

## Inputs

### Content planner (Google Sheet or CSV)

Headers are resolved case-insensitively against `PLANNER_SCHEMA` in `attribute_content.py`. The canonical header plus accepted aliases:

| Field | Canonical header | Accepted aliases | Type | Example |
|---|---|---|---|---|
| publish_date | `Publish Date` | `publish_date`, `publish date` | YYYY-MM-DD | `2026-05-01` |
| content_type | `Content Type` | `content_type`, `type` | string | `LLMs.txt`, `Schema`, `FAQ`, `Advertorial`, `Blog`, `Press` |
| title_url | `Title / URL` | `Title/URL`, `title`, `url` | string | `https://example.com/llms.txt` |
| target_cluster | `Target Query or Cluster` | `target_cluster`, `cluster` | comma-separated keywords | `organic whey protein, whey isolate Germany` |
| lag_days | `Expected Attribution Lag (days)` | `lag`, `lag_days` | int | `14` |
| status | `Status` | `status` | `live`, `planned`, `paused` | `live` |

Only `status = live` rows participate in attribution. Unparseable `Publish Date` values trigger a warning and the row is dropped. Unknown content types are accepted but render in the default grey `#6b7280`.

### AEO run history

A directory whose children are either:

- `runs/YYYY-MM-DD/scored_rows.jsonl`, or
- `runs/YYYY-MM-DD_scored_rows.jsonl`

Each scored row must include `query_id`, `query_tested`, and `brands_mentioned_list`. An optional `cited_urls` array (populated by `AEO skills/01-aeo-brand-visibility-analysis/scripts/extract_citations.py`) unlocks citation-level attribution. Without `cited_urls`, attribution falls back to cluster and brand-wide lift only.

### Brand profile

The standard AEO-01 `brand_profile.json`. The script reads `brand_name`, `brand`, `name`, or `target_brand` (first match wins) and exits with an error if none is present.

## Outputs

Written to `output-dir/`. Both JSON files are wrapped with a schema version and generation timestamp. The renderer accepts both wrapped and legacy (top-level list) formats; `render_dashboard.py` falls back to legacy when the wrapper is absent.

### `attributions.json`

Per-content-piece detail. One record per `live` planner row.

```json
{
  "_schema_version": "1.1",
  "_generated_at": "2026-05-13T22:00:00.000000Z",
  "target_brand": "Gymshark",
  "attributions": [
    {
      "publish_date": "2025-09-08",
      "attr_date": "2025-09-22",
      "content_type": "FAQ",
      "title_url": "https://www.gymshark.com/pages/leggings-guide",
      "target_cluster": "best leggings for squats, leggings opacity, high waisted leggings",
      "lag_days": 14,
      "status": "cited",
      "cluster_lift_pp": 6.25,
      "weighted_lift_pp": 5.81,
      "overall_lift_pp": 2.10,
      "citation_count": 4,
      "claimed_queries": ["best leggings for squats", "high waisted leggings opacity test"],
      "baseline_run_date": "2025-09-08",
      "attr_run_date": "2025-09-22",
      "primary": true
    }
  ],
  "breakouts": [
    {"date": "2025-10-06", "delta_pp": 4.2, "presence": 38.6}
  ]
}
```

Field notes:

- `cluster_lift_pp`: unweighted lift over the piece's claimed queries (binary cluster filter).
- `weighted_lift_pp`: lift weighted by per-query match strength. More accurate than `cluster_lift_pp` when a planner row's cluster has multiple keywords with varying overlap to AEO queries.
- `claimed_queries`: the queries this piece "claimed" via the highest `cluster_score` tiebreaker (see Attribution model). Used to prevent double-counting when two pieces target overlapping clusters in the same publish window.

### `strategy_events.json`

Annotations consumed by `render_dashboard.py --strategy-events`. Two events per primary attribution (`impl.` and `attr.`, paired by `pair_id`), one `impl.` event per non-primary contributing row, and one breakout event per detected jump.

```json
{
  "_schema_version": "1.1",
  "_generated_at": "2026-05-13T22:00:00.000000Z",
  "events": [
    {"date": "Sep 8'25",  "iso_date": "2025-09-08", "label": "impl.",       "color": "#2d6a4f", "row": 2, "type": "FAQ",      "kind": "impl", "pair_id": "p1"},
    {"date": "Sep 22'25", "iso_date": "2025-09-22", "label": "attr.",       "color": "#2d6a4f", "row": 2, "type": "FAQ",      "kind": "attr", "pair_id": "p1"},
    {"date": "Oct 6'25",  "iso_date": "2025-10-06", "label": "+4.2pp",      "color": "#2d6a4f", "row": 6, "type": "Breakout", "kind": "breakout"}
  ]
}
```

Each event carries both `date` (chart-label string like `Oct 20'25`) and `iso_date` (ISO 8601 `2025-10-20`). The renderer matches by `iso_date` first and falls back to `date` for legacy events.

### `summary.md`

Human-readable rollup. Top-line counts per status, breakout list, then one table per status group with publish date, attribution date, content type, truncated title, cluster delta, and brand-wide delta.

Note: SKILL.md mentions a standalone `attribution_report.html`. The current code does not emit it. The shipped artifacts are `attributions.json`, `strategy_events.json`, and `summary.md`.

## Attribution model

Four signals are computed per `live` row.

1. **Direct citation (strongest).** Counts rows in the attribution-window run where any `cited_urls` entry matches `title_url` (after normalization and regional-subdomain stripping). Requires `extract_citations.py` to have run.
2. **Cluster lift.** Target brand presence delta on queries matching the row's `Target Query or Cluster`, from `closest_run_date(publish_date)` to `closest_run_date(publish_date + lag_days)`. Match strength is computed by `cluster_score` (see below).
3. **Brand-wide lift.** Same window, all queries.
4. **Breakout.** Any consecutive run-to-run jump in brand-wide presence of at least `--breakout-threshold-pp` (default `3.0`) is emitted as a `+X.Xpp` badge anchored to the post-jump date.

### How `cluster_score` works

`cluster_score(cluster, query) -> [0.0, 1.0]` is a per-query match-strength score:

- **Full-term match -> 1.0.** If all tokens of any single cluster term are a subset of the query tokens.
- **Partial token overlap.** Best per-cluster-term proportion of tokens that overlap with the query.
- **Multi-token boost.** When a cluster term has `>= 2` tokens overlapping the query, the score is multiplied by `1.2` (capped at `1.0`).
- **Floor.** Any non-empty single-token overlap floors the score at `0.35` so partial matches stay comparable with the legacy binary cluster filter.
- Tokenization stems plural suffixes (`-ies`, `-es`, `-s`) and drops stopwords.

`weighted_presence_pct` uses these scores as weights: each row contributes its `cluster_score` to the denominator and `cluster_score * hit` to the numerator. `weighted_lift_pp` is the delta of weighted presence between baseline and attribution runs. It is more accurate than `cluster_lift_pp` when a cluster's keywords have uneven overlap with the AEO query set.

### Claim-based double-counting protection

When two or more `live` pieces in the same publish window have overlapping clusters, each unique query in the attribution window is **claimed** by the piece with the highest `cluster_score` for it (ties broken by piece order). A piece's `cluster_lift_pp` is computed only over its claimed queries; a piece that loses every tiebreaker has `cluster_lift_pp = 0` (not a phantom duplicate of another piece's lift). The claimed query list is surfaced as `claimed_queries` on each attribution record.

### Status hierarchy

| Status | Condition |
|---|---|
| `cited` | `citation_count > 0` (overrides everything below) |
| `strong` | `cluster_lift > overall_lift + --strong-lift-pp` (default 2.0) |
| `moderate` | `cluster_lift > overall_lift` and `cluster_lift > 0` |
| `weak` | `cluster_lift > 0` but `cluster_lift <= overall_lift` |
| `none` | `cluster_lift <= 0` |
| `insufficient_history` | fewer than 2 runs, or baseline and attribution snap to the same run date |

### Same-date tie-breaker

When two or more `live` rows share a publish date, primary attribution is awarded by sorting on `(STATUS_RANK, weighted_lift_pp, citation_count)` descending. Rank: `cited=4, strong=3, moderate=2, weak=1, none=0`. The first row with status in `{cited, strong, moderate}` becomes `primary = true`; the rest are recorded with their own status but rendered as contributing `impl.` markers only (no paired `attr.` event).

### When to trust each signal

- **Cited** is ground truth. If the LLM cited the URL, attribution is direct.
- **Strong/moderate cluster lift** is a reliable proxy when the AEO-01 query set actually covers the cluster. Run the coverage warning (printed automatically) before trusting any cluster-level result.
- **Brand-wide lift** is the weakest signal. Many things move brand-wide numbers. Use it only when cluster matching returns no queries.

## Setup

- Python `>=` 3.10.
- `pip install -r requirements.txt` (only needed for `--sheet-id` service-account mode and for running the tests; the default CSV and `--sheet-url` modes are stdlib-only).
- For `--sheet-url`: open the Google Sheet, set sharing to `Anyone with the link`, role `Viewer`. The script fetches the CSV export endpoint with a 15s timeout (override via `AEO_SHEET_TIMEOUT`) and three exponential-backoff retries.
- For `--sheet-id`: create a Google Cloud service account, download its JSON key, share the sheet with the service-account email, and pass the JSON via `--service-account-json`.

## Pipeline

The shipped orchestrator wires everything together. From the workshop root:

```bash
python3 "AEO skills/04-aeo-content-attribution/scripts/run_pipeline.py" \
  --runs-dir        "AEO skills/04-aeo-content-attribution/examples/gymshark/runs" \
  --queries         "AEO skills/01-aeo-brand-visibility-analysis/output/gymshark/queries.json" \
  --brand-profile   "AEO skills/01-aeo-brand-visibility-analysis/output/gymshark/brand_profile.json" \
  --content-planner "AEO skills/04-aeo-content-attribution/examples/gymshark/content_planner.csv" \
  --output-dir      "AEO skills/04-aeo-content-attribution/output/gymshark" \
  --dashboard-out   "company docs/Gymshark/Gymshark_aeo_dashboard.html"
```

What `run_pipeline.py` does internally:

1. **Input validation.** Confirms `--runs-dir` exists and contains at least 2 dated `YYYY-MM-DD` subdirs, that `--queries` and `--brand-profile` exist, and that exactly one of `--content-planner` or `--sheet-url` is supplied. Input failures exit with code `2`. Step failures (non-zero subprocess exit) exit with code `1`.
2. **Citation enrichment.** For each dated subdir with both `raw_responses.jsonl` and `scored_rows.jsonl`, runs `extract_citations.py --in-place` when `cited_urls` is not yet populated. Idempotent: skips subdirs already enriched.
3. **Attribution.** Invokes `attribute_content.py` with the runs dir, brand profile, planner source, and output dir.
4. **Dashboard render.** Invokes `render_dashboard.py` against the latest scored run and the freshly written `strategy_events.json`.

Flags:

- `--skip-citations`: skip step 2 (use when citations are already enriched or unavailable).
- `--skip-render`: skip step 4 (use when you only want JSON artifacts).
- `--verbose`: enable DEBUG logging for the orchestrator.

Running steps manually is still supported. Call `extract_citations.py`, `attribute_content.py`, and `render_dashboard.py` directly in that order.

## Configuration

CLI flags on `attribute_content.py`:

| Flag | Default | Effect |
|---|---|---|
| `--breakout-threshold-pp` | `3.0` | Period-over-period jump (pp) in brand-wide presence that emits a breakout event. |
| `--strong-lift-pp` | `2.0` | Cluster lift over brand-wide lift (pp) that earns `strong` status. |
| `--verbose`, `-v` | off | DEBUG-level logging. |

The orchestrator (`run_pipeline.py`) currently passes these through with their defaults; tune them by running `attribute_content.py` directly when you need non-default thresholds.

Env var `AEO_SHEET_TIMEOUT` (default `15`) overrides the Google Sheets CSV-export request timeout in seconds.

## Demo / quickstart

The repo ships a Gymshark example with a config-driven synthetic run history. From the workshop root:

```bash
# 1. Synthesize ~24 biweekly runs from the bundled config
python3 "AEO skills/04-aeo-content-attribution/scripts/generate_synth_runs.py" \
  --config  "AEO skills/04-aeo-content-attribution/examples/gymshark/synth_config.json" \
  --queries "AEO skills/01-aeo-brand-visibility-analysis/output/gymshark/queries.json" \
  --out-dir "AEO skills/04-aeo-content-attribution/examples/gymshark/runs"

# 2. Run the full pipeline (validate -> citations -> attribute -> render)
python3 "AEO skills/04-aeo-content-attribution/scripts/run_pipeline.py" \
  --runs-dir        "AEO skills/04-aeo-content-attribution/examples/gymshark/runs" \
  --queries         "AEO skills/01-aeo-brand-visibility-analysis/output/gymshark/queries.json" \
  --brand-profile   "AEO skills/01-aeo-brand-visibility-analysis/output/gymshark/brand_profile.json" \
  --content-planner "AEO skills/04-aeo-content-attribution/examples/gymshark/content_planner.csv" \
  --output-dir      "AEO skills/04-aeo-content-attribution/output/gymshark" \
  --dashboard-out   "company docs/Gymshark/Gymshark_aeo_dashboard.html"
```

Expected: step 1 prints one line per biweekly date with the realized target-presence percentage (rising from roughly 25% at `2025-06-02` to roughly 60% at `2026-04-20`). Step 2 logs validation, citation enrichment counts, attribution row/event counts, and the path to the rendered HTML dashboard. The dashboard's presence-over-time chart shows lane-stacked content callouts and a breakout marker on the largest jump.

## Configuration reference for `generate_synth_runs.py`

The synth config is brand-agnostic. Required keys: `target_brand`, `competitors`, `target_curve`, `start_date`, `engines`. Optional: `query_boosts`, `citation_pool`.

```json
{
  "target_brand": "Gymshark",
  "start_date": "2025-06-02",
  "engines": ["llm_openai", "llm_gemini", "llm_anthropic", "llm_perplexity"],
  "target_curve": [25, 26, 27, 28, 29, 30, 31, 32, 33, 35, 37, 40, 43, 46, 48, 51, 54, 56, 58, 59, 60, 60, 61, 61],
  "competitors": [
    {"name": "Lululemon", "baseline": 45, "drift": -0.20},
    {"name": "Nike",      "baseline": 42, "series": [42, 41, 40, 39, 38]}
  ],
  "query_boosts": {
    "Q03": [[8, 0.15]],
    "Q01": [[16, 0.10], [18, 0.10]]
  },
  "citation_pool": {
    "Q10": [["https://www.gymshark.com/llms.txt", 12]]
  }
}
```

Field meanings:

- `target_brand`: brand name to match against `brands_mentioned_list`.
- `start_date`: first run date (ISO). Subsequent runs are placed at 14-day intervals.
- `engines`: list of engine identifiers. One row per (query, engine) is written per run.
- `target_curve`: list of percentages, one per run date. The synthesizer draws a Bernoulli per (query, engine) at `curve[idx]/100 + query_boost(q, idx)`, capped at 0.95.
- `competitors`: list of `{name, baseline, drift?}` or `{name, baseline, series?}`. `drift` is per-period linear; `series` overrides with explicit percentages.
- `query_boosts`: per-`query_id` additive ramp. `[[start_idx, boost], ...]`. All entries with `idx >= start_idx` sum into the target probability.
- `citation_pool`: per-`query_id` URL availability. `[[url, available_from_idx], ...]`. When the target is mentioned and the citation is available, each URL has a 40% chance of being added to `cited_urls` (cap of 2 per row).

Validate the bundled config:

```bash
python3 -c "import json; json.load(open('AEO skills/04-aeo-content-attribution/examples/gymshark/synth_config.json'))"
```

## Production checklist

- Cadence: run AEO-01 biweekly (matches `generate_synth_runs.py`). Run AEO-04 attribution at the same cadence, or monthly if planner changes are infrequent.
- Query coverage matters. If more than 25% of `live` planner rows have clusters that match no tested query, the script prints a coverage warning. Either widen AEO-01's query set or accept brand-wide attribution for those rows.
- Citations need `extract_citations.py` to have run on each scored file. The orchestrator handles this automatically unless `--skip-citations` is passed. Without enrichment, `citation_count` is always 0 and no row will reach `cited` status.
- Storage estimate: roughly 200 KB per scored run. One year of biweekly runs is roughly 5 MB. `attributions.json` and `strategy_events.json` are tens of KB.

## Known limits

- Cluster matching is token-overlap with cheap suffix stemming (`-ies`, `-es`, `-s`) and the `cluster_score` heuristic. No semantic similarity, no synonym map. Extend `PLANNER_SCHEMA` or pre-normalize the cluster column if you need synonym handling.
- One primary winner per publish date. Non-primary rows from the same date render as contributing `impl.` markers in their content-type lane, but only one paired `impl.`/`attr.` pair is drawn per date.
- URL normalization is lexical. It strips protocol, `www.`, regional subdomain prefixes (`row.`, `us.`, `uk.`, `eu.`, `de.`, `fr.`, `au.`, `ca.`, `jp.`, `na.`), query strings, fragments, and trailing slashes. It does not follow redirects, resolve canonical URLs, or handle non-listed regional subdomains.
- Run history is loaded eagerly into memory. Lazy loading is not yet implemented, so very large run sets (multiple years of biweekly runs) may be slow to start.
- Single-run mode emits an empty `strategy_events.json` (every row classifies as `insufficient_history`).
- SKILL.md describes a `attribution_report.html` output. The current code does not emit it; attribution is rendered via AEO-01's `render_dashboard.py` instead.

## Testing & CI

The workshop root holds a `pyproject.toml` that configures pytest with `--import-mode=importlib` and a `testpaths` list covering every skill's `tests/` directory, so the suite can be run from the workshop root without manipulating `PYTHONPATH`.

```bash
# From the workshop root, run every test in the workshop
pytest

# Or scope to AEO-04 only
pytest "AEO skills/04-aeo-content-attribution/tests/"
```

Coverage includes URL normalization, regional-subdomain handling, `url_matches` exact/prefix/suffix logic, citation counting, planner-header resolution, status classification, tie-breaker ordering, breakout detection, query-coverage warning thresholds, strategy-event pairing, `cluster_score` math, weighted lift, claim-based double-counting protection, schema wrapper shape, and `extract_citations.py` regex coverage.

`.github/workflows/test.yml` runs the full pytest suite on every `push` and `pull_request` to `main`.

## License / attribution

Internal Raygency / Agentiwise tooling. Do not redistribute without permission.
