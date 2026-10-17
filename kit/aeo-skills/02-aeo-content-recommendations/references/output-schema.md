# Output schema, recommendations

This skill produces two on-disk shapes: the **nested JSONL** that the LLM judge fills directly, and the **flat CSV/XLSX** the user takes to a content team.

## 1. Nested JSONL (`output/recommendations.jsonl`)

One JSON object per line. The `recommendation` block is the same shape regardless of `action_type`, fields that don't apply to a given action_type are `null` (not omitted).

```json
{
 "row_id": "Q07",
 "query": "What should a B2B SaaS product team look for when choosing an in-app feedback tool?",
 "query_category": "C",
 "aeo_signals": {
 "mention_rate": 0.4,
 "avg_sov": 18.2,
 "priority": "High",
 "gap_types": ["Authority Gap", "Citation Gap"],
 "top_competitors": ["Pendo", "Sprig"]
 },
 "content_status": {
 "exists": true,
 "coverage_level": "partial",
 "locations": [
 { "page_url": "https://acme.com/blog/in-app-feedback-checklist", "section": "Evaluation criteria" },
 { "page_url": "https://acme.com/features", "section": "Why Acme" }
 ]
 },
 "recommendation": {
 "action_type": "new_article",
 "target_page": "https://acme.com/guides/in-app-feedback-tool-buyers-guide",
 "placement": null,
 "changes": "Title: … Meta: …",
 "seo_keywords": ["in-app feedback tool", "saas feedback tool comparison", "buyer's guide"],
 "article_outline": [
 { "heading": "What to look for in a B2B SaaS in-app feedback tool",
 "content_points": ["...", "..."] },
 { "heading": "Feature checklist by use case",
 "content_points": ["...", "..."] }
 ],
 "internal_links": ["https://acme.com/features/in-app-surveys", "..."],
 "external_links": ["https://www.nngroup.com/articles/intercept-surveys/", "..."],
 "expected_result": "..."
 },
 "priority": "High",
 "effort": "L",
 "_judge": { "provider": "Anthropic", "model": "claude-opus-4-7" }
}
```

### Per-action-type field requirements

| Field | new_article | section_addition | minor_optimization | maintain |
|---|---|---|---|---|
| `target_page` | required (proposed URL) | required (existing URL) | required (existing URL) | required (existing URL) |
| `placement` | null | required | null or short | null |
| `changes` | required (title + meta line) | required (150 to 400 words) | required (1 to 3 sentences) | optional |
| `seo_keywords` | required (≥ 3) | required (≥ 3) | required (≥ 2) | optional |
| `article_outline` | required (4 to 8 sections) | null | null | null |
| `internal_links` | required (≥ 2 from page index) | required (≥ 1) | required (≥ 1) | optional |
| `external_links` | required (≥ 1 authoritative) | required (≥ 1) | optional | optional |
| `expected_result` | required | required | required | required |

The validator rejects rows that don't meet these.

### Enums

- `content_status.coverage_level`: `comprehensive` | `partial` | `indirect` | `none`
- `recommendation.action_type`: `new_article` | `section_addition` | `minor_optimization` | `maintain`
- `priority`: `Critical` | `High` | `Medium` | `Low`
- `effort`: `S` | `M` | `L`

### Relationship between coverage_level and action_type (enforced)

| coverage_level | allowed action_type |
|---|---|
| `comprehensive` | `minor_optimization` or `maintain` |
| `partial` | `section_addition` or `minor_optimization` |
| `indirect` | `section_addition` or `minor_optimization` (rarely `new_article`, only if existing references are unsalvageable) |
| `none` | `new_article` |

## 2. Flat CSV (`output/aeo_content_recommendations.csv`)

The 15 user-requested columns, in order:

| # | Column | Type | Source |
|---|---|---|---|
| 1 | `query` | string | recommendation row |
| 2 | `content_exists` | bool | `content_status.exists` |
| 3 | `coverage_level` | enum | `content_status.coverage_level` |
| 4 | `current_locations` | string | `content_status.locations[]` flattened as `URL § section \| URL § section` |
| 5 | `action_type` | enum | `recommendation.action_type` |
| 6 | `target_page` | string | `recommendation.target_page` |
| 7 | `placement` | string | `recommendation.placement` (empty for non-section_addition) |
| 8 | `changes` | string (multiline) | `recommendation.changes` |
| 9 | `seo_keywords` | string | `recommendation.seo_keywords` joined with `, ` |
| 10 | `article_outline` | string (multiline) | flattened: `H: <heading>\n - <point>\n - <point>\n\nH: <heading>\n ...` |
| 11 | `internal_links` | string (multiline) | `recommendation.internal_links` joined with `\n` |
| 12 | `external_links` | string (multiline) | `recommendation.external_links` joined with `\n` |
| 13 | `expected_result` | string | `recommendation.expected_result` |
| 14 | `priority` | enum | inherited from AEO scorecard |
| 15 | `effort` | enum | derived |

### Effort derivation

- `minor_optimization` → `S` (≤ 1 hour of writer time)
- `section_addition` → `M` (≤ half-day)
- `new_article` outline ≤ 5 sections → `M` (1 day)
- `new_article` outline 6 to 8 sections → `L` (2 to 3 days)
- `maintain` → `S`

### XLSX helper columns (added at the front, not in CSV)

| # | Column | Source |
|---|---|---|
|  to 3 | `query_id` | recommendation row |
|  to 2 | `query_category` | recommendation row |
|  to 1 | `gap_types` | `aeo_signals.gap_types` joined with `, ` |

These are **prefixed** to the XLSX so users can filter by query / category / gap without polluting the CSV.

### Conditional formatting (XLSX)

| Column | Rule |
|---|---|
| `priority` | Categorical (Critical red, High orange, Medium yellow, Low gray) |
| `action_type` | Categorical (new_article blue, section_addition teal, minor_optimization green, maintain gray) |
| `coverage_level` | Categorical (comprehensive green, partial yellow, indirect orange, none red) |
| `effort` | Categorical (S green, M yellow, L red) |

## Validation contract

`scripts/compile_recommendations_sheet.py` validates every joined record before writing:

- All 15 columns present
- Types match
- Enums match exact strings
- Per-action-type field-completeness check (the table above)
- `target_page` is either an existing URL in the page index OR a proposed-new URL on the brand's domain
- `internal_links` are all in the page index (no invented URLs)
- `coverage_level → action_type` mapping respected
- `current_locations` formatting respects the ` | ` and ` § ` separators

Failing rows are logged with the specific field violation and **excluded** from the CSV/XLSX (with a count + first 10 reasons in the PDF methodology section). The skill never silently substitutes defaults.
