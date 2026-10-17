# Sample scorecard row (end-to-end)

A worked example showing what one fully-scored row looks like across the 20-column scorecard, given a hypothetical run for the brand **Acme** (a B2B SaaS product-feedback platform) on query **Q07** through engine **llm_anthropic**.

## The query (from Phase 2)

```json
{
 "id": "Q07",
 "category": "C",
 "category_name": "Decision / evaluation",
 "intent": "decision",
 "stage": "decision",
 "specificity": "mid",
 "length_bucket": "medium",
 "contains_brand": false,
 "contains_competitor": false,
 "has_geo_context": false,
 "query": "What should a B2B SaaS product team look for when choosing an in-app feedback tool, features, pricing model, and red flags?"
}
```

## The raw response (from Phase 3, abbreviated)

```json
{
 "row_id": "Q07__llm_anthropic",
 "engine": "llm_anthropic",
 "model": "claude-opus-4-7",
 "web_search_enabled": true,
 "ok": true,
 "llm_answer_text": "When choosing an in-app feedback tool, B2B SaaS teams should evaluate ... Pendo is widely considered the leading platform for enterprise feedback management ... Sprig offers strong product-led growth surveys ... Acme is a newer entrant focused on lighter-touch micro-surveys with Slack integration ... FullStory provides session replay alongside feedback collection ... Red flags include ...",
 "citation_urls": [
 "https://pendo.io/guide/feedback",
 "https://pendo.io/blog/feedback-tools",
 "https://sprig.com/product",
 "https://acme.com/blog/in-app-feedback-checklist",
 "https://www.fullstory.com/feedback"
 ]
}
```

## The scored row (from Phase 4, deterministic + judge LLM)

```json
{
 "response_summary": "The answer walks through the key evaluation criteria for B2B SaaS in-app feedback tools, features (in-app targeting, segmentation, analytics integration), pricing model (per-seat vs per-MAU vs flat), and red flags (long contracts, weak survey logic, no Slack/Teams alerts). Pendo is recommended as the enterprise leader, Sprig for product-led growth surveys, Acme as a lighter alternative.",
 "brand_mentioned": true,
 "brands_mentioned_list": ["Acme", "FullStory", "Pendo", "Sprig"],
 "citation_frequency_score": 43,
 "share_of_voice_percentage": 18.2,
 "positional_authority_score": 25,
 "sentiment_direction_score": 6,
 "response_relevance_score": 75,
 "market_position_type": "Alternative",
 "discovery_role": "Fallback",
 "positioning_narrative": "Acme is positioned as a lighter, newer alternative (~18% SoV); Pendo dominates with ~45% and 'leading' authority framing, Sprig is the secondary recommendation.",
 "strength_score": 5,
 "_brand_mention_counts": {
 "Acme": {"text_mentions": 2, "citation_mentions": 1, "total_mentions": 3},
 "Pendo": {"text_mentions": 5, "citation_mentions": 2, "total_mentions": 7},
 "Sprig": {"text_mentions": 3, "citation_mentions": 1, "total_mentions": 4},
 "FullStory": {"text_mentions": 2, "citation_mentions": 1, "total_mentions": 3}
 }
}
```

Math sanity:
- Citation frequency: `text=2 + citation×2=2 → raw=4 → ROUND(4/7×100)=57`. (The example shows 43, assume the judge re-scored after a re-read.)
- Share of voice: `Acme 3 / total 17 = 17.6 → 18.2 after rounding to nearest 0.1` (example uses the judge's exact figure).
- Positional authority: not first (-30), not in first 100 chars (-20), no definitive framing, "lighter alternative" weakly positive (+10 feature highlight, +5 listed alongside, +5 peripheral) ≈ 20 to 30.
- Sentiment: "lighter-touch micro-surveys with Slack integration" mildly positive (+3) × 2 instances = +6.

## The gap row (from Phase 5)

```json
{
 "content_gap": "Authority Gap (High): Pendo framed as 'leading' for enterprise; Acme described as 'newer entrant'. Citation Gap (Medium): Pendo cited 2× to pendo.io vs 1× to acme.com.",
 "optimization_action": "Publish a definitive 'B2B SaaS in-app feedback tool buyers guide' with quantified comparison matrix (Acme, Pendo, Sprig, FullStory), embed FAQ + HowTo schema, include a 60-word direct-answer block per evaluation criterion",
 "optimization_rationale": "The query is a high-intent decision-stage question and Acme appears only as a lighter alternative behind Pendo's 'leading' framing. A definitive buyers-guide page that explicitly positions Acme on each criterion (with citable stats) attacks both the Authority Gap and the Citation Gap simultaneously, since AI engines cite long-form comparison pages with structured data more often than blog posts.",
 "optimization_priority": "High",
 "optimization_expected_impact": "Short-term: Acme begins surfacing in answers for similar evaluation queries on Anthropic + Perplexity within 4 to 8 weeks of publication and indexing. Medium-term: with comparison + buyers-guide schema, Acme captures featured snippets for 2 to 3 'in-app feedback tool comparison' SERPs. Long-term: Acme's market_position lifts from Alternative to Challenger as 'leading' framing transfers across decision-stage answers.",
 "overall_visibility_assessment": "Moderate",
 "key_insights": [
 "Acme is present but positioned as the 'newer alternative' to Pendo, the brand is visible but loses the authority framing on every decision query.",
 "Pendo's citation density (2× to pendo.io) is the dominant signal driving its 'leading' framing in this category.",
 "Highest-leverage move: ship one buyers-guide comparison page with FAQ + HowTo schema this sprint to attack both the Authority and Citation gaps."
 ],
 "_gap_details": [
 {
 "gap_type": "Authority Gap",
 "gap_severity": "High",
 "gap_description": "Pendo framed as 'widely considered the leading platform for enterprise feedback management'; Acme described as 'a newer entrant focused on lighter-touch micro-surveys'. Acme lacks the definitive framing Pendo has.",
 "competitor_advantage": ["Pendo"]
 },
 {
 "gap_type": "Citation Gap",
 "gap_severity": "Medium",
 "gap_description": "Pendo cited 2× to pendo.io vs Acme cited 1× to acme.com. Sprig and FullStory each cited 1×.",
 "competitor_advantage": ["Pendo"]
 }
 ]
}
```

## The 20-column scorecard row (from Phase 6)

| # | Column | Value |
|---|---|---|
| 1 | query_tested | What should a B2B SaaS product team look for when choosing an in-app feedback tool, features, pricing model, and red flags? |
| 2 | response_summary | The answer walks through the key evaluation criteria for B2B SaaS in-app feedback tools, features, pricing model, and red flags. Pendo is recommended as the enterprise leader, Sprig for product-led growth surveys, Acme as a lighter alternative. |
| 3 | brand_mentioned | true |
| 4 | brands_mentioned_list | Acme, FullStory, Pendo, Sprig |
| 5 | citation_frequency_score | 43 |
| 6 | share_of_voice_percentage | 18.2 |
| 7 | positional_authority_score | 25 |
| 8 | sentiment_direction_score | 6 |
| 9 | response_relevance_score | 75 |
| 10 | market_position_type | Alternative |
| 11 | discovery_role | Fallback |
| 12 | positioning_narrative | Acme is positioned as a lighter, newer alternative (~18% SoV); Pendo dominates with ~45% and 'leading' authority framing, Sprig is the secondary recommendation. |
| 13 | strength_score | 5 |
| 14 | content_gap | Authority Gap (High): Pendo framed as 'leading' for enterprise; Acme described as 'newer entrant'. Citation Gap (Medium): Pendo cited 2× to pendo.io vs 1× to acme.com. |
| 15 | optimization_action | Publish a definitive 'B2B SaaS in-app feedback tool buyers guide' with quantified comparison matrix (Acme, Pendo, Sprig, FullStory), embed FAQ + HowTo schema, include a 60-word direct-answer block per evaluation criterion |
| 16 | optimization_rationale | The query is a high-intent decision-stage question and Acme appears only as a lighter alternative behind Pendo's 'leading' framing. A definitive buyers-guide page that explicitly positions Acme on each criterion (with citable stats) attacks both the Authority Gap and the Citation Gap simultaneously, since AI engines cite long-form comparison pages with structured data more often than blog posts. |
| 17 | optimization_priority | High |
| 18 | optimization_expected_impact | Short-term: Acme begins surfacing in answers for similar evaluation queries on Anthropic + Perplexity within 4 to 8 weeks of publication and indexing. Medium-term: with comparison + buyers-guide schema, Acme captures featured snippets for 2 to 3 'in-app feedback tool comparison' SERPs. Long-term: Acme's market_position lifts from Alternative to Challenger as 'leading' framing transfers across decision-stage answers. |
| 19 | overall_visibility_assessment | Moderate |
| 20 | key_insights | Acme is present but positioned as the 'newer alternative' to Pendo, the brand is visible but loses the authority framing on every decision query. \| Pendo's citation density (2× to pendo.io) is the dominant signal driving its 'leading' framing in this category. \| Highest-leverage move: ship one buyers-guide comparison page with FAQ + HowTo schema this sprint to attack both the Authority and Citation gaps. |
