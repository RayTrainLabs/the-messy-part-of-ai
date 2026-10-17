# Brand visibility metrics rubric

The full per-row scoring specification. Phase 4 enforces this; the system prompt in [`../templates/metrics_analysis_system_prompt.md`](../templates/metrics_analysis_system_prompt.md) is the operational version sent to the judge LLM.

## Role

You are a brand-detection and visibility-metrics engine. You analyze a single LLM or SERP response to measure how brands are represented.

## Core rules

1. Detect ALL brand names mentioned.
2. Determine if the target brand is among them.
3. Calculate metrics ONLY if the target brand is present (else all numeric scores = 0).
4. Be precise, no estimations.

## Inputs

```
query_tested: string
ai_engine: string # serp_google | llm_openai | llm_anthropic | llm_perplexity | llm_gemini
llm_answer_text: string | null # null for pure SERP rows
citation_urls: string[]
serp_results: object[] | null # null for LLM rows
serp_ai_overview: string | null # null for LLM rows; populated when SERP includes Google AI Overview
target_brand: string
target_brand_aliases: string[] # optional
known_competitors: string[]
```

For SERP rows, treat `serp_ai_overview` (if present) and the concatenation of organic snippets as the equivalent of `llm_answer_text` for detection / sentiment / authority scoring.

---

## Phase 1, Brand detection

### 1.1 Scan for all brands

Read `llm_answer_text` (or the SERP equivalent) and `citation_urls`. Identify every brand / product / company name mentioned.

**Include:**
- Software products and platforms
- Companies and organizations
- Tools and services
- Any proper noun representing a commercial entity

**Exclude:**
- Generic social platforms (Twitter, X, Facebook, LinkedIn, Reddit), unless the brand under audit IS one of these
- News and media (Forbes, TechCrunch, Wired, NYTimes, etc.)
- Reference sites (Wikipedia, GitHub, Medium, Stack Overflow)
- Search engines (Google Search, Bing), unless a search engine is the brand under audit

From citations, extract brand names from registered-domain (e.g., `asana.com → Asana`, `notion.so → Notion`). Apply the same exclusions.

### 1.2 Build `brands_mentioned_list`

Deduplicate (case-insensitive, trim possessive `'s`, normalize obvious aliases like "Acme Inc" → "Acme" if `target_brand_aliases` says so). Sort alphabetically.

### 1.3 Determine `brand_mentioned`

```
IF target_brand (or any alias) appears in brands_mentioned_list → true
ELSE → false
```

**Validation:** if the target brand or alias appears anywhere in the answer text or citation domains, `brand_mentioned` MUST be true. The deterministic pre-scan is the safety net.

### 1.4 Count mentions

For each brand in `brands_mentioned_list`:
- `text_mentions`, distinct mentions in the answer text (recount of the same surface form in different sentences = 2)
- `citation_mentions`, distinct citation URLs whose registered-domain belongs to that brand (same URL twice = 1)
- `total_mentions` = `text_mentions + citation_mentions`

---

## Phase 2, Metrics calculation

If `brand_mentioned` is false, set all numeric scores to 0 and skip to Phase 3.

### 2.1 `citation_frequency_score` (int 0 to 100)

```
raw = target_text_mentions + (target_citation_mentions × 2)
IF raw >= 7 → 100
ELSE → ROUND((raw / 7) × 100)
```

### 2.2 `share_of_voice_percentage` (float 0.0 to 100.0)

```
all_mentions = sum of total_mentions across all brands in brands_mentioned_list
IF all_mentions == 0 → 0.0
ELSE → ROUND((target_total_mentions / all_mentions) × 100, 1)
```

### 2.3 `positional_authority_score` (int 0 to 100)

Sum points (cap at 100):

| Signal | Points |
|---|---|
| Target brand appears before any competitor | +30 |
| Target brand in first 100 characters of answer | +20 |
| Definitive framing ("According to [target]", "[target] recommends") | +25 |
| Strong recommendation language in same context ("best", "top", "leading", "recommended") | +25 |
| Favorable comparison ("better than", "outperforms") | +15 |
| Feature/capability highlight ("offers", "provides", "includes") | +10 |
| Listed alongside competitors without distinction | +5 |
| Single peripheral mention only | +3 |

For SERP rows, treat the AI Overview text first; if absent, treat the top organic snippet as "first 100 chars". A position-1 organic listing for the target's domain counts as +30.

### 2.4 `sentiment_direction_score` (int -50 to +50)

Sum per-instance scores (cap between -50 and +50):

| Tone | Per instance |
|---|---|
| Strong positive ("excellent", "outstanding", "highly recommend") | +10 |
| Moderate positive ("great", "effective", "solid") | +6 |
| Mild positive ("good", "useful", "helpful") | +3 |
| Neutral (factual, no opinion) | 0 |
| Mild negative ("basic", "limited") | -3 |
| Moderate negative ("lacks", "disappointing") | -6 |
| Strong negative ("avoid", "worst", "terrible") | -10 |

Score sentiment of the **target brand specifically**, not the overall response. Faint praise that buries the brand under another recommendation counts as neutral or mildly positive at best.

### 2.5 `response_relevance_score` (int 0 to 100)

**Step A**, identify query intent:
- Problem-solving: "how to", "fix", "solve"
- Feature discovery: "features", "capabilities", "what can"
- Comparative: "vs", "compare", "best", "alternative"
- Informational: "what is", "explain", "overview"

**Step B**, base score:

| Alignment | Base |
|---|---|
| Directly addresses intent | 90 |
| Partially addresses query | 65 |
| Mentioned but doesn't address query | 40 |
| Mentioned in unrelated context | 15 |
| Not mentioned | 0 |

**Step C**, quality adjustment (cap 0 to 100):
- Specific details about target → +10
- Generic / vague mention → -10
- Errors about target → -15

---

## Phase 3, Categorical classification

### 3.1 `market_position_type`

```
brand_mentioned == false → "Not mentioned"
share_of_voice >= 50 AND positional_authority >= 70 → "Leader"
share_of_voice >= 30 AND positional_authority >= 50 → "Challenger"
share_of_voice >= 15 AND positional_authority >= 30 → "Alternative"
share_of_voice > 0 → "Niche"
ELSE → "Not competitive"
```

### 3.2 `discovery_role`

```
brand_mentioned == false → "Absent"
sentiment_direction < -20 → "Avoided"
positional_authority >= 60 AND share_of_voice >= 40 → "Primary"
positional_authority >= 30 AND share_of_voice >= 15 → "Secondary"
ELSE → "Fallback"
```

### 3.3 `positioning_narrative` (string, 150 to 250 chars)

If brand IS mentioned: describe market position, share-of-voice %, sentiment summary, comparison to leading competitor if applicable.

If brand is NOT mentioned: state target brand is absent, list top 2 to 3 brands that ARE mentioned, name the dominant brand and its share, note this represents a visibility gap.

### 3.4 `strength_score` (int 0 to 10)

Base from market position:
- Leader → 9
- Challenger → 7
- Alternative → 5
- Niche → 3
- Not competitive → 1
- Not mentioned → 0

Adjustment (cap 0 to 10):
- sentiment > +20 → +1
- sentiment < -20 → -1

### 3.5 `schema_presence_observed` (bool), Best-effort heuristic: did the surface (LLM answer or SERP) appear to have benefited from structured data on the *target* page? Set true when ANY of:
- The cited target URL appears as a rich result (FAQ accordion, How-To steps, Product card, star ratings, video thumbnail) in the SERP results passed in `serp_results`.
- The LLM answer quotes a discrete Q/A or step list whose phrasing is consistent with `FAQPage` / `HowTo` schema (verbatim Q→A pairs, numbered steps with imperative verbs).
- The LLM answer cites the target with a "Rated X out of 5" / price+availability snippet typical of `Product` / `Review` schema.

Set false otherwise (including when the brand isn't mentioned at all). The judge does not see the actual HTML, so this is a directional signal, a `false` score does not prove schema is missing on the page; it proves the engine did not surface it.

---

## Phase 4, Output

### `response_summary`

2 to 3 sentences summarizing what the LLM (or SERP) response covers and its main recommendations. Always present, regardless of whether the target brand is mentioned.

### Output schema (judge LLM must return this exact JSON)

```json
{
 "response_summary": "...",
 "brand_mentioned": true,
 "brands_mentioned_list": ["Acme", "Pendo", "Sprig"],
 "citation_frequency_score": 71,
 "share_of_voice_percentage": 33.3,
 "positional_authority_score": 65,
 "sentiment_direction_score": 12,
 "response_relevance_score": 90,
 "market_position_type": "Challenger",
 "discovery_role": "Secondary",
 "positioning_narrative": "Acme appears second after Pendo (~40% SoV) with positive framing as a 'lighter, faster' alternative; Sprig is mentioned but in a peripheral role.",
 "strength_score": 7,
 "schema_presence_observed": true,
 "_brand_mention_counts": {
 "Acme": {"text_mentions": 3, "citation_mentions": 1, "total_mentions": 4},
 "Pendo": {"text_mentions": 5, "citation_mentions": 0, "total_mentions": 5},
 "Sprig": {"text_mentions": 2, "citation_mentions": 1, "total_mentions": 3}
 }
}
```

The `_brand_mention_counts` block is consumed by the gap analyzer in Phase 5 (so it does not have to recount).

## Final validation

- If target appears in `llm_answer_text` or any citation → `brand_mentioned` MUST be true
- If `brand_mentioned` is true → target brand MUST be in `brands_mentioned_list`
- If `brand_mentioned` is false → all numeric scores MUST be 0 / 0.0
- `share_of_voice_percentage` MUST NOT exceed 100.0
- `positional_authority_score` MUST be in [0, 100]
- `sentiment_direction_score` MUST be in [-50, +50]
- `strength_score` MUST be in [0, 10]
- All enums MUST be exact strings from the spec
- `positioning_narrative` MUST address what IS present when target is absent

A judge response that fails any check is rejected and re-prompted; after 2 retries the row is logged as a scoring failure and excluded from the report (with a note).
