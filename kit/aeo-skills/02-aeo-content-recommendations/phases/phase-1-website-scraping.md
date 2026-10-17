# Phase 1, Website scraping

**Goal:** end the phase with `output/website_pages/` containing one clean markdown file per page on the brand's site, plus `output/website_pages/_index.json` cataloging every file (URL, title, word count, page type, UGC flag).

Phase 2 reads this folder. If the scrape is incomplete or messy, every recommendation downstream will be wrong.

## Two crawl modes

The script picks automatically:

| Mode | Trigger | Why |
|---|---|---|
| **Apify** | `APIFY_TOKEN` env var is set | Uses the `apify/website-content-crawler` actor. Renders JavaScript, follows sitemaps, returns clean markdown out of the box, handles SPAs and modern frameworks. Strongly preferred for any non-trivial site. |
| **Local** | No `APIFY_TOKEN` | Uses `requests + beautifulsoup4 + readability-lxml` with a polite concurrent fetcher and sitemap-aware URL discovery. Works for static / SSR sites; misses content that requires JS execution. |

Both modes produce the same on-disk shape so Phase 2 cannot tell which was used.

## Steps

1. **Run the scraper:**
 ```bash
 python scripts/scrape_website.py "<URL>" \
 --max-pages 250 \
 --max-depth 4 \
 --include-subdomains false \
 --out-dir output/website_pages/
 ```
 - `--max-pages` caps the total page count (default 250). Most B2B sites fit comfortably; ecommerce or large blogs may need 500+.
 - `--max-depth` limits how many link-hops from the homepage to follow. Default 4 covers most marketing sites.
 - `--include-subdomains` set to `true` if the brand's blog or docs lives on a subdomain (e.g., `blog.acme.com`).
 - `--respect-robots true` (default) honors `robots.txt`; only set false when the user explicitly asks (and owns the site).

2. **Watch the progress output**:
 ```
 Mode: apify actor: apify/website-content-crawler
 Discovered 188 URLs from sitemap.xml
 Crawling ... 50/188 ok=49 fail=1
 Crawling ... 100/188 ok=98 fail=2
 ...
 Done. 184 pages saved, 4 failed.
 Page-type breakdown: marketing=42 blog=98 product=12 pricing=1 customer-story=8 legal=5 other=18
 UGC pages flagged: 7 (testimonials, reviews), excluded from edit-target list
 ```

3. **Review `output/website_pages/_index.json`** before moving on. The index is the single source of truth for Phase 2:
 ```json
 {
 "homepage": "https://acme.com",
 "scraped_at": "2026-04-27T12:34:00Z",
 "mode": "apify",
 "page_count": 184,
 "pages": [
 {
 "id": "p001",
 "url": "https://acme.com/",
 "path_md": "p001__home.md",
 "title": "Acme, Real-time customer feedback for product teams",
 "h1": "Real-time customer feedback for product teams",
 "meta_description": "...",
 "page_type": "marketing",
 "is_ugc": false,
 "word_count": 412,
 "h2_headings": ["Why Acme", "Built for product teams", "Customers"],
 "internal_links_out": 27,
 "external_links_out": 3,
 "scraped_ok": true
 },
 ...
 ]
 }
 ```

## Per-page markdown structure

Every `output/website_pages/<id>__<slug>.md` file follows this exact template (Phase 2 parses it):

```markdown
---
url: https://acme.com/features/in-app-surveys
title: In-app surveys for SaaS, Acme
h1: In-app surveys built for product velocity
meta_description: Trigger micro-surveys at the moment users hit a friction point...
page_type: product
is_ugc: false
scraped_at: 2026-04-27T12:34:56Z
internal_links_out:
 - https://acme.com/features
 - https://acme.com/integrations/slack
external_links_out:
 - https://en.wikipedia.org/wiki/Net_promoter_score
---

# In-app surveys built for product velocity

## What it does
[clean prose, headings preserved, lists preserved]

## How it works
1. ...
2. ...
```

The frontmatter carries machine-readable metadata; the body is human-readable markdown with original heading hierarchy and list structure preserved.

## Page-type classification heuristics

The scraper assigns a `page_type` so Phase 2 can prefer the right kind of page for each recommendation. Heuristics:

| URL pattern + content cue | Type |
|---|---|
| `/`, `/home`, hero + CTA + nav | `marketing` |
| `/blog/...`, `/articles/...`, byline + date | `blog` |
| `/features/...`, `/product/...`, `/platform/...` | `product` |
| `/pricing` | `pricing` |
| `/customers/...`, `/case-studies/...`, `/stories/...` | `customer-story` |
| `/about`, `/team`, `/careers` | `company` |
| `/docs/...`, `/help/...`, `/support/...` | `docs` |
| `/legal/...`, `/privacy`, `/terms` | `legal` |
| `/vs/...`, `/compare/...` or page title contains " vs " | `comparison` |
| review-rich content (testimonials block, schema.org Review markup) | `ugc` (also sets `is_ugc: true`) |
| anything else | `other` |

Phase 2 **never recommends modifying `is_ugc: true` pages.** It can recommend linking *to* them, never editing them.

## Quality bar before exiting Phase 1

- ≥ 90% scrape success rate (`scraped_ok: true` on at least 90% of discovered URLs)
- Homepage successfully scraped (this is non-negotiable; if it fails the brand voice signals are missing for Phase 2)
- At least one of each page_type that the homepage navigation links to (e.g., if `/pricing` exists in the nav, it must be in the index)
- `internal_links_out` populated on every page (used by Phase 2 to suggest internal-link targets)
- No empty markdown bodies (a 200 OK with 0 words usually means JS-only rendering, switch to Apify mode)

## Common pitfalls

- **Ignoring the sitemap.** Without sitemap discovery, the local crawler depends on link-following and misses orphan pages. Both modes try `<url>/sitemap.xml` and `<url>/sitemap_index.xml` first.
- **Subdomains forgotten.** Many blogs live on `blog.<brand>.com` or `<brand>.help`. Ask the user; if yes, set `--include-subdomains true`.
- **Headless rendering needed.** SPAs rendered with React/Vue/Angular without SSR will look like 50-word stubs to the local crawler. Switch to Apify mode (or warn the user to set `APIFY_TOKEN`).
- **Crawling marketing pages in a different language.** Many sites have `/de/`, `/es/` folders; if the brand's primary market is one language, restrict via `--language en` (default) so the index isn't 80% non-English content.
- **Rate-limiting on small sites.** Local mode uses `--concurrency 4` by default and a 0.4s polite delay; turn this down on tiny sites or up if the user owns the site.

## Output contract

```
output/website_pages/
├── _index.json
├── p001__home.md
├── p002__features.md
├── p003__pricing.md
├── p004__features-in-app-surveys.md
├── ...
```

Phase 2 reads `_index.json` first to plan which pages to load per query, then reads only the markdown files it actually needs.
