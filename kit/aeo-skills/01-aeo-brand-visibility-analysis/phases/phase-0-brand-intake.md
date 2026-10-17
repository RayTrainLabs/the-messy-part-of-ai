# Phase 0, Brand intake

**Goal:** end the phase with a structured `output/brand_profile.json` and human-readable `output/brand_profile.md` that capture everything later phases need: brand name, one-line positioning, ICP, segments, demographics, product overview, core problem solved, key features, direct + indirect competitors, geographic / market focus, business maturity stage.

Nothing in later phases works correctly if this is wrong. Take time here.

## Decision tree

```
Is brand documentation supplied (paths, pasted text, or already in workspace)?
├── YES → READ_DOCS path
└── NO → Is a brand URL supplied?
 ├── YES → CRAWL_SITE path
 └── NO → ASK_USER path
```

### READ_DOCS path

1. Read every supplied document end-to-end. Do not skim. Common files:
 - `*ICP*`, `*persona*`, `*audience*`, `*segment*`
 - `*brand*`, `*positioning*`, `*messaging*`, `*voice*`
 - `*product*`, `*features*`, `*roadmap*`
 - `*marketing*`, `*GTM*`, `*launch*`
 - `*competitor*`, `*battlecard*`, `*landscape*`
2. Extract:
 - Brand name, one-line description, longer-form positioning
 - Customer segments (B2B/B2C, role, company size, industry, region)
 - Primary persona(s) and demographics
 - Product overview, core problem solved, top features (5 to 10)
 - Stated competitors (direct + indirect)
 - Geographic / language focus
 - Business stage (early / growth / mature), infer if not stated
3. **If competitors are missing or look incomplete (< 3 direct competitors):** also run the CRAWL_SITE path against the brand's website (if URL is known or extractable from the docs) to look for "vs" pages, comparison content, or category mentions that surface the competitor set. If still incomplete, you may also use a web search.
4. **If product features are vague or absent:** crawl the brand's website (especially `/features`, `/product`, `/platform`, `/pricing`) to fill in.

### CRAWL_SITE path

1. Run the brand-context fetcher to get a fresh snapshot:
 ```bash
 python scripts/fetch_brand_context.py "<URL>" \
 --max-pages 12 \
 --out output/brand_raw.json
 ```
2. Read `output/brand_raw.json`. The fetcher captures homepage, about, product, pricing, customers, contact pages by anchor-text heuristic.
3. Synthesize the same fields as READ_DOCS from the crawled content. Pay particular attention to:
 - **Hero / H1 / meta description**, usually the cleanest positioning
 - **About / Our story page**, voice samples, founding context
 - **Product / features pages**, feature list
 - **Customers / case studies**, segments, industries, deal sizes (signals enterprise vs. SMB vs. mid-market)
 - **Pricing page**, often signals SMB vs. enterprise focus
4. **For competitors:** crawl is unlikely to yield them. Run a web search for `"<brand> vs"`, `"alternatives to <brand>"`, and `"<category> tools"` (where category is inferred from positioning). Compile a candidate list of 5 to 10 and present it to the user for trim/confirmation in Phase 1.

### ASK_USER path

If neither docs nor URL are available, ask exactly these questions in one message (do not split into a long back-and-forth):

> I need a few quick details to run the AEO audit. Please share:
>
> 1. **Brand name and a one-line description** of what you sell.
> 2. **Who buys it?**, primary customer segment(s), role/title, industry, company size, geography.
> 3. **What problem does it solve?**, the core pain point a buyer would describe in their own words.
> 4. **Top 5 to 7 features or capabilities**, what users actually do with the product.
> 5. **Direct + indirect competitors**, names of products/companies a buyer would consider alongside yours. If you're not sure of the indirect ones, list what they'd use today instead (a spreadsheet, in-house tool, manual process, etc.).
> 6. **Any geographic or demographic focus**, e.g., "US mid-market", "EU enterprise", "global remote teams". If global / no focus, say so.
> 7. **Business stage**, early-stage (< $1M ARR), growth-stage ($1M to $50M), or mature ($50M+).

Synthesize their answers into the same structured profile.

## Output contract

Write **two** files at the end of Phase 0:

### `output/brand_profile.json` (machine-readable, consumed by every later phase)

```json
{
 "brand_name": "Acme",
 "brand_aliases": ["Acme Inc", "Acme.AI"],
 "url": "https://acme.com",
 "one_liner": "Real-time customer feedback for product teams",
 "positioning": "...",
 "icp": {
 "primary_persona": "Head of Product at B2B SaaS",
 "company_size": "50-500 employees",
 "industry": ["B2B SaaS", "Enterprise software"],
 "geography": ["US", "EU", "ANZ"],
 "buying_committee": ["Head of Product", "VP Engineering", "Customer Success Lead"]
 },
 "segments": [
 {"name": "Mid-market SaaS", "share": "primary"},
 {"name": "Enterprise SaaS", "share": "secondary"}
 ],
 "product": {
 "overview": "...",
 "core_problem": "Product teams have no fast feedback loop between shipping a feature and knowing if customers love or hate it.",
 "features": [
 "In-app micro-surveys",
 "Session replay clip linking",
 "Slack alerts on negative sentiment",
 "..."
 ]
 },
 "competitors": {
 "direct": ["Sprig", "Pendo", "FullStory"],
 "indirect": ["Typeform + Mixpanel combo", "Intercom feedback module", "Internal dashboards"]
 },
 "market_focus": {
 "geo": ["US", "EU"],
 "demographic_notes": "B2B SaaS product teams, often distributed/remote"
 },
 "business_stage": "growth-stage",
 "category": "Product feedback / experience analytics",
 "source": "supplied-docs | crawled-site | user-provided",
 "intake_date": "2026-04-27"
}
```

### `output/brand_profile.md` (human-readable, used in Phase 1)

Same content, rendered as a markdown report a non-technical stakeholder can skim and edit. Include a final section called **"Open questions"** listing anything the skill could not confidently determine and is asking the user to confirm.

## Quality bar before exiting Phase 0

- Brand name + one-liner are written in the brand's own voice (or a faithful paraphrase), not jargon
- `brand_aliases` includes any names buyers / AI engines might use that differ from the canonical `brand_name` (legal entity name, common abbreviations, formerly-known-as, parent company, "Acme.AI" vs "Acme")
- ICP has at least: primary persona, company size band, geography, 1 to 3 industries
- At least 5 features listed (specific, not "features include X, Y, Z")
- Competitors list has **≥ 3 direct AND ≥ 2 indirect** (exception: very early-stage brands may have only 1 to 2 direct, in that case explicitly note this in the "Open questions" section)
- Geographic and stage fields filled (these drive query-generation rules in Phase 2)
- If anything is uncertain, it is explicitly listed in "Open questions" rather than guessed

## Common pitfalls

- **Treating the marketing-page tagline as the ICP.** Read multiple pages; the homepage hero is often aspirational, the customers/case-studies page is the truth.
- **Inferring competitors from "vs." blog posts written by the brand itself.** These tend to be selectively flattering. Treat them as candidates, validate in Phase 1.
- **Missing the indirect competition.** AI engines often surface "use a spreadsheet", "use Notion + Zapier", or vertical-specific tools as alternatives. The audit will look weak if these aren't on the competitor list.
- **Over-broad category.** "B2B software" is not a category; "product feedback platforms" is. The narrower the category, the sharper the queries in Phase 2.
