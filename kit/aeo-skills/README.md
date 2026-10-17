# AEO Skills

Claude Code skills for **Answer Engine Optimization (AEO)**, measuring how well a brand shows up in AI search engines (ChatGPT, Perplexity, Claude, Gemini, Google AI Overviews) and producing a prioritized plan to improve that visibility.

The SEO skills set in `../SEO skills/` covers classic search visibility (crawl, schema, rankings). This set covers the **AI / answer-engine** layer that sits on top.

## The skills

| # | Skill | What it does | When to run |
|---|---|---|---|
| 01 | [aeo-brand-visibility-analysis](./01-aeo-brand-visibility-analysis) | End-to-end AEO audit for one brand: understands the brand, generates 50 to 60 unbiased category queries, runs them through SERP + LLM APIs, scores the brand's visibility per query, identifies content gaps, outputs a CSV/XLSX scorecard plus a PDF report with charts and prioritized actions. | Quarterly baseline · After a major content/positioning shift · Before a competitor benchmark exercise |
| 02 | [aeo-content-recommendations](./02-aeo-content-recommendations) | Turns the AEO scorecard from skill 01 into a per-query content roadmap. Scrapes the brand's site to clean per-page markdown, then for each target query produces a structured recommendation (action_type, target_page, exact changes, article outline, internal/external links, expected result). Outputs a CSV/XLSX of recommendations and a PDF roadmap with priority logic and cluster opportunities. | Right after every AEO audit · Before a content sprint · Before a site redesign (to capture "don't break this" rows) |

Skills 01 and 02 are the foundational pair: **measure** AI-search visibility, then **act** on the website.

## Shared utilities


## How these skills chain (and how they relate to the SEO skills)

```
SEO skills (visibility in classic search)
 └── content briefs, schema, internal links, page audits

AEO skills (visibility in AI answer engines)
 ├── 01 brand-visibility-analysis ← measure where you stand
 │ output: aeo_scorecard.csv, brand_profile.json, aeo_report.pdf
 │ │
 │ ▼
 ├── 02 content-recommendations ← turn the audit into a content roadmap
 │ inputs: aeo_scorecard.csv + brand website
 │ output: aeo_content_recommendations.csv/xlsx, aeo_content_roadmap.pdf
 │ │
 │ ▼
 │ (content team executes the roadmap)
 │ │
 │ ▼
 └── re-run skill 01 in N weeks → trend chart confirms gaps closed
```

Run skill 01 first to know what AI engines say about the brand today. Run skill 02 to translate that into shippable content changes. Use the SEO skills set in parallel for the technical / structured-data layer. Re-run skill 01 in 4 to 8 weeks to confirm the changes closed the gaps.

## Installation

These skills are designed for [Claude Code](https://docs.claude.com/en/docs/claude-code/skills). Copy any skill folder into `~/.claude/skills/<skill-name>/` (user-level) or `.claude/skills/<skill-name>/` (project-local), the destination directory should match the `name` field in `SKILL.md`'s frontmatter (e.g., `~/.claude/skills/aeo-brand-visibility-analysis/`). Each `SKILL.md` already has the YAML frontmatter Claude Code expects.

## Python dependencies

Install with:

```bash
pip install -r requirements.txt
```

Required: `requests`, `beautifulsoup4`, `lxml`, `pandas`, `openpyxl`, `matplotlib`, `reportlab`.

## API providers

The skill is **provider-pluggable**. At minimum it needs **one SERP source** (without it, AEO has no ground truth). LLM engines are layered on top. Configure via environment variables:

| Provider | Env var | Required? | Notes |
|---|---|---|---|
| SerpApi | `SERPAPI_KEY` | One SERP source required | Free tier exists; easiest start |
| Apify (Google SERP actor) | `APIFY_TOKEN` | Alternative SERP source | Use if SerpApi credits exhausted |
| OpenAI / ChatGPT | `OPENAI_API_KEY` | Recommended | Set web-search tool ON when supported |
| Anthropic / Claude | `ANTHROPIC_API_KEY` | Recommended | Use web-search tool when available |
| Perplexity | `PERPLEXITY_API_KEY` | Recommended | Native answer-engine; high signal |
| Google Gemini | `GEMINI_API_KEY` | Recommended | Set web-grounding ON |

If a provider key is missing, that engine is skipped (with a note in the report). The skill never fails just because one engine is unavailable, as long as **at least one SERP source plus at least one LLM** is reachable.

## Output

Each skill writes to its own `output/` folder:

- **Skill 01**, `aeo_scorecard.csv`/`.xlsx` (per-query × engine, 20-column scorecard), `aeo_report.pdf` (charts + prioritized actions + what's good vs bad), `aeo_executive_summary.md`, `raw/` (every API response for audit/re-analysis), `brand_profile.json`, `queries.json`.
- **Skill 02**, `aeo_content_recommendations.csv`/`.xlsx` (15-column per-query roadmap), `aeo_content_roadmap.pdf`, `aeo_content_executive_summary.md`, `website_pages/` (scraped markdown).
- **Skill 03**, `social_listening.csv`/`.xlsx` (13-column engagement queue), `social_listening_report.pdf`, `social_listening_executive_summary.md`, `discovery_plan.json`, `serp_results.jsonl`, `classified_results.jsonl`.
