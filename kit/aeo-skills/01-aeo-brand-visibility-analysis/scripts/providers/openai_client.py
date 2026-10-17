"""OpenAI adapter — uses the Responses API with web_search tool ON.

The Chat Completions endpoint does not support web_search; do not fall back to it.

Quota-exhaustion handling: if the API returns 429 with `error.type ==
"insufficient_quota"` we set a module-level circuit-breaker flag and short-circuit
all subsequent calls in the same process. Without this, run_queries.py wastes
~3 retries x N queries on a key that will never recover this billing cycle
(observed 15-min hang in the Country Bean test run).
"""

import json
import os
import sys
import time

import requests

ENGINE_ID = "llm_openai"
PROVIDER_NAME = "OpenAI"
ENDPOINT = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-5.4-nano"
JUDGE_MODEL = "gpt-5.4-nano"
TIMEOUT = 120

# Circuit breaker — once tripped, every subsequent call returns instantly.
_QUOTA_EXHAUSTED = False


def is_available():
    return bool(os.environ.get("OPENAI_API_KEY")) and not _QUOTA_EXHAUSTED


def _trip_circuit_breaker(reason):
    global _QUOTA_EXHAUSTED
    if not _QUOTA_EXHAUSTED:
        _QUOTA_EXHAUSTED = True
        print(f"[openai_client] OpenAI engine disabled for the rest of this run: {reason}",
              file=sys.stderr)


def _headers():
    return {
        "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
        "Content-Type":  "application/json",
    }


def call(query, brand_profile=None, model=None, **kwargs):
    body = {
        "model": model or DEFAULT_MODEL,
        "input": query,
        "tools": [{"type": "web_search"}],
        "tool_choice": "auto",
        "max_output_tokens": 4000,
    }
    return _post_responses(body, web_search_enabled=True)


def judge(system_prompt, user_payload, model=None, max_output_tokens=8000):
    # Responses API expects JSON-mode under `text.format`. 8000 tokens covers
    # query-generation prompts that ask for ~20 queries with rich schemas; the
    # legacy 2000 cap truncated mid-JSON on multi-query responses.
    body = {
        "model": model or JUDGE_MODEL,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "max_output_tokens": max_output_tokens,
        "text": {"format": {"type": "json_object"}},
    }
    result = _post_responses(body, web_search_enabled=False)
    if not result.get("ok"):
        raise RuntimeError(f"OpenAI judge failed: {result.get('error')}")
    return result["llm_answer_text"]


def _post_responses(body, web_search_enabled):
    if _QUOTA_EXHAUSTED:
        return {"ok": False, "error": "openai_quota_exhausted (engine disabled for run)"}
    for attempt in range(3):
        try:
            r = requests.post(ENDPOINT, headers=_headers(), json=body, timeout=TIMEOUT)
            if r.status_code == 429:
                # Distinguish quota-exhausted (terminal) from rate-limit (retryable).
                err_body = ""
                try: err_body = r.text or ""
                except Exception: pass
                if "insufficient_quota" in err_body or "exceeded your current quota" in err_body.lower():
                    _trip_circuit_breaker("insufficient_quota")
                    return {"ok": False, "error": "openai_quota_exhausted"}
                wait = int(r.headers.get("Retry-After", 4 ** attempt))
                time.sleep(wait)
                continue
            if r.status_code in (401, 403):
                _trip_circuit_breaker(f"HTTP {r.status_code} (auth)")
                return {"ok": False, "error": f"openai_auth_failed: HTTP {r.status_code}"}
            r.raise_for_status()
            data = r.json()
            return _normalize(data, body.get("model"), web_search_enabled)
        except requests.HTTPError as e:
            if r.status_code >= 500 and attempt < 2:
                time.sleep(4 ** attempt)
                continue
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:300]}"}
        except (requests.RequestException, ValueError) as e:
            if attempt < 2:
                time.sleep(4 ** attempt)
                continue
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return {"ok": False, "error": "exhausted retries"}


def _normalize(data, model, web_search_enabled):
    text_parts = []
    citations = []

    output = data.get("output") or []
    for item in output:
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    text_parts.append(c.get("text", ""))
                    for ann in c.get("annotations") or []:
                        if ann.get("type") == "url_citation" and ann.get("url"):
                            citations.append(ann["url"])

    if not text_parts and data.get("output_text"):
        text_parts.append(data["output_text"])

    return {
        "ok": True,
        "engine_type": "llm",
        "model": model,
        "web_search_enabled": web_search_enabled,
        "llm_answer_text": "\n".join(text_parts).strip(),
        "citation_urls": list(dict.fromkeys(citations)),
        "serp_results": None,
        "serp_organic_count": None,
        "serp_ai_overview": None,
        "raw": data,
    }
