# Phase 3, Reporting

**Goal:** turn `output/recommendations.jsonl` into:

1. `output/aeo_content_recommendations.csv`, the flat per-recommendation roadmap (15 columns)
2. `output/aeo_content_recommendations.xlsx`, same data, formatted (frozen header, color-coded priority/action_type, autosized columns, conditional fills)
3. `output/aeo_content_roadmap.pdf`, executive content roadmap with charts, content-cluster opportunities, priority logic, what/why/how
4. `output/aeo_content_executive_summary.md`, one-page markdown for Slack / email

## Steps

1. **Compile the sheet:**
 ```bash
 python scripts/compile_recommendations_sheet.py \
 --recommendations output/recommendations.jsonl \
 --aeo-scorecard output/aeo_scorecard.csv \
 --pages-index output/website_pages/_index.json \
 --out-csv output/aeo_content_recommendations.csv \
 --out-xlsx output/aeo_content_recommendations.xlsx
 ```
 The script flattens the nested `recommendation` object into the flat CSV columns specified in [`../references/output-schema.md`](../references/output-schema.md), validates every row, and writes both files.

2. **Render the PDF:**
 ```bash
 python scripts/render_recommendations_pdf.py \
 --xlsx output/aeo_content_recommendations.xlsx \
 --recommendations output/recommendations.jsonl \
 --brand-profile output/brand_profile.json \
 --pages-index output/website_pages/_index.json \
 --aeo-scorecard output/aeo_scorecard.csv \
 --out output/aeo_content_roadmap.pdf
 ```

 Also writes `output/aeo_content_executive_summary.md`.

3. **Hand off** in the chat reply:
 ```
 AEO content roadmap ready.
 - 28 recommendations: 4 new_article · 9 section_addition · 12 minor_optimization · 3 maintain
 - Top-3 priorities: <action 1> · <action 2> · <action 3>
 - Largest content cluster: 6 queries → /pricing-comparison (proposed new article)
 - Files: output/aeo_content_recommendations.{csv,xlsx} · output/aeo_content_roadmap.pdf · output/aeo_content_executive_summary.md
 ```

## CSV / XLSX columns (flat)

The 15-column flat schema (matches the user-requested output, with the nested fields collapsed):

| # | Column | Source |
|---|---|---|
| 1 | `query` | recommendation row |
| 2 | `content_exists` | `content_status.exists` |
| 3 | `coverage_level` | `content_status.coverage_level` (comprehensive / partial / indirect / none) |
| 4 | `current_locations` | flattened `content_status.locations[]` as `URL § section \| URL § section` |
| 5 | `action_type` | `recommendation.action_type` |
| 6 | `target_page` | `recommendation.target_page` |
| 7 | `placement` | `recommendation.placement` (only meaningful for section_addition) |
| 8 | `changes` | `recommendation.changes` (multiline) |
| 9 | `seo_keywords` | `recommendation.seo_keywords` joined with `, ` |
| 10 | `article_outline` | flattened: `H: <heading>\n - <point>\n - <point>\n\nH: <heading>\n ...` |
| 11 | `internal_links` | `recommendation.internal_links` joined with `\n` |
| 12 | `external_links` | `recommendation.external_links` joined with `\n` |
| 13 | `expected_result` | `recommendation.expected_result` |
| 14 | `priority` | inherited from AEO scorecard (Critical / High / Medium / Low) |
| 15 | `effort` | derived (S / M / L) |

The XLSX adds three helper columns at the front (`query_id`, `query_category`, `gap_types`) for filtering, same convention as skill 01.

## PDF structure

### Section 1, Executive summary (page 1)
- Brand name, audit date, recommendation count
- **Action-type breakdown** (donut: new_article / section_addition / minor_optimization / maintain)
- **Top 5 actions** sorted by priority × queries-affected
- **Total estimated effort** (sum of S/M/L weights, e.g., "12 S + 9 M + 4 L ≈ 6 sprint-weeks")
- **Single most important recommendation** (highest priority, largest cluster)

### Section 2, Action-type breakdown (charts)
- **Chart A**: Action-type donut
- **Chart B**: Priority distribution bar (Critical / High / Medium / Low)
- **Chart C**: Effort distribution bar (S / M / L)
- **Chart D**: Coverage-level donut (comprehensive / partial / indirect / none), what state was the site in before recommendations

### Section 3, Content clusters (the big-leverage section)
A **content cluster** is a group of queries that all map to the same recommended `target_page`. These represent disproportionate leverage, one piece of content moves the needle on multiple visibility gaps.

- Table: clusters with ≥ 3 queries pointing to the same target_page, sorted by query count
- For each cluster: target_page, query count, total priority weight, action_type, effort

### Section 4, Priority backlog (the actionable list)
Sorted by `priority` (Critical → Low), then by cluster size:

| Rank | Priority | Action type | Target page | Why | Expected result |
|---|---|---|---|---|---|
| 1 | Critical | new_article | /guides/in-app-feedback-tool-buyers-guide | Closes 6 visibility gaps … | Acme begins surfacing … |
| 2 | High | section_addition | /features/in-app-surveys | Closes 3 gaps … | … |
| ... | | | | | |

### Section 5, What's good (don't break this)
Pages where the brand is already winning. These come from `maintain` rows + queries where the AEO scorecard already showed Leader/Primary status.

- Pages currently driving visibility (with citation count from AEO scorecard)
- Sections / patterns to **preserve** during any future site redesign

### Section 6, What's bad (the visibility holes)
Aggregate of all `coverage_level: none` queries plus `Critical`-priority recommendations. The "if we do nothing" picture.

### Section 7, Per-action-type playbooks
For each of the four action types, the PDF shows:

- **What** the action means (1-paragraph definition)
- **Why** it works for AEO (brief reference to the SEO/AEO best-practices doc)
- **How** to execute (concrete checklist a content writer can follow)
- **Effort range** (with example deliverables at each)

### Section 8, Methodology
- Pages scraped + scrape mode (Apify or local) + scrape success rate
- Queries processed (count + dedup ratio if `--per-row` was not used)
- Top-K relevance pre-filter parameters
- Judge model used + spot-check confirmation
- Anything skipped (queries that couldn't be analyzed, pages that failed validation, etc.)

### Section 9, Appendix: full per-recommendation table
Small-font, paginated dump of the 15-column scorecard for full traceability.

## Color conventions in the XLSX and PDF

| Field | Value | Color |
|---|---|---|
| `priority` | Critical | red |
| | High | orange |
| | Medium | yellow |
| | Low | gray |
| `action_type` | new_article | blue |
| | section_addition | teal |
| | minor_optimization | green |
| | maintain | gray |
| `coverage_level` | comprehensive | green |
| | partial | yellow |
| | indirect | orange |
| | none | red |
| `effort` | S | green |
| | M | yellow |
| | L | red |

## Common pitfalls

- **Treating the recommendation list as a literal sprint plan.** Many rows will share a target_page (cluster opportunity); ship the cluster, not 6 separate tickets.
- **Skipping `maintain` rows in the PDF.** They're the "don't break this" list, without them, a site redesign can accidentally regress winning pages.
- **Forgetting the AEO scorecard context.** The PDF's "why" column for each row pulls from the AEO scorecard's gap_types and competitor_advantage; if that wasn't loaded, the priority order looks arbitrary.
