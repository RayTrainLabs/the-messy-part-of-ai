# Sample recommendation rows (one per action type)

A worked example showing what one recommendation looks like for each of the four action types, for the same brand (**Acme**, B2B SaaS product feedback) used in skill 01's example.

## 1. new_article (coverage = none)

**Query Q07:** "What should a B2B SaaS product team look for when choosing an in-app feedback tool, features, pricing model, and red flags?"

**AEO signals:** mention_rate 0.4, avg_sov 18.2%, priority High, gap_types `[Authority Gap, Citation Gap]`, top competitors `[Pendo, Sprig]`.

**Coverage analysis:** the site has `/blog/in-app-feedback-checklist` (partial coverage) and `/features` (indirect mention), but no dedicated buyer's-guide page. Coverage_level: `partial`, borderline `none` for a deep buyer's-guide query. The judge picks `new_article` because the existing partial pages can't be expanded into a full buyer's guide without losing their original purpose.

```json
{
 "action_type": "new_article",
 "target_page": "https://acme.com/guides/in-app-feedback-tool-buyers-guide",
 "placement": null,
 "changes": "Title: B2B SaaS In-App Feedback Tool Buyer's Guide (2026 edition)\nMeta: A practical evaluation framework for choosing in-app feedback software, feature checklist, pricing-model breakdown, integration must-haves, and red flags. Acme vs Pendo vs Sprig vs FullStory side-by-side.",
 "seo_keywords": [
 "in-app feedback tool",
 "product feedback platform",
 "saas feedback tool comparison",
 "buyer's guide",
 "Pendo alternatives"
 ],
 "article_outline": [
 {
 "heading": "What to look for in a B2B SaaS in-app feedback tool",
 "content_points": [
 "60-word direct answer summarizing the four evaluation pillars (features, pricing, integrations, support)",
 "Comparison table: Acme vs Pendo vs Sprig vs FullStory across the four pillars",
 "Why feature checklists fail without context, link to the in-app surveys feature page"
 ]
 },
 {
 "heading": "Feature checklist by use case",
 "content_points": [
 "Micro-surveys at moments of friction",
 "Session-replay linkage",
 "Slack/Teams alerts on negative sentiment",
 "Audience segmentation",
 "Analytics-tool integrations (Mixpanel, Amplitude, Heap)"
 ]
 },
 {
 "heading": "Pricing models compared (per-seat vs per-MAU vs flat)",
 "content_points": [
 "When per-seat makes sense (small product teams)",
 "When per-MAU bites (high-traffic consumer apps)",
 "Hidden costs to watch for in long-term contracts"
 ]
 },
 {
 "heading": "Red flags during the demo and trial",
 "content_points": [
 "Vague answers about export and data ownership",
 "No SOC 2 / GDPR documentation on hand",
 "Slow customer-support response on trial accounts",
 "Onboarding longer than two weeks for SMB customers"
 ]
 },
 {
 "heading": "Implementation timeline and ROI checkpoints",
 "content_points": [
 "Week 1: instrument the first three product surfaces",
 "Week 4: first response cohort (≥ 100 responses)",
 "Week 12: first decision actually informed by collected feedback"
 ]
 },
 {
 "heading": "How to run a vendor evaluation in 30 days",
 "content_points": [
 "Step-by-step 30-day evaluation playbook",
 "Demo-call question list (15 questions)",
 "Scoring sheet (downloadable, internal link to gated asset)"
 ]
 }
 ],
 "internal_links": [
 "https://acme.com/features/in-app-surveys",
 "https://acme.com/integrations/slack",
 "https://acme.com/customers/series-b-saas-team-improves-activation-by-40",
 "https://acme.com/pricing"
 ],
 "external_links": [
 "https://www.nngroup.com/articles/intercept-surveys/",
 "https://en.wikipedia.org/wiki/Net_promoter_score"
 ],
 "expected_result": "Within 8 to 12 weeks of publish + indexing, Acme captures featured-snippet eligibility for 'in-app feedback tool comparison' and starts surfacing in 2 to 3 of 5 LLM answers for category-C decision queries; medium-term, Acme's market_position lifts from Alternative to Challenger on Anthropic and Perplexity."
}
```

**Priority:** High (inherited from AEO scorecard)
**Effort:** L (6-section outline → ~2 to 3 days writer work)

---

## 2. section_addition (coverage = partial)

**Query Q23:** "How should remote SaaS teams handle async product feedback collection across time zones?"

**Coverage analysis:** `/features/in-app-surveys` already discusses survey distribution but doesn't address async / time-zone challenges. Coverage_level: `partial`.

```json
{
 "action_type": "section_addition",
 "target_page": "https://acme.com/features/in-app-surveys",
 "placement": "after the 'Smart targeting' section, before the 'Customers using this' block",
 "changes": "## How does Acme handle async feedback across time zones?\n\nAcme's micro-survey delivery is timezone-aware out of the box. Surveys queue per user's local time, fire only when activity patterns suggest the user is engaged (not at 3am their local time), and sentiment alerts route to the on-call channel for the user's region. Distributed teams running 24/7 product surfaces avoid the classic \"wake up to 200 unanswered surveys from APAC\" problem.\n\n**How it works for distributed product teams:**\n\n- Survey triggers respect each user's timezone (not the server's)\n- Slack alerts route to region-specific channels (us-on-call, eu-on-call, apac-on-call) so the right humans see the right signals during their working hours\n- A weekly digest rolls up async-collected feedback into one shared report, no need for synchronous handoff calls\n- Cohort filters let you compare US-only vs EU-only response patterns to catch regional sentiment splits early\n\nFor remote-first product teams, this is the difference between feedback being a real-time async signal vs. a batch report that lands on someone's desk Monday morning.",
 "seo_keywords": [
 "async product feedback",
 "remote saas team",
 "timezone-aware surveys",
 "distributed product team"
 ],
 "internal_links": [
 "https://acme.com/integrations/slack",
 "https://acme.com/blog/async-feedback-loops"
 ],
 "external_links": [
 "https://www.nngroup.com/articles/intercept-surveys/"
 ],
 "expected_result": "Within 4 to 6 weeks of publish, /features/in-app-surveys begins surfacing in LLM answers for 'remote / distributed / async product team' queries on Anthropic + Perplexity (currently absent). Section captures partial credit on the existing pillar's authority score."
}
```

**Priority:** Medium · **Effort:** M (~ half day)

---

## 3. minor_optimization (coverage = comprehensive but underperforming)

**Query Q34:** "What does NPS not capture that micro-surveys do?"

**Coverage analysis:** `/blog/why-nps-isnt-enough` already covers this comprehensively (3-year-old article with strong arguments). AEO scorecard shows the brand is mentioned but loses authority framing. Coverage_level: `comprehensive`, strength_score 6 → action_type `minor_optimization`.

```json
{
 "action_type": "minor_optimization",
 "target_page": "https://acme.com/blog/why-nps-isnt-enough",
 "placement": "in the opening paragraph",
 "changes": "Replace the existing first sentence with: 'NPS gives you a single number; micro-surveys give you the why behind it, captured at the moment a user hits a friction point, not 30 days later in an inbox they'll never open.' Add a 60-word direct-answer paragraph immediately after, optimized for voice / snippet capture.",
 "seo_keywords": [
 "nps vs micro-surveys",
 "in-app feedback",
 "voice of customer"
 ],
 "internal_links": [
 "https://acme.com/features/in-app-surveys"
 ],
 "external_links": [
 "https://en.wikipedia.org/wiki/Net_promoter_score"
 ],
 "expected_result": "Improved direct-answer pattern lifts the existing post's snippet-eligibility for 'NPS vs micro-surveys' query within 4 weeks; current Niche → Alternative position on the AEO scorecard for category-D queries."
}
```

**Priority:** Low · **Effort:** S (~30 min)

---

## 4. maintain (currently winning)

**Query Q41:** "How does Acme integrate with Slack for product feedback alerts?"

**Coverage analysis:** `/integrations/slack` is comprehensive and the AEO scorecard shows Acme as Leader/Primary on this query (strength 9). Coverage_level: `comprehensive`, no gap.

```json
{
 "action_type": "maintain",
 "target_page": "https://acme.com/integrations/slack",
 "placement": null,
 "changes": null,
 "seo_keywords": [],
 "article_outline": [],
 "internal_links": [],
 "external_links": [],
 "expected_result": "Page is currently Acme's strongest AEO win (Leader, strength 9, sentiment +18). DO NOT modify the existing structure, specifically, do not move the 'Setup in 4 steps' numbered list (driving snippet capture) and do not consolidate the dedicated Slack integration page into a generic /integrations index (would dilute the citation density to slack-specific keywords). Recheck on next AEO baseline run."
}
```

**Priority:** Low · **Effort:** S (no work, explicit "do nothing" record for the future redesign)

---

## How these flow into the CSV

The flat CSV row for each (15 columns), example for Q07 (the new_article above):

| # | Column | Value |
|---|---|---|
| 1 | query | What should a B2B SaaS product team look for when choosing an in-app feedback tool? |
| 2 | content_exists | true |
| 3 | coverage_level | partial |
| 4 | current_locations | https://acme.com/blog/in-app-feedback-checklist § Evaluation criteria \| https://acme.com/features § Why Acme |
| 5 | action_type | new_article |
| 6 | target_page | https://acme.com/guides/in-app-feedback-tool-buyers-guide |
| 7 | placement | _(empty)_ |
| 8 | changes | Title: B2B SaaS In-App Feedback Tool Buyer's Guide (2026 edition)\\nMeta: A practical evaluation framework... |
| 9 | seo_keywords | in-app feedback tool, product feedback platform, saas feedback tool comparison, buyer's guide, Pendo alternatives |
| 10 | article_outline | H: What to look for in a B2B SaaS in-app feedback tool\\n - 60-word direct answer ...\\n - Comparison table ...\\n\\nH: Feature checklist by use case\\n - Micro-surveys ...\\n... |
| 11 | internal_links | https://acme.com/features/in-app-surveys\\nhttps://acme.com/integrations/slack\\n... |
| 12 | external_links | https://www.nngroup.com/articles/intercept-surveys/\\nhttps://en.wikipedia.org/wiki/Net_promoter_score |
| 13 | expected_result | Within 8 to 12 weeks of publish + indexing, Acme captures featured-snippet eligibility for ... |
| 14 | priority | High |
| 15 | effort | L |
