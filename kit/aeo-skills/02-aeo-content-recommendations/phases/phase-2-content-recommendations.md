# Phase 2, Content recommendations

**Goal:** for every target query, produce one structured recommendation describing exactly what content to add / change / write on the brand's site to improve visibility for that query. Output: `output/recommendations.jsonl`.

The full recommendation schema lives in [`../references/output-schema.md`](../references/output-schema.md). The action-type rules live in [`../references/action-types.md`](../references/action-types.md). The system prompt sent to the judge LLM lives in [`../templates/content_recommendations_system_prompt.md`](../templates/content_recommendations_system_prompt.md). This phase doc is the **operational** runbook.

## Inputs

- `output/website_pages/_index.json` and `output/website_pages/*.md` (from Phase 1)
- A target-queries source, one of:
 - `output/aeo_scorecard.csv` (preferred, carries gap signals and priority)
 - `output/queries.json`
 - `--queries-txt one_per_line.txt`
- `output/brand_profile.json` (ICP, brand voice, messaging, competitors)

## Design note: no relevance pre-filter

Earlier versions ran a TF-IDF index step before this phase. We removed it. The judge LLM now sees **every page on the scraped site** (with content excerpts sized to the page count) and picks relevance itself. Reasons:

- Less code, fewer scripts, fewer failure modes
- The LLM is better at semantic relevance than TF-IDF (handles synonyms, jargon, niche use-cases)
- Cost is comparable: 80 pages × 2.5k chars/page in a single prompt ≈ same input tokens as TF-IDF + 12 full pages
- For sites > 200 pages, the script auto-shrinks the per-page snippet so the prompt stays within budget

## Steps

1. **Decide granularity:**
 - **Default (per-query):** one recommendation per unique query. The script aggregates the AEO scorecard rows for that query (worst-case priority, union of competitor_advantage, average share-of-voice). This is what the user almost always wants.
 - **`--per-row`:** one recommendation per scorecard row (query × engine). Use only when the user explicitly asks for engine-specific content tactics.

2. **Smoke-test first** (mandatory before committing to the full batch, protects against bad prompts / over-budget runs):
 ```bash
 python scripts/recommend_content.py \
 --queries output/aeo_scorecard.csv \
 --pages-dir output/website_pages/ \
 --brand-profile output/brand_profile.json \
 --judge-provider anthropic \
 --limit 3 \
 --out output/recommendations.smoke.jsonl
 ```
 Read the 3 smoke rows. Are the recommendations grounded in the actual scraped content? Are the internal_links real URLs? Is the brand voice right? If yes, run the full batch.

3. **Generate the full batch:**
 ```bash
 python scripts/recommend_content.py \
 --queries output/aeo_scorecard.csv \
 --pages-dir output/website_pages/ \
 --brand-profile output/brand_profile.json \
 --judge-provider anthropic \
 --judge-model claude-opus-4-7 \
 --concurrency 4 \
 --out output/recommendations.jsonl
 ```

 For each query the script:
 1. Loads every scraped page from `output/website_pages/` (shared across all queries, read once).
 2. Builds the per-page payload (URL + title + page_type + is_ugc + content excerpt). Snippet size is auto-tuned: ≤ 30 pages → 6000 chars/page, ≤ 80 → 2500, ≤ 200 → 900, more → 400.
 3. Pulls AEO-scorecard signals for the query (mention rate, share-of-voice, top competitor advantage, priority, gap_type) and the brand profile (ICP, voice samples, key messaging, competitor list).
 4. Calls the judge LLM with the system prompt in `templates/content_recommendations_system_prompt.md`. The LLM picks which pages are relevant.
 5. Validates the JSON response: enums, UGC exclusion, internal_links must be on the scraped site, on-domain check for `new_article` target_page, per-action-type field minimums (see [`../references/action-types.md`](../references/action-types.md)).
 6. Re-prompts up to 2× on schema failure.
 7. Writes one JSON object to `output/recommendations.jsonl`.

4. **Mid-batch sanity check** (printed automatically every 10 queries):
 - Action-type distribution so far (e.g., `new_article: 4 / section_addition: 5 / minor_optimization: 1 / maintain: 0`)
 - Target_page collisions (multiple queries → same page), flagged as content-cluster opportunities
 - Any recommendations targeting `is_ugc: true` pages (should be 0, the validator catches this)

5. **Manual spot-check** (mandatory), pick 3 rows spanning action types and read them end-to-end:
 - Does `target_page` make sense for the query?
 - Are the `seo_keywords` natural language, not stuffed?
 - For `new_article`: does the outline cover the topic in a way a competent writer could turn into a draft? Are there 4 to 8 sections?
 - For `section_addition`: does `placement` reference an actual section on the target page?
 - Do the `internal_links` point to real pages on the scraped site?
 - Does `expected_result` describe a concrete visibility outcome, not vague "more traffic"?

 If ≥ 1 of 3 spot-checks is wrong, tighten the prompt with a counter-example and re-run.

## Output schema (per row in `output/recommendations.jsonl`)

Full nested schema:

```json
{
 "row_id": "Q07",
 "query": "What should a B2B SaaS product team look for when choosing an in-app feedback tool, features, pricing model, and red flags?",
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
 {"page_url": "https://acme.com/blog/in-app-feedback-checklist", "section": "Evaluation criteria"},
 {"page_url": "https://acme.com/features", "section": "Why Acme"}
 ]
 },
 "recommendation": {
 "action_type": "new_article",
 "target_page": "https://acme.com/guides/in-app-feedback-tool-buyers-guide",
 "placement": null,
 "changes": "Title: B2B SaaS In-App Feedback Tool Buyer's Guide (2026). Meta: A practical evaluation framework with feature checklists, pricing-model analysis, and red flags, covering Acme, Pendo, Sprig, and FullStory side-by-side.",
 "seo_keywords": ["in-app feedback tool", "product feedback platform", "saas feedback tool comparison", "buyer's guide"],
 "article_outline": [
 {
 "heading": "What to look for in a B2B SaaS in-app feedback tool",
 "content_points": [
 "60-word direct answer summarizing the four evaluation pillars (features, pricing, integrations, support)",
 "Quick comparison table: Acme vs Pendo vs Sprig vs FullStory across the four pillars"
 ]
 },
 {
 "heading": "Feature checklist by use case",
 "content_points": [
 "Micro-surveys at moments of friction (Acme's strength)",
 "Session-replay linkage",
 "Slack/Teams alerts on negative sentiment",
 "Audience segmentation"
 ]
 }
 // ... 4-6 more sections
 ],
 "internal_links": [
 "https://acme.com/features/in-app-surveys",
 "https://acme.com/integrations/slack",
 "https://acme.com/customers/series-b-saas-team-improves-activation-by-40"
 ],
 "external_links": [
 "https://www.nngroup.com/articles/intercept-surveys/",
 "https://en.wikipedia.org/wiki/Net_promoter_score"
 ],
 "expected_result": "New page captures featured-snippet eligibility for 'best in-app feedback tool' and '[competitor] alternatives' queries; 8-12 weeks post-publish, Acme begins surfacing in 2-3 of 5 LLM answers for category-C decision queries."
 },
 "priority": "High",
 "effort": "L",
 "_judge": { "provider": "Anthropic", "model": "claude-opus-4-7" }
}
```

## Per-action-type required fields (enforced by validator)

| Action type | Required fields |
|---|---|
| `new_article` | `target_page` (proposed URL), `changes` (title + meta), `seo_keywords`, `article_outline` (4 to 8 sections), `internal_links`, `external_links`, `expected_result` |
| `section_addition` | `target_page` (existing URL), `placement`, `changes` (150 to 400 words), `seo_keywords`, `internal_links`, `external_links`, `expected_result` |
| `minor_optimization` | `target_page` (existing URL), `changes` (1 to 3 sentences), `seo_keywords`, `internal_links`, `external_links`, `expected_result` |
| `maintain` | `target_page` (the page that's already winning), `expected_result` (what to keep doing); other fields may be empty |

## Why a judge LLM (not pure templates)

- **Brand voice matching** is semantic, formulaic SEO copy reads off-brand and gets revised by the content team anyway. The judge sees voice samples from the brand profile + the homepage and writes in that voice.
- **Section placement** depends on the existing structure of the target page. A template can't know that the page already has an "Integrations" section after "Pricing", the judge reads the actual markdown.
- **Article outlines** require coverage planning that respects what's already on the site (avoid duplicating an existing post; complement it instead).
- **Determinism is a non-goal**, the same query will produce slightly different recommendations on re-runs, which is fine. What matters is that recommendations are *consistent with* the brand's content, not bit-identical.

## Common pitfalls

- **Recommending edits to UGC pages.** The validator rejects rows whose `target_page` matches an `is_ugc: true` page from the index. The prompt also calls this out explicitly.
- **Vague `changes` field.** "Add more details about your features" is not a change. The prompt requires actual prose for `minor_optimization` and `section_addition`, and a real outline for `new_article`.
- **`internal_links` to invented URLs.** The validator checks that every internal link is in the page index. The prompt is given the flat sitemap precisely to prevent invention.
- **Same page recommended for 20 different queries.** Real signal, those queries cluster topically. The compiler in Phase 3 surfaces this as a "content cluster opportunity" rather than 20 separate row-level fixes.
- **Recommending `new_article` when content already exists.** The prompt explicitly maps `coverage_level → action_type`: `comprehensive → minor_optimization or maintain`, `partial/indirect → section_addition or minor_optimization`, `none → new_article`. The validator enforces this mapping.

## References

- [`../references/output-schema.md`](../references/output-schema.md), full schema (nested + flat CSV)
- [`../references/action-types.md`](../references/action-types.md), when to choose each action and what each requires
- [`../references/seo-aeo-best-practices.md`](../references/seo-aeo-best-practices.md), the SEO + AEO rules embedded in the prompt
- [`../templates/content_recommendations_system_prompt.md`](../templates/content_recommendations_system_prompt.md), system prompt loaded by `recommend_content.py`
