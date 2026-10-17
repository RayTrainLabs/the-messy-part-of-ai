# SEO + AEO best practices (the rules embedded in the prompt)

Reference for what "good" looks like in every recommendation. The system prompt sent to the judge LLM enforces these. This doc is the human-readable version for tuning.

## SEO essentials

| Practice | Why |
|---|---|
| Use target keywords naturally in title, H1, first paragraph, and 1 to 2 H2s | Google still rewards keyword presence in semantically obvious places |
| Maintain clear H1 → H2 → H3 hierarchy | Crawlers and LLMs both extract structure from headings |
| Keep paragraphs short (2 to 4 sentences) | Improves scan-ability for both readers and answer engines |
| Include 2 to 4 internal links per section | Distributes authority, helps crawlers find related content |
| Add 1 to 3 external links to authoritative sources | Builds credibility, satisfies E-E-A-T expectations |
| Optimize the meta description (~155 chars, includes keyword) | Affects click-through from SERPs |
| Use semantic HTML where possible (lists, tables, definitions) | Easier for engines to parse |

## AEO essentials

Answer Engine Optimization, what makes content **citable** by ChatGPT, Perplexity, Claude, Gemini, and Google AI Overviews.

| Practice | Why |
|---|---|
| Format key headers as questions ("What is …?", "How to …?", "Why …?") | LLMs use question-shaped headings as answer anchors |
| First 1 to 2 sentences after a question are the direct answer (40 to 60 words) | Voice / snippet capture; LLM extraction prefers the first plausible answer |
| Use numbered lists for steps and processes | Ordered lists are recognized as procedural answers |
| Use bulleted lists for features, options, comparisons | Unordered lists are recognized as set answers |
| Include comparison tables for vs / alternative queries | Tables are extractable as comparison facts |
| Provide quantified facts where possible ("response rate 23% higher than industry mean of 8%") | Citable statistics are linked back to the source page |
| Keep brand-name variants consistent | Alias confusion fragments mention counts |
| Add structured data (FAQ, HowTo, Product, Article) | Schema is read by some answer engines as ground truth |
| State your sources inline (link to data, studies, primary sources) | Demonstrates the page is grounded, increases citability |
| Include a TL;DR or key-takeaways block at the top | Often extracted verbatim by AI overview features |
| Keep canonical URLs stable | Changing URLs breaks accumulated citation patterns |

## Internal linking pattern

For every recommendation:

- Identify 2 to 4 **existing** pages to link to (Phase 2 has the page index, never invent URLs).
- Use natural anchor text containing target keywords (not "click here", not the bare URL).
- Link to pages that **add value or context** for the reader, not just topically adjacent pages.
- Prefer linking to product / pricing / features pages from informational content (drives the buying funnel).
- Prefer linking to blog / guide / case-study content from product pages (drives credibility).

## External linking pattern

- 1 to 3 authoritative external sources per recommendation.
- Allowed sources: Wikipedia, NNGroup / Nielsen Norman, GOV / EDU domains, peer-reviewed papers, industry standards (W3C, IETF, etc.), well-established trade publications, primary research from credible organizations.
- **Disallowed**: competitors' marketing pages, generic content farms, pages without clear authorship.
- Never link out from the highest-converting product / pricing pages (those should keep the reader on-domain), only from blog / guide content.

## Brand-voice rules

- The judge LLM is given:
 - `brand_profile.json` (one_liner, positioning, tone notes)
 - 1 to 2 voice samples from the scraped homepage and about page
- Recommendations must:
 - Match the existing site's tone (formal vs. conversational, hedged vs. assertive, dry vs. playful)
 - Use the brand's preferred terms ("customers" vs. "clients" vs. "users", "platform" vs. "tool" vs. "app")
 - Avoid phrases the brand demonstrably never uses ("synergy", "leverage", "world-class" if absent from the existing copy)
- A common failure mode is generic SaaS-marketing prose; the prompt explicitly anchors voice to the homepage samples to prevent this.

## What never to do

- **Never recommend writing on a UGC page.** Testimonials, customer reviews, forum content, comments, the user owns these via their customers, not as editable copy.
- **Never invent URLs.** Internal links must come from the page index. Proposed `target_page` for `new_article` must be on the brand's domain and explicit about being new.
- **Never recommend duplicating existing content.** If a partial-coverage page exists, the recommendation is `section_addition` or `minor_optimization`, not `new_article`.
- **Never recommend changes that contradict the brand's positioning.** If the brand profile says "SMB-focused", do not recommend enterprise-targeted content (and vice versa).
- **Never write in a voice the brand doesn't use.** Match samples from the scraped homepage, not generic SEO copywriting.
- **Never recommend keyword stuffing.** Two natural mentions beat eight unnatural ones.
- **Never recommend external links to competitors' marketing pages.**

## What "expected_result" should describe

Every recommendation includes `expected_result`. It is **not** "more traffic". It is a specific, falsifiable visibility outcome:

| Bad | Better |
|---|---|
| "More traffic" | "Featured-snippet capture for 'best in-app feedback tool' query within 8 to 12 weeks" |
| "Better SEO" | "Acme starts surfacing in 2 to 3 of 5 LLM answers for category-C decision queries within one month of indexing" |
| "Improved authority" | "Comparison page captures the 'Pendo alternatives' SERP from position 11 → 1 to 3 within 12 weeks" |

The test: could you measure whether the result happened by re-running skill 01 in 8 weeks? If no, the wording is too vague.
