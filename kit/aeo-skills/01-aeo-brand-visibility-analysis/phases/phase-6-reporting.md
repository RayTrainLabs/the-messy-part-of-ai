# Phase 6, Reporting

**Goal:** compile the per-row scorecard (`output/scored_rows.jsonl` + `output/gap_rows.jsonl`) into:

1. `output/aeo_scorecard.csv`, the 20-column scorecard the user requested
2. `output/aeo_scorecard.xlsx`, same data, formatted (frozen header, color-coded priority/assessment columns, autosized columns)
3. `output/aeo_report.pdf`, executive report with charts, prioritization, what's good vs. what's bad, full action plan
4. `output/aeo_executive_summary.md`, 1-page markdown the user can paste into Slack / email

## Steps

1. **Compile the scorecard:**
 ```bash
 python scripts/compile_sheet.py \
 --scored output/scored_rows.jsonl \
 --gaps output/gap_rows.jsonl \
 --raw output/raw_responses.jsonl \
 --brand-profile output/brand_profile.json \
 --out-csv output/aeo_scorecard.csv \
 --out-xlsx output/aeo_scorecard.xlsx
 ```
 The script:
 - Joins scored + gaps by `row_id`
 - Validates the joined record against [`../references/output-schema.md`](../references/output-schema.md), every row must have all 20 columns, types must match, enums must be valid
 - Writes CSV (UTF-8, no index) and XLSX (with conditional formatting on `optimization_priority`, `overall_visibility_assessment`, `share_of_voice_percentage`, `strength_score`)

2. **Render the PDF:**
 ```bash
 python scripts/render_pdf_report.py \
 --xlsx output/aeo_scorecard.xlsx \
 --brand-profile output/brand_profile.json \
 --out output/aeo_report.pdf
 ```
 The PDF contains the sections listed below. Each chart is generated with matplotlib and embedded as a PNG; the layout uses ReportLab's Platypus flowables.

3. **Generate the executive summary:**
 The PDF renderer also writes `output/aeo_executive_summary.md` containing the same Section 1 of the PDF as plain markdown.

4. **Hand off to the user** in the chat reply with:
 - 5-line summary (status, share of voice, top threat, top action, output paths)
 - Direct paths to the four deliverables (CSV, XLSX, PDF, executive summary MD)

## PDF structure

### Section 1, Executive summary (page 1)
- Brand name, audit date, engines queried, query count
- **Headline metric**: overall visibility status (Excellent/Good/Moderate/Weak/Not visible) in big text + colored badge
- **Top 3 numbers**: aggregate share-of-voice %, mention rate %, average strength score
- **Top 3 actions**: deduplicated, sorted by aggregate priority
- **Top 3 risks**: deduplicated, framed as "if we do nothing"

### Section 2, Visibility at a glance (charts)
- **Chart A**: Share-of-voice donut (target brand vs. top 5 competitors, "Other" bucket)
- **Chart B**: Per-engine bar chart of mention rate (% of queries the brand showed up in, by engine)
- **Chart C**: Per-category heatmap (9 query categories × engines, cell color = share-of-voice in that intersection)
- **Chart D**: Strength-score distribution histogram across all rows
- **Chart E**: Sentiment direction box plot per engine

### Section 3, Competitive landscape
- Table: top 10 competitors by aggregate share-of-voice (across all rows), with their average positional authority and sentiment
- Identification of the **dominant competitor per query category** (which competitor wins each of the 9 categories)
- Brands mentioned but **not** previously known (i.e., new competitors surfaced by the audit)

### Section 4, What's good (keep doing)
- Categories / engines / specific query themes where the brand is performing well (Strength ≥ 7)
- Specific queries to use as social proof internally
- Existing content/pages that are clearly being cited (extracted from `citation_urls` where the brand's domain appears), implicit signal of what's working

### Section 5, What's bad (fix urgently)
- Critical-priority rows, sorted by query category importance
- Each line: query → engines that didn't mention us → top competitor that did → recommended action
- Total Visibility Gap rows (brand absent entirely) listed first

### Section 6, Action plan (deduplicated)
- All `optimization_action` values, deduplicated and clustered by gap type
- Each cluster gets:
 - Action name
 - Number of queries this action would help
 - SEO tactics (specific deliverables)
 - AEO tactics (specific deliverables)
 - Priority
 - Effort estimate (S / M / L, based on deliverable type)
 - Expected impact (short / medium / long-term)
- Sorted by priority × queries-affected

### Section 7, Methodology & engines
- List of every engine queried, success rate, web-search/grounding flag confirmation
- Query count, distribution across the 9 categories, brand-mention percentage in queries
- Judge model used for scoring + spot-check confirmation that scoring was reviewed
- Note: anything skipped (engines without keys, queries with all-engine failures, etc.)

### Section 8, Appendix
- Full per-row scorecard (all 20 columns), paginated, small font
- Pointer to `output/raw/` for the raw API payloads

## Color conventions in the XLSX and PDF

| Field | Value | Color |
|---|---|---|
| `overall_visibility_assessment` | Excellent | green |
| | Good | light green |
| | Moderate | yellow |
| | Weak | orange |
| | Not visible | red |
| `optimization_priority` | Critical | red |
| | High | orange |
| | Medium | yellow |
| | Low | gray |
| `share_of_voice_percentage` | data bar 0 to 100 | blue gradient |
| `strength_score` | data bar 0 to 10 | green gradient |
| `sentiment_direction_score` | divergent -50 / 0 / +50 | red ↔ green |

## Output contract

The skill exits Phase 6 having written:

```
output/
├── brand_profile.json
├── brand_profile.md
├── queries.json
├── raw_responses.jsonl
├── scored_rows.jsonl
├── gap_rows.jsonl
├── aeo_scorecard.csv
├── aeo_scorecard.xlsx
├── aeo_report.pdf
├── aeo_executive_summary.md
└── raw/
 └── Q01__llm_anthropic.json (one file per row)
 └── ...
```

The chat reply to the user is exactly 5 lines, plus the paths.

## Common pitfalls

- **Charts that don't legend.** Every chart caption explains what the axes / colors mean and what the takeaway is.
- **PDF is too long.** Cap at ~25 pages. Push the per-row appendix to a separate file if the row count blows up.
- **Mixing aggregate and per-row metrics.** The PDF is aggregate; the CSV/XLSX is per-row. Don't put per-row text into the PDF or aggregate prose into the CSV.
- **Missing "what's good" section.** Reports that only criticize get ignored; reports that name the wins build buy-in for the fixes.
