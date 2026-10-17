---
name: aeo-brand-visibility-analysis
description: Use when the user wants an Answer Engine Optimization (AEO) / AI-search visibility audit of a brand. Triggers on requests like "how does my brand show up in ChatGPT / Perplexity / Gemini", "AEO audit", "AI visibility report", "share of voice in AI answers", "where do we rank in LLM responses", "AI search benchmark vs competitors". Builds a brand profile (from supplied docs or by crawling the site), generates 20 unbiased category-level queries (configurable via `--target-count`), runs them through SERP and LLM APIs, scores each response for the target brand's visibility, identifies content gaps, and produces both a CSV/XLSX scorecard and a PDF report with charts and a prioritized action plan.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# AEO Brand Visibility Analysis

End-to-end AEO audit. Takes a brand and produces a per-query scorecard plus a prioritized action report showing where the brand stands inside AI answer engines today and what to fix first.

## When to use

- The user asks for an AEO / GEO / AI-visibility / answer-engine audit on a brand
- The user wants to know how their brand is mentioned by ChatGPT, Perplexity, Claude, Gemini, or Google AI Overviews
- The user wants share-of-voice vs. competitors in AI answers
- The user is preparing a quarterly AI-visibility baseline or board report
- The user just shipped major positioning/content changes and wants to re-baseline

If the user wants **classic SEO** issues (crawl, indexability, schema, internal links, page-level optimization), use the SEO skills set instead. AEO is the layer **on top** of solid SEO.

## Inputs

Required (one of):
- **Brand documents**, any combination of brand profile, ICP, customer segments, product overview, marketing docs, positioning docs. Path(s) or pasted text.
- **Brand website URL**, if no docs supplied, the skill crawls the site to derive ICP, positioning, product, competitors.

Either way, the skill confirms the synthesized brand picture with the user before moving on (Phase 1).

Optional but strongly recommended:
- **Known competitors**, direct + indirect. If not provided, the skill infers them from the site/docs and asks the user to confirm.
- **Geographic / demographic targeting**, e.g., "US mid-market", "EU enterprise", "India D2C", "remote teams globally". Used to localize ~20 to 30% of generated queries.
- **API keys** (env vars):
 - At least one SERP source: `SERPAPI_KEY` **or** `APIFY_TOKEN`, **mandatory**. Without SERP we have no ground truth.
 - LLM engine keys (any subset): `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `PERPLEXITY_API_KEY`, `GEMINI_API_KEY`, strongly recommended. The skill skips engines whose key is missing and notes the gap in the report.

If no API keys are configured, the skill stops at Phase 2 (queries generated) and tells the user what to set before continuing, it does not fabricate engine responses.

## The 7 phases

The skill orchestrates seven phases. Each phase has its own reference doc; load it on demand.

| # | Phase | Reference |
|---|---|---|
| 0 | **Brand intake**, read user docs OR crawl site OR ask the user; synthesize brand profile, ICP, product, positioning, competitors | [`phases/phase-0-brand-intake.md`](phases/phase-0-brand-intake.md) |
| 1 | **Brand validation**, present synthesized profile to the user; iterate until confirmed | [`phases/phase-1-brand-validation.md`](phases/phase-1-brand-validation.md) |
| 2 | **Query generation**, produce 20 unbiased category queries across 9 categories using the framework | [`phases/phase-2-query-generation.md`](phases/phase-2-query-generation.md) |
| 3 | **Query execution**, fan-out each query across SERP + every available LLM engine; save raw responses | [`phases/phase-3-query-execution.md`](phases/phase-3-query-execution.md) |
| 4 | **Metrics analysis**, for each (query, engine) row, compute the 13 visibility scores | [`phases/phase-4-metrics-analysis.md`](phases/phase-4-metrics-analysis.md) |
| 5 | **Gap & optimization**, for each row, identify content gaps and produce SEO + AEO recommendations | [`phases/phase-5-gap-optimization.md`](phases/phase-5-gap-optimization.md) |
| 6 | **Reporting**, compile the CSV/XLSX scorecard and render the PDF report with charts | [`phases/phase-6-reporting.md`](phases/phase-6-reporting.md) |

## Steps (high-level orchestration)

1. **Read** [`phases/phase-0-brand-intake.md`](phases/phase-0-brand-intake.md) and execute it. Stop and ask the user the four canonical questions if neither docs nor URL are supplied.

2. **Read** [`phases/phase-1-brand-validation.md`](phases/phase-1-brand-validation.md). Show the synthesized profile to the user (`output/brand_profile.md`). Iterate edits until the user says "looks good". **Do not proceed until validated.**

3. **Read** [`phases/phase-2-query-generation.md`](phases/phase-2-query-generation.md). Run:
 ```bash
 python scripts/generate_queries.py \
 --brand-profile output/brand_profile.json \
 --out output/queries.json
 ```
 This calls Anthropic (or your configured LLM) with the prompt in [`templates/query_generation_system_prompt.md`](templates/query_generation_system_prompt.md). Run the QA checks listed in the phase doc before moving on.

4. **Read** [`phases/phase-3-query-execution.md`](phases/phase-3-query-execution.md). Verify which providers are available:
 ```bash
 python scripts/run_queries.py --check-providers
 ```
 Then execute the full sweep:
 ```bash
 python scripts/run_queries.py \
 --queries output/queries.json \
 --brand "<TARGET BRAND>" \
 --out output/raw_responses.jsonl
 ```
 The script saves one row per (query × engine) plus the raw payload under `output/raw/`.

5. **Read** [`phases/phase-4-metrics-analysis.md`](phases/phase-4-metrics-analysis.md). Score each row:
 ```bash
 python scripts/analyze_response.py \
 --responses output/raw_responses.jsonl \
 --brand "<TARGET BRAND>" \
 --competitors output/brand_profile.json \
 --out output/scored_rows.jsonl
 ```
 This script delegates the per-row scoring to an LLM using the rubric in [`references/metrics-rubric.md`](references/metrics-rubric.md). Spot-check 3 to 5 rows manually against the LLM answer before trusting the batch.

6. **Read** [`phases/phase-5-gap-optimization.md`](phases/phase-5-gap-optimization.md). Generate gap + optimization fields:
 ```bash
 python scripts/analyze_response.py \
 --responses output/raw_responses.jsonl \
 --scored output/scored_rows.jsonl \
 --brand "<TARGET BRAND>" \
 --competitors output/brand_profile.json \
 --mode gaps \
 --out output/gap_rows.jsonl
 ```

7. **Read** [`phases/phase-6-reporting.md`](phases/phase-6-reporting.md). Compile the scorecard and render the PDF:
 ```bash
 python scripts/compile_sheet.py \
 --scored output/scored_rows.jsonl \
 --gaps output/gap_rows.jsonl \
 --raw output/raw_responses.jsonl \
 --brand-profile output/brand_profile.json \
 --out-csv output/aeo_scorecard.csv \
 --out-xlsx output/aeo_scorecard.xlsx

 python scripts/render_pdf_report.py \
 --xlsx output/aeo_scorecard.xlsx \
 --brand-profile output/brand_profile.json \
 --out output/aeo_report.pdf
 ```

8. **Hand off** the four deliverables to the user:
 - `output/aeo_scorecard.csv` (raw data, 20 columns)
 - `output/aeo_scorecard.xlsx` (formatted, with conditional formatting + 3 helper columns)
 - `output/aeo_report.pdf` (executive report with charts)
 - `output/aeo_executive_summary.md` (one-page markdown for Slack / email)

 Include a 5-line executive summary in the chat reply: visibility status (Excellent/Good/Moderate/Weak/Not visible), share of voice number, top 1 competitor threat, single most important next action, and where the full report lives.

## Output guarantees

- **Provenance**: every scorecard row links back to the raw API response that produced it under `output/raw/`. Nothing is unverifiable.
- **Brand profile is validated**: no analysis runs against an unvalidated brand picture.
- **Engine transparency**: the report names exactly which engines were queried and which were skipped (and why, missing key, rate limit, etc.).
- **Provider neutrality**: the skill never fabricates engine responses; if no LLM keys are available it still produces the SERP-only scorecard and clearly marks LLM columns as `n/a`.
- **Actionability**: every gap has a concrete SEO + AEO action with deliverables; nothing in the report is a vague suggestion.
- **Reproducibility**: the `output/` folder is dated and self-contained; re-running on a different day produces a comparable second snapshot for trend analysis.

## References

- [`references/query-generation-prompt.md`](references/query-generation-prompt.md), the full 9-category query-generation framework, rules, and QA checklist
- [`references/metrics-rubric.md`](references/metrics-rubric.md), the brand-visibility metrics engine specification (Phase 4)
- [`references/gap-analysis-rubric.md`](references/gap-analysis-rubric.md), the gap-analyzer & optimization-engine specification (Phase 5)
- [`references/output-schema.md`](references/output-schema.md), the exact 20-column scorecard schema with types and validators
- [`references/api-providers.md`](references/api-providers.md), provider configuration, web-search/grounding flags, rate limits, fallbacks
- [`templates/query_generation_system_prompt.md`](templates/query_generation_system_prompt.md), system prompt loaded by `scripts/generate_queries.py`
- [`templates/metrics_analysis_system_prompt.md`](templates/metrics_analysis_system_prompt.md), system prompt loaded by `scripts/analyze_response.py` (scoring mode)
- [`templates/gap_optimization_system_prompt.md`](templates/gap_optimization_system_prompt.md), system prompt loaded by `scripts/analyze_response.py` (gaps mode)
- [`examples/sample-output-row.md`](examples/sample-output-row.md), what one fully-scored row looks like end-to-end
