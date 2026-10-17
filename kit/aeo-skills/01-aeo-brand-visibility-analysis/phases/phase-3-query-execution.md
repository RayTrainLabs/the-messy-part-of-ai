# Phase 3, Query execution

**Goal:** for every approved query, fetch a response from **every available engine** (one SERP source plus all configured LLM engines), save the raw payload, and produce one row per (query × engine) ready for scoring.

This is the only phase that spends real API credits. Be deliberate.

## Engine definitions

| Engine ID | Type | Provider |
|---|---|---|
| `serp_google` | SERP | SerpApi (`google` engine) **or** Apify (`apify/google-search-scraper`), whichever key is set; SerpApi takes precedence |
| `llm_openai` | LLM | OpenAI Responses API with `web_search` tool ON |
| `llm_anthropic` | LLM | Anthropic Messages API with `web_search_20250305` tool enabled |
| `llm_perplexity` | LLM | Perplexity Sonar (`sonar-pro` or `sonar`), native answer engine, web search built in |
| `llm_gemini` | LLM | Google Gemini API with `google_search` grounding tool ON |

A row is produced for every (query, engine) pair where the engine is configured AND the call succeeds. Failures are recorded but do not abort the run.

## Steps

1. **Pre-flight check:**
 ```bash
 python scripts/run_queries.py --check-providers
 ```
 Output looks like:
 ```
 [OK ] serp_google (SerpApi)
 [OK ] llm_openai
 [OK ] llm_anthropic
 [ - ] llm_perplexity (PERPLEXITY_API_KEY not set)
 [OK ] llm_gemini
 ```
 (Plain ASCII glyphs are used so the output renders on Windows cp1252 consoles
 as well as POSIX terminals.)
 **Hard requirement:** at least one SERP engine must be ✓. If not, stop the phase and tell the user which env var to set.

2. **Estimate cost and ask for confirmation.** The script prints an estimate based on engine count × query count × typical response size. Show this to the user verbatim and wait for go-ahead. Example:
 > 20 queries × 4 engines = 80 API calls.
 > Estimated cost: SerpApi ~$0.20, OpenAI (gpt-5.4-nano w/ web search) ~$0.50 to 1.00, Anthropic (claude-opus-4-7 + web) ~$1.00 to 2.00, Gemini (3-flash w/ search) ~$0.30 to 0.60. Total ~$2.00 to 4.00.
 > Proceed? (y/n), pass `--yes` to skip this prompt for non-interactive runs.

3. **Run the sweep:**
 ```bash
 python scripts/run_queries.py \
 --queries output/queries.json \
 --brand "Acme" \
 --concurrency 4 \
 --out output/raw_responses.jsonl \
 --raw-dir output/raw/
 ```
 - `--concurrency 4` runs four queries in parallel; respect each provider's documented rate limits (Perplexity in particular is strict).
 - The script retries on 429 with exponential backoff (max 3 retries).
 - Each (query, engine) result is appended to `output/raw_responses.jsonl` AND saved as a standalone JSON under `output/raw/<query_id>__<engine>.json`.

4. **Mid-run sanity check.** After the first 10 queries × engines (~40 rows), the script pauses and shows:
 - Per-engine success rate
 - Average response length
 - Whether the target brand has been mentioned at all yet
 - Top 5 brands surfaced so far

 If any engine has < 50% success rate, fix and resume rather than burning the rest of the budget. Resume with `--resume`.

5. **Full run completes.** Final summary printed:
 ```
 Total rows: 220
 Successful: 217
 Failed (with reason): 3
 - Q42 / llm_gemini → 429 after 3 retries
 - Q51 / llm_openai → safety filter blocked
 - Q55 / llm_perplexity → timeout
 Brand mentions detected (rough text scan): 47 / 217 rows (21.7%)
 ```

## Per-row schema (`output/raw_responses.jsonl`)

```json
{
 "row_id": "Q01__llm_anthropic",
 "query_id": "Q01",
 "query_tested": "How do remote SaaS product teams quickly find out which newly-shipped features are actually used?",
 "category": "A",
 "engine": "llm_anthropic",
 "engine_type": "llm",
 "model": "claude-opus-4-7",
 "web_search_enabled": true,
 "fetched_at": "2026-04-27T...",
 "ok": true,
 "error": null,

 "llm_answer_text": "...full answer text...",
 "citation_urls": ["https://acme.com/...", "https://sprig.com/..."],

 "serp_results": null,
 "serp_organic_count": null,
 "serp_ai_overview": null,

 "raw_response_path": "output/raw/Q01__llm_anthropic.json"
}
```

For SERP rows, `llm_answer_text` is null and the `serp_*` fields are populated:

```json
{
 "engine": "serp_google",
 "serp_results": [
 {"position": 1, "title": "...", "url": "...", "snippet": "..."},
 ...
 ],
 "serp_organic_count": 10,
 "serp_ai_overview": "Google AI Overview text if present, else null",
 "citation_urls": ["...top-10 URLs..."]
}
```

The unified `citation_urls` field exists on every row so downstream metrics treat SERP and LLM responses uniformly.

## Provider-specific notes

See [`../references/api-providers.md`](../references/api-providers.md) for the full configuration reference. Key reminders:

- **OpenAI:** use the **Responses API** with `tools=[{"type": "web_search"}]`. The Chat Completions endpoint does **not** ground in live web data and will produce stale answers.
- **Anthropic:** enable `tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]`. Claude will refuse some queries it considers ambiguous; treat refusals as a row-level error, not a fatal stop.
- **Perplexity:** Sonar models grounding is automatic; no tool flag needed. Use `sonar-pro` for richer citations when budget allows.
- **Gemini:** use `tools=[{"google_search": {}}]` (grounding). Without this flag, Gemini answers from training data, useless for AEO.
- **SerpApi:** request `engine=google`, plus `gl=<country>` and `hl=<language>` if Phase 0 captured a regional focus. Request `output=json`.
- **Apify:** the `apify/google-search-scraper` actor returns the same `organic_results[]` shape; the adapter normalizes both to one schema.

## Quality bar before exiting Phase 3

- ≥ 95% row success rate overall
- Every approved query has at least 1 successful row across engines (queries with 100% engine failure are flagged, the user is asked whether to drop or retry)
- `output/raw/` directory has one file per row (no missing payloads)
- The unified `citation_urls` field is non-empty for ≥ 90% of rows (a row with no citations and no text is suspicious)

## Common pitfalls

- **Forgetting to enable web search on the LLM call.** Easy mistake; produces hallucinated brand mentions and unusable scoring. The script logs the `web_search_enabled` flag on every row precisely so this is verifiable later.
- **Running 50 queries × 5 engines in serial.** Takes 30+ minutes. Use `--concurrency 4` and respect per-provider limits.
- **Treating SERP top-10 as "the answer".** SERP gives positional ranking and surrounding context (AI Overview, People Also Ask). Capture all of it; the metrics rubric uses more than just position 1.
- **Ignoring AI Overview on SerpApi.** This is increasingly important for AEO and is a separate field in the SerpApi response.
