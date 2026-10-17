# Output schema, `aeo_scorecard.csv` / `.xlsx`

The exact 20-column schema for the per-row scorecard. Phase 6 validates every joined record against this schema before writing.

## Columns (in order)

| # | Column | Type | Source phase | Constraints |
|---|---|---|---|---|
| 1 | `query_tested` | string | Phase 2/3 | non-empty |
| 2 | `response_summary` | string | Phase 4 | 2 to 3 sentences, 50 to 600 chars |
| 3 | `brand_mentioned` | bool | Phase 4 | true / false |
| 4 | `brands_mentioned_list` | string | Phase 4 | comma-separated, sorted alphabetically |
| 5 | `citation_frequency_score` | int | Phase 4 | 0 to 100 |
| 6 | `share_of_voice_percentage` | float | Phase 4 | 0.0 to 100.0 |
| 7 | `positional_authority_score` | int | Phase 4 | 0 to 100 |
| 8 | `sentiment_direction_score` | int | Phase 4 | -50 to +50 |
| 9 | `response_relevance_score` | int | Phase 4 | 0 to 100 |
| 10 | `market_position_type` | enum | Phase 4 | Leader / Challenger / Alternative / Niche / Not competitive / Not mentioned |
| 11 | `discovery_role` | enum | Phase 4 | Primary / Secondary / Fallback / Avoided / Absent |
| 12 | `positioning_narrative` | string | Phase 4 | 150 to 250 chars |
| 13 | `strength_score` | int | Phase 4 | 0 to 10 |
| 14 | `content_gap` | string | Phase 5 | non-empty |
| 15 | `optimization_action` | string | Phase 5 | non-empty, names a concrete deliverable |
| 16 | `optimization_rationale` | string | Phase 5 | 2 to 3 sentences |
| 17 | `optimization_priority` | enum | Phase 5 | Critical / High / Medium / Low |
| 18 | `optimization_expected_impact` | string | Phase 5 | three timeframes, semicolon-separated |
| 19 | `overall_visibility_assessment` | enum | Phase 5 | Excellent / Good / Moderate / Weak / Not visible |
| 20 | `key_insights` | string | Phase 5 | three insights, ` | ` (pipe-with-spaces) separated |

The CSV/XLSX exposes exactly these 20 columns. The JSONL files (`scored_rows.jsonl`, `gap_rows.jsonl`) carry additional internal fields (`row_id`, `query_id`, `engine`, `_brand_mention_counts`, `_gap_details`, `_judge`) used by the PDF report and audit trail.

## Auxiliary columns added in the XLSX (for filtering only, not in CSV)

| Column | Source | Why |
|---|---|---|
| `engine` | Phase 3 | filter by serp_google / llm_openai / llm_anthropic / llm_perplexity / llm_gemini |
| `query_id` | Phase 2 | jump back to the original query record |
| `query_category` | Phase 2 | filter by A to I |

These are added as the **first three columns** of the XLSX (so the CSV's column 1, `query_tested`, becomes column 4 in the XLSX). The CSV stays clean (just the 20 columns).

## Conditional formatting (XLSX only)

| Column | Rule |
|---|---|
| `share_of_voice_percentage` | Data bar, 0 to 100, blue gradient |
| `positional_authority_score` | 3-color scale (red 0 → yellow 50 → green 100) |
| `sentiment_direction_score` | 3-color scale (red -50 → white 0 → green +50) |
| `response_relevance_score` | 3-color scale (red 0 → yellow 50 → green 100) |
| `strength_score` | Data bar, 0 to 10, green gradient |
| `market_position_type` | Categorical color (Leader green, Challenger light green, Alternative yellow, Niche orange, Not competitive light red, Not mentioned red) |
| `optimization_priority` | Categorical color (Critical red, High orange, Medium yellow, Low gray) |
| `overall_visibility_assessment` | Categorical color (Excellent green, Good light green, Moderate yellow, Weak orange, Not visible red) |

Header row frozen; all columns autosized to content.

## Validation

`scripts/compile_sheet.py` validates each joined record before writing:

- Every column present
- Type matches
- Numeric ranges respected
- Enums match the allowed value lists exactly (case-sensitive)
- `brands_mentioned_list` is sorted, deduplicated, comma-separated
- `key_insights` has exactly 3 items split on ` | `
- `optimization_expected_impact` parses to 3 timeframe segments

Any failing record is logged with the offending field and excluded from the CSV/XLSX (with a note in the PDF methodology section). The skill **never** silently substitutes default values.

## Aggregate `overall_visibility_assessment` (PDF report only)

The per-row column #19 is row-scoped. The PDF executive summary also shows an **aggregate** overall assessment derived from the average `strength_score` across all rows, using the same brackets as the per-row rubric in `metrics-rubric.md`:

| Avg strength | Aggregate label |
|---|---|
| ≥ 8 | Excellent |
| ≥ 6 | Good |
| ≥ 3 | Moderate |
| ≥ 1 | Weak |
| 0 | Not visible |

Computed in `scripts/render_pdf_report.py:aggregate()`. The CSV/XLSX never carries this aggregate, it is purely a report-level summary.

## Why these 20 columns and not more

The user's brief specified exactly these columns. Internal metadata that the PDF report needs (engine, gap details, brand mention counts) is preserved in the JSONL files and read by the renderer; it does not pollute the scorecard the user asked for.
