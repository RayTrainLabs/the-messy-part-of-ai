# Phase 4, Metrics analysis

**Goal:** for every row in `output/raw_responses.jsonl`, compute the 13 visibility metric fields defined in the rubric and write `output/scored_rows.jsonl`.

The full rubric (scoring formulas, thresholds, classification rules, validation contract) lives in [`../references/metrics-rubric.md`](../references/metrics-rubric.md). This phase doc is the **operational** runbook.

## Fields produced per row

| Field | Type | Source |
|---|---|---|
| `response_summary` | string (2 to 3 sentences) | LLM, judgment |
| `brand_mentioned` | bool | LLM after deterministic name-match check |
| `brands_mentioned_list` | string[] (sorted, deduplicated) | LLM after deterministic + heuristic detection |
| `citation_frequency_score` | int 0 to 100 | Deterministic from text/citation counts |
| `share_of_voice_percentage` | float 0.0 to 100.0 | Deterministic |
| `positional_authority_score` | int 0 to 100 | LLM, rubric-driven |
| `sentiment_direction_score` | int -50 to +50 | LLM, rubric-driven |
| `response_relevance_score` | int 0 to 100 | LLM, rubric-driven |
| `market_position_type` | enum | Derived from above |
| `discovery_role` | enum | Derived from above |
| `positioning_narrative` | string (150 to 250 chars) | LLM |
| `strength_score` | int 0 to 10 | Derived from market_position + sentiment |

`query_tested` is carried forward from Phase 3 unchanged.

## Steps

1. **Confirm prerequisites:**
 - `output/raw_responses.jsonl` exists with successful rows
 - `output/brand_profile.json` is present (needed for target brand + competitor list)
 - At least one LLM key is configured (for the judge; Anthropic preferred, different model from the one being audited if possible, to reduce circular bias)

2. **Run the scorer:**
 ```bash
 python scripts/analyze_response.py \
 --responses output/raw_responses.jsonl \
 --brand-profile output/brand_profile.json \
 --judge-provider anthropic \
 --judge-model claude-opus-4-7 \
 --mode metrics \
 --concurrency 6 \
 --out output/scored_rows.jsonl
 ```
 The script:
 - Loads each raw row
 - Runs a deterministic brand/competitor name scan first (regex with word boundaries, case-insensitive, plus simple plural / possessive variants)
 - Calls the judge LLM with the prompt in [`../templates/metrics_analysis_system_prompt.md`](../templates/metrics_analysis_system_prompt.md), passing the deterministic scan as a hint the judge must reconcile
 - Validates the JSON response against the schema (cap enforcement, enum validity, required fields)
 - Re-prompts up to 2× on schema failure
 - Writes one scored row to `output/scored_rows.jsonl`

3. **Manual spot-check (mandatory).** Pick **3 rows the judge marked `brand_mentioned = true`** and **2 rows it marked `false`**. Read the raw text for each and confirm:
 - Brand-mention boolean is correct
 - `brands_mentioned_list` is complete and not double-counting (e.g., "Acme" and "Acme Inc" should be one entry)
 - `share_of_voice_percentage` math reconciles (sum of all brand mentions vs. target)
 - `positional_authority_score` matches the rubric (count the points)
 - `sentiment_direction_score` is not over- or under-weighted

 If ≥ 1 of 5 spot-checks is wrong, re-run with a different judge model or tighten the rubric prompt with a counter-example. **Do not proceed to Phase 5 with bad scores**, every downstream recommendation will be off.

4. **Aggregate sanity checks** (printed automatically by the script):
 - Mean, median, p25/p75 of each numeric metric
 - Per-engine breakdown (e.g., does the brand appear in 80% of Perplexity rows but 5% of Gemini rows?, that's a real finding, not a bug)
 - Per-category breakdown (which query categories surface the brand at all?)
 - Brand list cardinality (how many distinct brands across all rows? if < 5, the category may be defined too narrowly; if > 100, possibly being too liberal in detection)

5. **If aggregate checks reveal something suspicious** (e.g., 0 brand mentions across 220 rows), pause. Re-read 5 to 10 raw rows. Either:
 - The brand is genuinely invisible (real finding, proceed; the report will say so loudly)
 - The judge prompt is failing to detect mentions (fix prompt, re-run)
 - The brand name has an unusual form (e.g., "Acme.AI" vs. "Acme") that needs alias handling, add aliases to `brand_profile.json` under `brand_aliases: [...]` and re-run

## Output contract

`output/scored_rows.jsonl`, one row per (query × engine), 13 metric fields plus `row_id`, `query_id`, `query_tested`, `engine`, and a `_judge` block with the model used and timestamp.

## Why a judge LLM (not pure regex)?

- **Sentiment** and **positional authority** are inherently semantic, counting words misses sarcasm, conditional praise, faint-praise burying ("X is a fine option, but Y is what most teams pick").
- **Brand detection** still uses deterministic regex first because LLMs occasionally miss exact-string matches; the judge reconciles ambiguous cases (e.g., "Acme" in a sentence about Acme Corporation construction company vs. the SaaS).
- **Share of voice** math is deterministic but depends on the brand list, which is judge-produced.

## Common pitfalls

- **Single-model bias.** Using GPT-5 to judge GPT-5 responses will inflate sentiment scores and under-detect competitors. Cross-judge: use Claude to judge OpenAI/Gemini/Perplexity/SERP, and vice versa.
- **Hallucinated brand mentions** in the judge response (judge claims the brand is mentioned when it isn't). The deterministic pre-scan + a final assertion in the validator catches most of these.
- **Brand-name collisions.** "Notion" the SaaS vs. "the notion of X" the noun. The rubric requires the judge to consider context; the validator double-checks proper-noun framing.
- **Over-counting citations.** The same domain cited twice in one response counts as 2 citations only if they are distinct URLs. Same URL → 1.

## References

- [`../references/metrics-rubric.md`](../references/metrics-rubric.md), full scoring rubric
- [`../templates/metrics_analysis_system_prompt.md`](../templates/metrics_analysis_system_prompt.md), system prompt loaded by the scorer
