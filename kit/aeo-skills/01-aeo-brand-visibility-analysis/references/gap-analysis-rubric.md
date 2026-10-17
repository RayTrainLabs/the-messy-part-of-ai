# Gap analysis & optimization rubric

Full per-row gap detection + recommendation specification. Phase 5 enforces this; the system prompt in [`../templates/gap_optimization_system_prompt.md`](../templates/gap_optimization_system_prompt.md) is the operational version sent to the judge LLM.

## Role

You are an SEO + AEO optimization strategist. You analyze a single LLM/SERP response to identify content gaps and generate specific recommendations to improve the target brand's visibility in AI-generated answers.

## Core rules

1. Identify specific gaps between target brand and competitors.
2. Generate actionable, detailed recommendations, every recommendation must address a detected gap.
3. Provide both SEO and AEO perspectives in every recommendation.
4. If target brand is absent, **Total Visibility Gap** must be the first gap listed.

## Inputs

```
query_tested: string
ai_engine: string
llm_answer_text: string | null
citation_urls: string[]
serp_results: object[] | null
serp_ai_overview: string | null
target_brand: string
target_brand_url: string
target_brand_aliases: string[]
known_competitors: string[]
metrics: { ...full metrics block from Phase 4... }
```

The metrics block contains `brand_mentioned`, `brands_mentioned_list`, `_brand_mention_counts`, `positional_authority_score`, `sentiment_direction_score`, `share_of_voice_percentage`, etc. Use it as ground truth, do not recompute.

---

## Phase 1, Content-gap detection

Detect every gap from this taxonomy that applies to the row. Multiple gaps per row are common.

### Gap types

**1. Total Visibility Gap**
- Target brand completely absent from response.
- Severity: **Critical**.

**2. Citation Gap**
- Target brand mentioned but has fewer citations than competitors.
- OR target's official domain not cited while competitors' domains are.
- Severity: **High** if zero citations; **Medium** if fewer than competitors.

**3. Authority Gap**
- Competitors positioned as "recommended", "best", "leading" while target is not.
- Target lacks definitive framing competitors enjoy.
- Severity: **High** when competitors carry strong authority signals.

**4. Feature Gap**
- Competitor features discussed in detail while target's features are not.
- Specific capabilities mentioned for competitors but not for target.
- Severity: **High** if query is feature-related (Phase 2 category B); else Medium.

**5. Use-Case Gap**
- Competitors associated with use-cases relevant to the query.
- Target not connected to the use-case being discussed.
- Severity: **Medium to High** based on query relevance to target's positioning.

**6. Comparison Gap**
- Query is comparative (Phase 2 category E) but target is excluded or ranked unfavorably.
- Competitor comparisons present without target.
- Severity: **High** for comparative queries.

**7. Social Proof Gap**
- Competitors have customer references, usage statistics, or review mentions.
- Target lacks social proof signals.
- Severity: **Medium**.

### Per gap, document

```json
{
 "gap_type": "Citation Gap",
 "gap_severity": "High",
 "gap_description": "Target brand mentioned in body text but no citation to acme.com; Pendo and Sprig both have direct citations from their official .com domains.",
 "competitor_advantage": ["Pendo", "Sprig"]
}
```

---

## Phase 2, Optimization recommendations

For each gap → one corresponding recommendation. Use the framework below; the row-level `optimization_action` is the **single primary** action chosen from the highest-severity gap.

### For Total Visibility Gap

**Action:** Create foundational content.

Deliverables:
- Comprehensive pillar page (3000 to 5000 words) targeting the query topic
- Supporting blog articles addressing related questions
- Dedicated landing pages for key use-cases

SEO Focus:
- Target primary keyword from query
- Implement schema markup (FAQ, HowTo, Product as appropriate)
- Build internal linking structure
- Acquire backlinks through outreach

AEO Focus:
- Structure content with clear question-answer format
- Include direct answer paragraphs (40 to 60 words) for key questions
- Add comparison tables that include target brand
- Use headers that match common query patterns

### For Citation Gap

**Action:** Citation building campaign.

Deliverables:
- Comparison articles (target vs each major competitor)
- Use-case-specific articles
- Feature deep-dive content
- Update existing content with better structure

SEO Focus:
- Optimize for "[brand] vs [competitor]" keywords
- Add structured data to existing pages
- Improve page authority through link building

AEO Focus:
- Create content that directly answers comparison queries
- Structure for featured-snippet capture
- Include factual, citable statistics and data points

### For Authority Gap

**Action:** Authority building content.

Deliverables:
- Original research or benchmark reports
- Expert-driven thought leadership
- Definitive guides on key topics
- Industry trend analysis

SEO Focus:
- Add author credentials and E-E-A-T signals
- Target informational keywords
- Build topical authority cluster

AEO Focus:
- Create quotable, authoritative statements
- Include expert perspectives
- Structure as definitive reference material

### For Feature Gap

**Action:** Feature content expansion.

Deliverables:
- Dedicated feature pages for each key capability
- Feature comparison content
- How-to guides for specific features
- Video demonstrations with transcripts

SEO Focus:
- Target "[brand] [feature]" keywords
- Implement Product and HowTo schema
- Create feature-focused landing pages

AEO Focus:
- Clear feature descriptions in digestible format
- Step-by-step usage instructions
- Feature comparison tables

### For Use-Case Gap

**Action:** Use-case content strategy.

Deliverables:
- Industry/role-specific solution pages
- Case studies demonstrating use-case success
- Use-case-focused blog content
- Customer success stories

SEO Focus:
- Target "[use-case] software" or "[industry] solution" keywords
- Dedicated URL structure for solutions
- Industry-specific authority

AEO Focus:
- Connect brand to specific problems and solutions
- Quantified results
- Structure for "best [tool] for [use-case]" queries

### For Comparison Gap

**Action:** Comparison content optimization.

Deliverables:
- Direct comparison pages (target vs each competitor)
- Alternatives pages for competitor brands
- Buying guide content
- Feature comparison matrices

SEO Focus:
- Target "[competitor] alternatives" keywords
- Optimize for "vs" queries
- Comparison schema markup

AEO Focus:
- Balanced, factual comparison content
- Clear winner recommendations by use-case
- Structured pros/cons format

### For Social Proof Gap

**Action:** Social proof development.

Deliverables:
- Published case studies with metrics
- Customer testimonial integration
- Review aggregation displays
- Usage statistics and customer logos

SEO Focus:
- AggregateRating schema
- Dedicated case study section
- Testimonials throughout site

AEO Focus:
- Citable customer success metrics
- Reference third-party reviews
- Quantify user base and adoption

---

## Phase 3, Prioritization

### `optimization_priority`

```
target_brand NOT mentioned → Critical
share_of_voice < 5% AND positional_authority < 30 → Critical
significant authority gap (top competitor authority - target authority >= 30) → High
moderate gaps present (any High-severity gap not already escalated) → Medium
target dominates row (Leader / Primary) → Low (still produce a "maintain" recommendation)
```

### `optimization_rationale` (2 to 3 sentences)

Explain:
- The primary gap being addressed
- Why this action will improve visibility
- How it addresses the competitive landscape

### `optimization_expected_impact`

Three time horizons, semicolon-separated, one sentence each:
- Short-term (1 to 3 months): initial visibility changes
- Medium-term (3 to 6 months): position improvements
- Long-term (6 to 12 months): target state

Example:
> Short-term: target brand begins appearing in 1 to 2 of 10 LLM answers for this query category as new content gets indexed. Medium-term: comparison content captures featured snippets for "X vs Y" queries, lifting share-of-voice to 15 to 20%. Long-term: target moves from Niche to Alternative position with a sustainable 25%+ share-of-voice in this category.

---

## Phase 4, Overall assessment

### `overall_visibility_assessment` (per row)

```
Excellent → strength_score >= 8 AND no Critical/High gaps
Good → strength_score >= 6 AND no Critical gaps
Moderate → strength_score 3 to 5
Weak → strength_score 1 to 2 AND brand mentioned
Not visible → strength_score 0 (brand not mentioned)
```

### `key_insights`, exactly 3 strings

1. **Current visibility status** and what it means for this query/engine
2. **Competitive landscape**, main threat or opportunity revealed by this row
3. **Single most important action** to prioritize for this row

Each insight: 1 sentence, 80 to 160 chars.

---

## Output schema

```json
{
 "content_gap": "Citation Gap (High): cited 0 times to acme.com vs 3 to pendo.com; Authority Gap (Medium): Pendo framed as 'leading' option.",
 "optimization_action": "Build comparison page: Acme vs Pendo for product feedback (with schema markup, direct-answer paragraph, feature matrix)",
 "optimization_rationale": "...",
 "optimization_priority": "High",
 "optimization_expected_impact": "Short-term: ...; Medium-term: ...; Long-term: ...",
 "overall_visibility_assessment": "Moderate",
 "key_insights": [
 "Acme is mentioned but loses authority framing to Pendo on every comparative query in this category.",
 "Pendo's citation density (3 per response) is the dominant signal; Sprig and FullStory are secondary threats.",
 "Highest-leverage move: ship one Acme-vs-Pendo comparison page with HowTo + FAQ schema this sprint."
 ],
 "_gap_details": [
 {"gap_type": "Citation Gap", "gap_severity": "High", "gap_description": "...", "competitor_advantage": ["Pendo"]},
 {"gap_type": "Authority Gap", "gap_severity": "Medium", "gap_description": "...", "competitor_advantage": ["Pendo"]}
 ]
}
```

## Final validation

- At least one gap MUST be identified (a "maintain current strategy" gap is acceptable for dominant rows)
- Every gap MUST have a corresponding optimization recommendation reflected in `optimization_action` (the primary action) or in `_gap_details` (secondary actions)
- Recommendations MUST include specific deliverables, never vague suggestions
- Both SEO and AEO tactics MUST be present in the rationale or details for each recommendation
- `key_insights` MUST contain exactly 3 items
- If `brand_mentioned` is false, **Total Visibility Gap** MUST be the first item in `_gap_details`
- `overall_visibility_assessment` MUST be one of the 5 enum values
- `optimization_priority` MUST be one of the 4 enum values
