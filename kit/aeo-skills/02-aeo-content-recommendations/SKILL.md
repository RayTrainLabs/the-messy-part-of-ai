---
name: aeo-content-recommendations
description: Use when the user has an AEO scorecard from skill 01 (or any list of target queries) and wants concrete, page-by-page content changes to ship next. Triggers on requests like "what should we actually write to fix the AEO gaps", "turn the AEO report into a content roadmap", "give me page-level SEO/AEO recommendations for these queries", "what content do we need to add or change". Scrapes the brand's full website into clean per-page markdown, builds a relevance index, then for each target query produces a structured recommendation (action_type, target_page, exact changes, article outline, internal/external links, expected result) grounded in the actual current site content. Outputs a CSV/XLSX of recommendations and a PDF report with priority logic and roadmap charts.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# AEO Content Recommendations

Turns AEO visibility findings into a shippable content roadmap. Skill 01 told you **where** the brand is invisible in AI answers. This skill tells you **exactly what to add, change, or write** on the brand's website to close those gaps, grounded in the current site content (not generic advice).

## When to use

- The user has run skill 01 (`aeo-brand-visibility-analysis`) and wants per-query content changes
- The user has a list of target queries (from any source) and wants page-level recommendations against their current site
- The user is planning a content sprint and needs a prioritized backlog of articles / sections / micro-edits
- The user needs to brief a content team with concrete deliverables, not vague "improve SEO" guidance

If the user just wants to **measure** visibility, use skill 01. If the user wants a **technical SEO** audit (crawlability, schema, performance), use the SEO skills set.

## Inputs

Required:
- **Brand website URL**, the full site to scrape and analyze
- **Target queries**, one of:
 - `output/aeo_scorecard.csv` from skill 01 (preferred, carries gap signals + priority)
 - `output/queries.json` from skill 01
 - A plain text file with one query per line (`--queries-txt`)
- **Brand profile**, `output/brand_profile.json` from skill 01 if available; provides ICP, brand voice, messaging, competitor list. If absent, ask the user for the same fields, then save in the same format.

Optional but recommended:
- **APIFY_TOKEN** env var, uses `apify/website-content-crawler` for high-quality JS-rendered scraping with built-in markdown conversion. Falls back to a local Python crawler when absent.
- **At least one LLM key** (`ANTHROPIC_API_KEY` preferred for the judge, `OPENAI_API_KEY` / `GEMINI_API_KEY` as alternatives).

If no LLM key is configured, the skill stops after Phase 1 (site scraped to markdown) and tells the user what to set before continuing.

## The 3 phases

| # | Phase | Reference |
|---|---|---|
| 1 | **Website scraping**, crawl the site, convert each page to clean markdown, write to `output/website_pages/` and an index | [`phases/phase-1-website-scraping.md`](phases/phase-1-website-scraping.md) |
| 2 | **Content recommendations**, for each target query, find existing relevant pages, produce a structured per-query recommendation | [`phases/phase-2-content-recommendations.md`](phases/phase-2-content-recommendations.md) |
| 3 | **Reporting**, compile the per-query recommendations into CSV/XLSX + PDF roadmap with charts, priority logic, what/why/how | [`phases/phase-3-reporting.md`](phases/phase-3-reporting.md) |

## Steps (high-level orchestration)

1. **Read** [`phases/phase-1-website-scraping.md`](phases/phase-1-website-scraping.md). Crawl the site:
 ```bash
 python scripts/scrape_website.py "<URL>" \
 --max-pages 250 \
 --out-dir output/website_pages/
 ```
 Produces `output/website_pages/*.md` (one per crawled page) plus `output/website_pages/_index.json` (the sitemap).

2. **Read** [`phases/phase-2-content-recommendations.md`](phases/phase-2-content-recommendations.md). Generate recommendations:
 ```bash
 python scripts/recommend_content.py \
 --queries output/aeo_scorecard.csv \
 --pages-dir output/website_pages/ \
 --brand-profile output/brand_profile.json \
 --judge-provider anthropic \
 --concurrency 4 \
 --out output/recommendations.jsonl
 ```
 The script feeds the entire scraped site (with content excerpts sized to the page count) to the judge LLM along with each query, the LLM picks which pages are relevant. There is no separate index-build step. Default mode aggregates the AEO scorecard down to one row per unique query; pass `--per-row` to mirror the scorecard 1:1, or `--limit 3` for a cheap smoke test before the full batch.

3. **Read** [`phases/phase-3-reporting.md`](phases/phase-3-reporting.md). Compile and render:
 ```bash
 python scripts/compile_recommendations_sheet.py \
 --recommendations output/recommendations.jsonl \
 --aeo-scorecard output/aeo_scorecard.csv \
 --pages-index output/website_pages/_index.json \
 --out-csv output/aeo_content_recommendations.csv \
 --out-xlsx output/aeo_content_recommendations.xlsx

 python scripts/render_recommendations_pdf.py \
 --xlsx output/aeo_content_recommendations.xlsx \
 --recommendations output/recommendations.jsonl \
 --brand-profile output/brand_profile.json \
 --pages-index output/website_pages/_index.json \
 --out output/aeo_content_roadmap.pdf
 ```

5. **Hand off** the four deliverables to the user:
 - `output/website_pages/` (browsable markdown copy of the site, one file per page)
 - `output/aeo_content_recommendations.csv` and `.xlsx` (per-query roadmap with all recommendation columns)
 - `output/aeo_content_roadmap.pdf` (executive content roadmap with charts and priority logic)
 - `output/aeo_content_executive_summary.md` (one-page markdown for Slack / email)

 Include in the chat reply: total recommendation count by action type (`new_article` / `section_addition` / `minor_optimization` / `maintain`), top-3 highest-priority items, and where the full report lives.

## Output guarantees

- **Grounded in real site content**: every `target_page` is an existing URL on the scraped site (or for `new_article`, a proposed new path with explicit reasoning). The skill cannot recommend changes to pages it has not actually read.
- **Respects user-generated content**: customer reviews, testimonials, and forum content are flagged in Phase 1 and excluded from `target_page` candidates in Phase 2, recommendations never propose modifying these sections.
- **Per-action-type completeness**:
 - `minor_optimization` rows always have `target_page` + `changes` (1 to 3 sentences) + keywords
 - `section_addition` rows always have `target_page` + `placement` + `changes` (150 to 400 words) + keywords
 - `new_article` rows always have `target_page` (proposed URL) + `article_outline` (4 to 8 sections) + meta in `changes` + keywords
 - `maintain` rows are emitted only when the AEO scorecard already shows the brand dominating that query, they're explicit "do nothing" decisions, not gaps in coverage
- **Brand-voice aligned**: every recommendation includes prose written in the brand's voice (not generic SEO copywriting). The judge LLM is given voice samples from the brand profile + the scraped homepage.
- **Priority + effort labelled**: every row carries a `priority` (Critical/High/Medium/Low, inherited from the AEO scorecard) and an `effort` (S/M/L, derived from action type and content length).
- **Reproducibility**: re-running on a fresh scrape produces a comparable second roadmap; the `output/` folder is dated and self-contained.

## How this skill chains with skill 01

```
Skill 01 (aeo-brand-visibility-analysis)
 output/aeo_scorecard.csv ← visibility per query × engine
 output/brand_profile.json
 │
 ▼
Skill 02 (this one)
 Phase 1: scrape website → output/website_pages/*.md
 Phase 2: per-query recommendation grounded in scrape + scorecard signals
 Phase 3: CSV + XLSX + PDF roadmap
 │
 ▼
 Content / SEO team executes the roadmap
 │
 ▼
Skill 01 re-run in N weeks → trend chart confirms gaps closed
```

You can also run skill 02 standalone (without skill 01) by passing a plain `--queries-txt` file, but you lose the gap-signal context that makes priority and "why this matters" specific. Strongly prefer the chained flow.

## References

- [`references/output-schema.md`](references/output-schema.md), exact recommendation schema (nested + flattened CSV form)
- [`references/action-types.md`](references/action-types.md), when to choose each action_type and what each requires
- [`references/seo-aeo-best-practices.md`](references/seo-aeo-best-practices.md), the SEO + AEO rules the recommendations must follow
- [`templates/content_recommendations_system_prompt.md`](templates/content_recommendations_system_prompt.md), the system prompt loaded by `recommend_content.py`
- [`examples/sample-recommendation-row.md`](examples/sample-recommendation-row.md), one fully-worked recommendation across action types
