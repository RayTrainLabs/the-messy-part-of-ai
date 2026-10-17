# Phase 2, Query generation

**Goal:** produce `output/queries.json` containing 50 to 60 unbiased, natural-language queries that cover the brand's category across 9 categories and three intent stages, with **no more than 10%** of queries naming the brand or a competitor.

The full generation framework lives in [`../references/query-generation-prompt.md`](../references/query-generation-prompt.md). This phase doc is the **operational** runbook.

## Steps

1. **Confirm prerequisites:**
 - `output/brand_profile.json` exists and has `validated_at` set (Phase 1 stamped it)
 - At least one LLM key is set (`ANTHROPIC_API_KEY` preferred for query generation; `OPENAI_API_KEY` is the fallback)

2. **Run the generator:**
 ```bash
 python scripts/generate_queries.py \
 --brand-profile output/brand_profile.json \
 --provider anthropic \
 --model claude-opus-4-7 \
 --target-count 20 \
 --out output/queries.json
 ```
 The script loads `templates/query_generation_system_prompt.md`, injects the brand profile, requests structured JSON back, and writes `output/queries.json`.

3. **Run the QA validator** (built into the generator, but re-runnable):
 ```bash
 python scripts/generate_queries.py --validate output/queries.json
 ```
 Validation enforces every check from the framework's QA section:

 | Check | Threshold |
 |---|---|
 | Total query count | within ±5 of `--target-count` (default 20) |
 | Brand-name mentions | ≤ 10% (target ≤ 5) |
 | Competitor-name mentions | included in the 10% above |
 | Distinct categories used | all 9 (A to I) represented; at least 3 queries per category for A to G, at least 2 for H to I |
 | Query duplication | no near-duplicates (cosine similarity > 0.92 → flag) |
 | Length distribution | 35% short (≤12 words) / 40% medium (13 to 22) / 25% long (23+); ±10% tolerance |
 | Specificity gradient | 20% broad / 50% mid / 30% hyper-specific; ±10% tolerance |
 | Intent spread | informational ~18 to 20% / navigational ~22 to 25% / decision ~28 to 30% / problem-centric ~20 to 22% / trend ~5 to 8%; ±5% tolerance |
 | Stage alignment | distribution matches `business_stage` from brand profile (early → 40 to 45% awareness; growth → 30/40/30; mature → 35% decision + 25% advanced) |
 | Geo / demographic context | 20 to 30% of queries reference market_focus from brand profile |

4. **If any check fails**, the script prints the failing check and the offending queries. Re-prompt the LLM with a targeted patch ("regenerate categories E and G with stricter brand-name avoidance") rather than regenerating from scratch.

5. **Show the user a sample** of 8 to 10 queries spanning categories before running Phase 3 (which spends real API credits). Ask:
 > Here are 8 of the 20 queries I generated, one from each major category. Do these sound like questions your buyers would actually ask? Anything sound off-category or too narrow / too broad?

 The user can ask for category-level rewrites (e.g., "the comparative ones are too vendor-focused, make them more methodology-focused"). Re-run step 2 with a delta prompt.

6. **Lock the query set** when the user approves:
 ```json
 "approved_at": "2026-04-27",
 "approved_by": "user"
 ```

## Output contract

`output/queries.json`:

```json
{
 "brand": "Acme",
 "category": "Product feedback / experience analytics",
 "generated_at": "2026-04-27T...",
 "approved_at": "2026-04-27",
 "approved_by": "user",
 "model": "claude-opus-4-7",
 "queries": [
 {
 "id": "Q01",
 "category": "A",
 "category_name": "Core problem / use-case",
 "intent": "problem-centric",
 "stage": "awareness",
 "specificity": "mid",
 "length_bucket": "medium",
 "contains_brand": false,
 "contains_competitor": false,
 "has_geo_context": true,
 "query": "How do remote SaaS product teams quickly find out which newly-shipped features are actually used?"
 },
 ...
 ],
 "validation": {
 "passed": true,
 "checks": { "...": "..." }
 }
}
```

## Why these constraints matter

- **≤ 10% brand mentions**: AEO measures *unbranded discovery*. A query that names your brand will of course return your brand, that is not a visibility test.
- **9 categories**: covers the full funnel from "what is this category" to "we picked X but it broke, alternatives?". Skipping categories produces a biased report.
- **Specificity gradient**: pure broad queries reward leaders disproportionately; pure niche queries miss leadership signal. The mix is what produces a usable share-of-voice number.
- **Geo context in 20 to 30%**: AI engines weight regional cues heavily; without them, a US-focused brand will look invisible in a global category and a global brand will look invisible in a regional category.

## Common pitfalls

- LLMs love comparative queries (category E). They will often over-generate them and underweight problem-discovery (G). Watch for distribution drift.
- LLMs sneak brand names into "natural" examples ("for instance, what makes Slack different from..."). The validator catches these but you should also visually scan.
- "Best [category] tool for [persona]" queries are too generic, they are useful but should be a small slice, not the bulk.
- Adding too many constraints in one prompt → the LLM compromises by writing shorter, blander queries. Use targeted re-prompts for fixes rather than a single mega-prompt.

## References

- [`../references/query-generation-prompt.md`](../references/query-generation-prompt.md), full framework
- [`../templates/query_generation_system_prompt.md`](../templates/query_generation_system_prompt.md), the actual system prompt loaded by the script
