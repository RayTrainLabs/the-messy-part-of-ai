# API provider configuration

Operational reference for every supported provider. Phase 3 (`scripts/run_queries.py`) and Phase 4/5 (`scripts/analyze_response.py`) read this, when something is broken in production, start here.

## Required environment variables

| Var | Used by | Required? |
|---|---|---|
| `SERPAPI_KEY` | SERP source | one of `SERPAPI_KEY` or `APIFY_TOKEN` is **required** |
| `APIFY_TOKEN` | SERP source (fallback) | "" |
| `OPENAI_API_KEY` | OpenAI engine + judge | optional, recommended |
| `ANTHROPIC_API_KEY` | Anthropic engine + judge | optional, recommended (Anthropic is the **preferred** judge for cross-model neutrality) |
| `PERPLEXITY_API_KEY` | Perplexity engine | optional, recommended |
| `GEMINI_API_KEY` | Gemini engine + judge | optional, recommended |

If only one LLM key is available, the skill uses the same provider for both the engine sweep AND the judge, this introduces self-judgment bias which is logged in the PDF methodology section.

## SERP providers

### SerpApi (preferred)

Endpoint: `https://serpapi.com/search`
Auth: `?api_key=...`
Per query, request:
```
engine=google
q=<query>
gl=<country code, e.g. us, de, in> # from brand_profile.market_focus.geo[0]
hl=<language code, e.g. en, de> # default en
num=10
output=json
```
Response of interest: `organic_results[]`, `ai_overview` (when present), `related_questions[]`, `answer_box`.

Free tier: 100 searches/month. Paid plans linked from <https://serpapi.com/pricing>.

### Apify (fallback)

Actor: `apidojo/google-search-scraper` (intentionally **not** `apify/google-search-scraper`, apidojo is faster, simpler payload, and is the single Apify SERP actor used across this skill set including skill 03's social-listening sweep).

Endpoint: `https://api.apify.com/v2/acts/apidojo~google-search-scraper/run-sync-get-dataset-items`
Auth: `?token=...`

Body (POST):
```json
{
 "queries": ["<query>"],
 "maxItemsPerQuery": 10,
 "countryCode": "us",
 "languageCode": "en"
}
```

Response: a flat array of result items (one per organic result), each `{ searchQuery, url, title, description, position, displayedUrl, ... }`. The first item also carries optional `featuredSnippet` and `peopleAlsoAsk` enrichments. The adapter normalizes to the same shape as SerpApi's output.

**First page only**: every Apify SERP call across this skill set requests only the first page (`maxItemsPerQuery: 10`). Going deeper rarely changes AEO findings and multiplies the bill.

## LLM engines

For every LLM engine, **web search / grounding MUST be enabled**. Without it, the response reflects training-data memory and is useless for AEO. The script logs the `web_search_enabled` flag on every row; the methodology section of the PDF surfaces it.

### OpenAI (GPT, e.g. gpt-4o or gpt-4.1)

API: **Responses API** (`POST /v1/responses`), NOT Chat Completions. Chat Completions does not support web_search natively.

Body:
```json
{
 "model": "gpt-4o",
 "input": "<query>",
 "tools": [{"type": "web_search"}],
 "tool_choice": "auto",
 "max_output_tokens": 1500
}
```

Auth: `Authorization: Bearer $OPENAI_API_KEY`

Response of interest:
- `output[]`, list of message + tool_call entries; concatenate text deltas to get `llm_answer_text`
- `output[].content[].annotations[]` where `type == "url_citation"` → `citation_urls`

If model returns 404 / "tool not supported" → fall back to `gpt-4o-search-preview` (older surface).

### Anthropic (Claude, e.g. claude-opus-4-7 or claude-sonnet-4-6)

API: Messages API (`POST /v1/messages`)

Body:
```json
{
 "model": "claude-opus-4-7",
 "max_tokens": 2000,
 "tools": [
 {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
 ],
 "messages": [{"role": "user", "content": "<query>"}]
}
```

Auth: `x-api-key: $ANTHROPIC_API_KEY`, `anthropic-version: 2023-06-01`

Response of interest:
- `content[]`, concatenate `text` blocks for `llm_answer_text`
- `content[]` blocks of type `web_search_tool_result` → extract `url` from each search result → `citation_urls`

Refusals (Claude declines a query): record as `ok: false, error: "refused"`. Do not retry; move on.

### Perplexity (Sonar)

API: `POST https://api.perplexity.ai/chat/completions`

Body:
```json
{
 "model": "sonar-pro",
 "messages": [{"role": "user", "content": "<query>"}],
 "return_citations": true,
 "return_related_questions": false
}
```

Auth: `Authorization: Bearer $PERPLEXITY_API_KEY`

Response of interest:
- `choices[0].message.content` → `llm_answer_text`
- `citations` (top-level array) → `citation_urls`

Models: `sonar-pro` (richer citations, more expensive) or `sonar` (cheaper). Default `sonar-pro` for audits, `sonar` for re-runs.

Rate limits are strict, keep `--concurrency 4` or lower, and respect `Retry-After` on 429s.

### Google Gemini (1.5-pro or 2.0-flash with grounding)

API: `POST https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent`

Body:
```json
{
 "contents": [{"role": "user", "parts": [{"text": "<query>"}]}],
 "tools": [{"google_search": {}}],
 "generationConfig": {"maxOutputTokens": 1500}
}
```

Auth: `?key=$GEMINI_API_KEY`

Response of interest:
- `candidates[0].content.parts[].text` → concatenate to `llm_answer_text`
- `candidates[0].groundingMetadata.groundingChunks[].web.uri` → `citation_urls`

Without `tools=[{"google_search": {}}]`, Gemini returns ungrounded text, the adapter rejects ungrounded responses and marks the row as a failure.

## Concurrency, retries, rate limits

Default in `run_queries.py`:
- `--concurrency 4`
- Per-provider semaphore: SerpApi 4, OpenAI 4, Anthropic 4, Perplexity 2, Gemini 4
- Retries: 3 attempts on HTTP 429 / 5xx with exponential backoff (1s, 4s, 16s)
- Honor `Retry-After` header when present
- Hard timeout per request: 60s

If a provider repeatedly fails, the script disables it for the remainder of the run and logs the disable reason. Subsequent rows still use other engines.

## Cost estimation

Rough per-call costs as of late 2025 / early 2026 (verify in the provider's dashboard):

| Provider | Per query (typical) |
|---|---|
| SerpApi | ~$0.005 to $0.01 |
| Apify Google scraper | ~$0.005 to $0.015 |
| OpenAI gpt-4o + web search | ~$0.02 to $0.05 |
| Anthropic claude-opus-4-7 + web search | ~$0.05 to $0.10 |
| Perplexity sonar-pro | ~$0.005 to $0.01 |
| Gemini 1.5-pro + grounding | ~$0.01 to $0.03 |

For 20 queries × 5 engines = 100 calls, total ~$2 to $6. The script shows the estimate before running and asks for confirmation.

## Adding a new provider

The provider adapters live in `scripts/providers/`. To add a new one:

1. Create `scripts/providers/<provider>_client.py` exposing `def call(query: str, brand_profile: dict, **kwargs) -> dict` returning the unified row schema.
2. Register it in `scripts/providers/__init__.py` (add to `PROVIDERS` registry).
3. Add an entry to the env-var table at the top of this doc.
4. Update the engines table in [`../phases/phase-3-query-execution.md`](../phases/phase-3-query-execution.md).

The unified row schema is documented in `phases/phase-3-query-execution.md` ("Per-row schema").
