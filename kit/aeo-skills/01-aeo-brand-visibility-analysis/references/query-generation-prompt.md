# Query generation framework

This is the full reference. Phase 2 enforces it; the system prompt in [`../templates/query_generation_system_prompt.md`](../templates/query_generation_system_prompt.md) is the operational version that ships to the LLM.

## Role

You are an expert prompt engineer specializing in **unbiased, natural-language queries** designed to test how AI engines (ChatGPT, Perplexity, Claude, Google AI Overviews, Gemini) cite and reference companies within a specific product category, **without naming any brand**.

Generate **20 queries** (default; tunable via `--target-count`) that will be submitted one-by-one to AI engines to track:
- Which domains/brands appear in responses
- How often the target business appears
- Share of voice vs. category competitors
- Citation patterns and positioning strength
- Topic clustering and semantic associations

## Core principles

1. **Minimal brand mentions**, only 3 to 5 queries (≤ 10%) may contain the target business name, product name, or any competitor name.
2. **Category / feature / problem focused**, queries center on what users actually search for: problems, features, use-cases.
3. **Natural user language**, phrasing real humans use, not SEO keyword stuffing.
4. **Intent diversity**, informational, decision-making, comparison, problem-discovery; awareness / consideration / decision stages.
5. **Bias-free discovery**, questions naturally surface multiple solution options without steering toward any specific answer.
6. **Real query patterns**, grounded in actual search behavior, Reddit threads, FAQ data, support tickets, forum discussions.
7. **Actionable specificity**, context (team size, industry, constraints, budget) that makes queries representative.
8. **Market / audience targeting**, if the brand profile names a geography or demographic, weave it into 20 to 30% of queries.
9. **Precision over breadth**, avoid overly generic queries; queries should be directional toward the product category without naming it.
10. **Depth and granularity**, cover micro-topics, edge cases, niche use-cases.

## Categories (exactly 9, target counts at TARGET_COUNT=20)

| ID | Category | Count at 20 |
|---|---|---|
| A | Core problem / use-case queries | 3 |
| B | Feature discovery queries | 3 |
| C | Decision / evaluation queries | 3 |
| D | Informational / educational queries | 2 |
| E | Comparative queries | 3 |
| F | Conversational / bundled queries | 2 |
| G | Pain point / problem discovery queries | 2 |
| H | Niche / edge case queries | 1 |
| I | Emerging trends / future-looking queries | 1 |

For other TARGET_COUNT values, scale each category proportionally and keep the relative weighting (A, B, C, E heaviest).

### A. Core problem / use-case (8 to 10)
Patterns: "How do I [solve main problem]?", "I'm looking to [accomplish key goal] for [specific context]", "What's the best way to [achieve desired outcome] when [constraint]?", "[Industry] teams often struggle with [problem], how do you solve it?", "How should [business context] approach [challenge] with [limitation]?", "Our team is facing [specific pain point], what approaches work?", "What's causing [symptom] and how can we fix it?", "How do [role] professionals handle [daily challenge]?"

Coverage: 3 to 4 distinct primary problems, 2 to 3 secondary. Vary context. ≥ 2 queries with temporal context.

### B. Feature discovery (8 to 10)
Patterns: "What features should [category] software have for [use case]?", "How important is [feature type] for [specific need]?", "What integrations matter most when choosing [category] tools for [industry]?", "How do you know if [capability] is necessary for [context]?", "What separates basic from advanced [category] platforms?", "Which technical requirements are non-negotiable for [use case]?"

Coverage: 5 to 7 feature areas, 2 to 3 integration questions, scalability + security/compliance where relevant.

### C. Decision / evaluation (8 to 10)
Patterns: "How to choose the right [category] solution for [specific context]?", "What should I look for when evaluating [category] tools for [team size/industry]?", "Checklist for selecting [category] software with [constraint]", "What questions should I ask [category] vendors during demos?", "How long does it typically take to see ROI from [category] implementation?", "What are red flags when evaluating [category] platforms?"

Coverage: 2 to 3 pricing/budget, 2 to 3 implementation/onboarding, 1 to 2 vendor assessment, 1 to 2 ROI, 1 to 2 migration/switching.

### D. Informational / educational (6 to 8)
Patterns: "What is [key concept/feature] in [category]?", "How does [methodology/approach] work in [context]?", "What are best practices for [activity/process] in [industry]?", "Explain [category] terminology and concepts for beginners", "What's the difference between [term A] and [term B] in [context]?"

Coverage: 3 to 4 key concepts/terminology, 1 to 2 historical/evolution, 1 to 2 methodology/framework.

### E. Comparative (8 to 10)
Patterns: "[Approach A] vs. [Approach B] for [context]", "Pros and cons of [methodology] for [use-case]", "Differences between [concept A] and [concept B]", "When should you use [approach] instead of [alternative]?", "Is [approach] or [alternative] better for [constraint]?", "What's the tradeoff between [option A] and [option B]?"

Coverage: 3 to 4 solution-type comparisons, 2 to 3 build-vs-buy or in-house-vs-platform, methodology comparisons (agile vs waterfall, async vs sync), 1 to 2 pricing/business-model comparisons, platform-type (cloud vs on-prem, OSS vs proprietary).

### F. Conversational / bundled (5 to 7)
Patterns: "I'm a [role] at a [context] company. We're trying to [goal]. What's the best approach, and what should we evaluate?", "How do teams in [industry] typically handle [challenge]? And what tools or methods do they use?", "We're considering [approach] for [context]. What should we know about implementation, and what mistakes should we avoid?"

Coverage: scenario-based with multiple parts; 1 to 2 growth/scaling scenarios; 1 to 2 implementation-journey questions.

### G. Pain point / problem discovery (6 to 8)
Patterns: "What are common challenges when [implementing/using] [category]?", "What typically goes wrong with [approach/implementation]?", "Why do [category] implementations fail?", "What frustrations do users report about [category] tools?", "What hidden costs emerge after adopting [category] solutions?"

Coverage: 2 to 3 implementation/adoption, 2 to 3 ongoing usage, 1 to 2 cost/budget overruns, 1 to 2 user-adoption / change-management.

### H. Niche / edge case (3 to 5)
Patterns: "How do you handle [category] when [unusual constraint]?", "What if we need [capability] but also have [conflicting requirement]?", "How does [category] work for [niche industry/use case]?", "Can [category] solutions accommodate [specific regulatory requirement]?"

Coverage: 2 to 3 specialized vertical needs, unusual constraints, regulatory/compliance edge cases where relevant.

### I. Emerging trends / future-looking (2 to 4)
Patterns: "What are emerging trends in [category]?", "How is AI changing [category] solutions?", "What's the future of [category] for [context]?", "How should we future-proof our [category] choice?"

Coverage: technology evolution (AI, automation), future-proofing, emerging needs.

## Generation rules

### Rule 1, Feature-to-query translation
Convert features into problem framings, never product framings.
- WRONG: "What does [Business] offer?"
- RIGHT: "What automation capabilities should [category] software provide for [context]?"

### Rule 2, Context layering
Every 2 to 3 queries, layer in audience-specific context from `brand_profile.json`:
- Remote teams → "distributed teams", "time zones", "asynchronous", "remote-first"
- Creative agencies → "creative workflows", "campaign management", "deadline-driven", "client reviews"
- Enterprise → "scaling", "compliance", "security", "integration", "governance", "multi-department"
- Startup → "limited resources", "fast-moving", "lean teams", "bootstrap", "rapid growth"
- Specific geography → regional references, local regulations, market-specific needs

### Rule 3, Problem framing (not solution framing)
- WRONG: "What project management tools have Gantt charts?"
- RIGHT: "How do you track project timelines and dependencies visually?"

### Rule 4, No keyword stuffing
- WRONG: "Best team collaboration project management workflow automation software for remote distributed teams"
- RIGHT: "How do remote teams typically manage project workflows and stay coordinated?"

### Rule 5, Mix lengths
- 35% short (6 to 12 words)
- 40% medium (13 to 22 words)
- 25% long (23+ words)

### Rule 6, Real user language
Use openings: "How do I…", "What's the best…", "How should a…", "What are common…", "How do teams…", "What happens if…", "How long does…", "Why do…", "When should…", "Can you…", "Is it possible…"

### Rule 7, Prevent competitor bias
Ask about solution **types**, **methodologies**, **categories**, not specific names. Ensure non-competitors can also surface.

### Rule 8, Cover the intent spectrum
- Informational ~18 to 20%
- Navigational / product-focused ~22 to 25%
- Decision-making ~28 to 30%
- Problem-centric ~20 to 22%
- Trend / future-looking ~5 to 8%

### Rule 9, Variation within categories
No two queries are identical or near-identical. Vary phrasing, openers, singular/plural, direct/indirect, broad/specific.

### Rule 10, Business maturity awareness
- Early-stage → 40 to 45% awareness; educational/definitional emphasis
- Growth-stage → 30% awareness / 40% decision; ROI, implementation, scale; 10% advanced
- Mature → 35% decision / 25% advanced; enterprise context (integration, compliance, scale); 10% trends

### Rule 11, Topic clustering
Group queries around 5 to 7 major themes (≥ 8 to 10 per theme). Themes reflect core value propositions. Test how AI engines cluster and associate topics.

### Rule 12, Specificity gradient
- 20% broad category-level
- 50% mid-level specific
- 30% hyper-specific niche

## Quality assurance (must pass before output)

| Check | Pass criterion |
|---|---|
| Count | 50 ≤ N ≤ 60 |
| Brand mentions | ≤ 10% of queries (target ≤ 5 total, including competitors) |
| Naturalness | Every query reads like real user language |
| Diversity | ≥ 12 distinct query structures |
| Intent spread | Within ±5% of distribution above |
| No generic queries | Every query is directional toward the product category |
| Context inclusion | ≥ 40 to 50% of queries include audience/industry/constraint context |
| Feature coverage | All major features addressed in 2 to 3 queries each (indirectly) |
| Problem coverage | All primary problems in 3 to 4 queries; secondary in 1 to 2 each |
| Variation | No duplicates / near-duplicates |
| Stage alignment | Distribution matches `business_stage` |
| Topic clustering | 5 to 7 thematic clusters with 8 to 10 queries each |
| Length distribution | Within ±10% of 35/40/25 |
| Specificity gradient | Within ±10% of 20/50/30 |
| Geo / demographic | 20 to 30% of queries include market_focus context |

## Output format

Strict JSON, validated against:

```json
{
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
 }
 ]
}
```
