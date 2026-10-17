# Action types

There are exactly four action_types. The judge LLM picks one per query based on `coverage_level` and the AEO-scorecard gap signals. The validator enforces the mapping.

## Decision tree

```
What's the coverage_level for this query on the current site?
├── comprehensive → strength_score on AEO scorecard?
│ ├── ≥ 7 (we're winning) → maintain
│ └── < 7 (we have content but losing) → minor_optimization
├── partial → does the right page exist but underdeveloped?
│ ├── yes (1-3 sentences would close the gap) → minor_optimization
│ └── no (a dedicated 150-400 word section) → section_addition
├── indirect → section_addition (usually) or new_article (rare, only if existing references can't be salvaged)
└── none → new_article
```

The validator enforces this map. A judge response with `coverage_level: none` and `action_type: minor_optimization` is rejected.

## new_article

**When:** no content exists on the site addressing the query.

**Required deliverables:**
- `target_page`: a proposed new URL on the brand's domain (e.g., `https://acme.com/guides/in-app-feedback-tool-buyers-guide`). Must be on-domain; the validator rejects external proposals.
- `changes`: title + meta description. One line for each, prefixed `Title:` and `Meta:`.
- `seo_keywords`: 3 to 7 keywords. Primary first, secondaries after. Must be natural language, not stuffed.
- `article_outline`: 4 to 8 sections. Each section has:
 - `heading`: clear, SEO-friendly. Phrase as a question for AEO when the query is informational ("What is X?", "How do I X?").
 - `content_points`: bullet list (3 to 7 points) of what the section must cover. Not full prose, that's the writer's job.
- `internal_links`: ≥ 2 existing pages on the scraped site. The validator checks against the page index.
- `external_links`: ≥ 1 authoritative external source (Wikipedia, NNGroup, government, peer-reviewed, industry standard). Not a blog, not a competitor's page.
- `expected_result`: a sentence describing the visibility outcome, when, on which engines, against which competitors.

**Quality bar:**
- The outline must cover enough to make the article cite-worthy (an LLM scanning the page should be able to answer the original query from the page alone).
- The first section should answer the query directly in 40 to 60 words (AEO direct-answer pattern).
- Articles supporting decision-stage queries should include a comparison table or pros/cons block.

## section_addition

**When:** the right page exists but lacks dedicated coverage of the query topic.

**Required deliverables:**
- `target_page`: an existing URL from the page index. Must not be a UGC page (the validator checks `is_ugc: false`).
- `placement`: where on the target page to insert the section. Reference an actual section from the page's heading hierarchy ("after the 'Why Acme' section", "before the 'Customers' section", "above the FAQ"). Generic "at the end" is allowed only when the page has no clear section structure.
- `changes`: 150 to 400 words of actual content (or detailed bullet points). Includes the section heading (formatted as a question for AEO when appropriate). Must be in the brand's voice.
- `seo_keywords`: 3 to 5 keywords to incorporate naturally.
- `internal_links`: ≥ 1 link from the new section to another existing page.
- `external_links`: ≥ 1 authoritative external source.
- `expected_result`: visibility outcome.

**Quality bar:**
- The new section reads like it belongs on the target page, same voice, same style, same depth.
- The first sentence after the section heading is the direct answer (AEO).
- The section's heading should not duplicate an existing heading on the page.

## minor_optimization

**When:** the right page exists with the right section, but coverage is shallow or keyword integration is weak.

**Required deliverables:**
- `target_page`: an existing URL from the page index. Not a UGC page.
- `placement`: optional. If specified, names the existing section being modified.
- `changes`: 1 to 3 sentences of new prose to insert OR replace existing prose with. Surgical, not a rewrite.
- `seo_keywords`: 2 to 5 keywords.
- `internal_links`: ≥ 1 internal link to add.
- `external_links`: optional but recommended.
- `expected_result`: visibility outcome.

**Quality bar:**
- Changes are minimal and reversible.
- Keyword integration reads natural, never "best in-app feedback tool for B2B SaaS in-app feedback tool".
- Existing structure / hierarchy preserved.

## maintain

**When:** the AEO scorecard already shows the brand winning this query (Leader / Primary discovery role, strength ≥ 7) AND coverage_level is comprehensive.

**Required deliverables:**
- `target_page`: the page that's already winning.
- `expected_result`: what to keep doing, the patterns / signals on the page that are working, so a future redesign doesn't accidentally regress them.

**Why include `maintain` rows at all:**
- The PDF report's "What's good (don't break this)" section depends on them.
- Site-redesign briefs often regress winning pages because nobody named them. `maintain` rows are an explicit "leave this alone" record.
- Without `maintain`, the roadmap looks like everything is broken, it isn't.

## What the prompt is told to NEVER do

- Recommend modifying a UGC page (testimonials, reviews, forum content). The Phase 1 scrape flags these via `is_ugc: true`.
- Invent internal-link URLs that don't exist on the site.
- Invent external links to non-existent sources.
- Write generic SEO copy ("In today's competitive landscape...") that doesn't match the brand voice.
- Recommend `new_article` when a partial-coverage page already exists, that's almost always a `section_addition` instead.
- Stuff keywords. Two natural mentions beat eight unnatural ones.
- Suggest changes that contradict the brand's stated positioning (e.g., recommending enterprise-targeted content for an explicitly SMB-focused brand).
