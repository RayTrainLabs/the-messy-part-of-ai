# Phase 5, Gap analysis & optimization

**Goal:** for every scored row, identify the **specific content gap** between the target brand and competitors, generate a **concrete SEO + AEO action**, and assign a **priority + expected impact**. Write `output/gap_rows.jsonl` and produce the row-level + aggregate fields the final scorecard needs.

The full rubric (gap taxonomy, recommendation framework, prioritization rules) lives in [`../references/gap-analysis-rubric.md`](../references/gap-analysis-rubric.md). This phase doc is the **operational** runbook.

## Fields produced per row

| Field | Type | Notes |
|---|---|---|
| `content_gap` | string | One-line summary of the primary gap (concatenated from gap_type + competitor_advantage). Full structured gap data goes to `_gap_details`. |
| `optimization_action` | string | The single primary recommended action, e.g., "Build comparison page: Acme vs Sprig vs Pendo" |
| `optimization_rationale` | string (2 to 3 sentences) | Why this action addresses the gap and beats the competitive landscape |
| `optimization_priority` | enum: Critical / High / Medium / Low | Per the priority rules in the rubric |
| `optimization_expected_impact` | string | Short / medium / long-term projections, one sentence each, semicolon-separated |
| `overall_visibility_assessment` | enum: Excellent / Good / Moderate / Weak / Not visible | **Per row**, based on this row's metrics |
| `key_insights` | string[] (exactly 3) | Per-row insights, current visibility, competitive landscape, single most important action |
| `_gap_details` | object | Full structured gap list (gap_type, severity, description, competitor_advantage), kept in JSONL for the PDF report; not exposed as a top-level scorecard column |

The aggregate (whole-audit) version of `overall_visibility_assessment` and `key_insights` is computed in Phase 6 from the row-level versions; both are kept so the PDF can show per-engine + overall.

## Steps

1. **Confirm prerequisites:**
 - `output/scored_rows.jsonl` exists, validated, spot-checked
 - `output/raw_responses.jsonl` is still on disk (the gap analyzer reads both: scored row gives the metrics, raw row gives the actual text/citations to ground the gap claim)

2. **Run the gap analyzer:**
 ```bash
 python scripts/analyze_response.py \
 --responses output/raw_responses.jsonl \
 --scored output/scored_rows.jsonl \
 --brand-profile output/brand_profile.json \
 --judge-provider anthropic \
 --judge-model claude-opus-4-7 \
 --mode gaps \
 --concurrency 6 \
 --out output/gap_rows.jsonl
 ```
 The script:
 - Joins scored row + raw row by `row_id`
 - Runs the prompt in [`../templates/gap_optimization_system_prompt.md`](../templates/gap_optimization_system_prompt.md)
 - Enforces: at least one gap per row (a "maintain current strategy" gap is acceptable for dominant rows); every gap has a corresponding optimization recommendation; recommendations include both SEO and AEO tactics; `key_insights` has exactly 3 items
 - If `target_brand_mentioned == false`, asserts that **Total Visibility Gap** is the first gap listed
 - Writes one row to `output/gap_rows.jsonl`

3. **Spot-check 5 rows** spanning the priority spectrum:
 - 1 Critical (brand absent on a high-intent decision query)
 - 1 High (brand present but losing on authority)
 - 1 Medium (brand mid-pack)
 - 1 Low (brand dominates the row)
 - 1 random

 For each, ask: does the recommended action sound like something the brand could actually ship in a quarter? Are the SEO + AEO tactics specific (named deliverables) or vague?

 If recommendations are vague ("create more content"), tighten the prompt with a counter-example and re-run.

4. **Cross-row deduplication pass.** Many rows will recommend the same underlying action (e.g., "build a comparison page vs Pendo" might appear for 8 different decision-stage queries). The compiler in Phase 6 will deduplicate at the top-level action plan, but make sure each row's `optimization_action` is **scoped to that row's specific gap**, not a generic plan-level action.

## Output contract

`output/gap_rows.jsonl`, one row per (query × engine) with the 7 fields above plus `row_id` and `_gap_details`.

## Priority rules (enforced by the validator)

```
target_brand NOT mentioned → Critical
share_of_voice < 5% AND positional_authority < 30 → Critical
significant authority gap (top competitor +30 vs target) → High
moderate gaps → Medium
target dominates row (Leader/Primary) → Low (still produce a "maintain" recommendation)
```

## Why per-row recommendations, not just aggregate?

- The **aggregate** action plan goes in the PDF executive summary
- The **per-row** recommendations let the user filter the scorecard ("show me every Critical row in category C, Decision queries, and tell me what to ship") and understand exactly which queries each recommended action would help with
- Without per-row actions, the user cannot trace any aggregate recommendation back to evidence ("why does the report say I need a comparison page?" → "because these 8 queries all surfaced competitors with comparison content while you have none")

## Common pitfalls

- **Generic recommendations.** "Improve your content marketing" is not a recommendation. Every action must name a deliverable (page, schema type, comparison target, FAQ block, etc.).
- **Recommendations that ignore the gap type.** A row with a Citation Gap calls for citation-targeted content, not a redesign of the homepage.
- **Recommending against the brand's own positioning.** Phase 0/1 captured ICP and positioning; the gap analyzer should respect them. Don't recommend going after enterprise queries if the brand is explicitly SMB-focused.
- **Recommending pure SEO when the gap is AEO.** AI engines reward different signals than Google does (citable statistics, direct-answer paragraphs, structured comparisons, llms.txt). The rubric requires both SEO and AEO tactics per recommendation.

## References

- [`../references/gap-analysis-rubric.md`](../references/gap-analysis-rubric.md), full gap taxonomy + optimization framework
- [`../templates/gap_optimization_system_prompt.md`](../templates/gap_optimization_system_prompt.md), system prompt loaded by the gap analyzer
