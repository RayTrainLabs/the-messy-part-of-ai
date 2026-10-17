"""Anthropic adapter — Messages API with web_search tool ON."""

import json
import os
import time

import requests

ENGINE_ID = "llm_anthropic"
PROVIDER_NAME = "Anthropic"
ENDPOINT = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-opus-4-7"
JUDGE_MODEL = "claude-opus-4-7"
TIMEOUT = 120


def is_available():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _headers():
    return {
        "x-api-key":         os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": "2023-06-01",
        "content-type":      "application/json",
    }


def call(query, brand_profile=None, model=None, **kwargs):
    body = {
        "model": model or DEFAULT_MODEL,
        "max_tokens": 2000,
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
        "messages": [{"role": "user", "content": query}],
    }
    return _post_messages(body, web_search_enabled=True)


def judge(system_prompt, user_payload, model=None):
    body = {
        "model": model or JUDGE_MODEL,
        "max_tokens": 2500,
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
    }
    result = _post_messages(body, web_search_enabled=False)
    if not result.get("ok"):
        raise RuntimeError(f"Anthropic judge failed: {result.get('error')}")
    return result["llm_answer_text"]


def _post_messages(body, web_search_enabled):
    for attempt in range(3):
        try:
            r = requests.post(ENDPOINT, headers=_headers(), json=body, timeout=TIMEOUT)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 4 ** attempt))
                time.sleep(wait)
                continue
            r.raise_for_status()
            data = r.json()
            return _normalize(data, body.get("model"), web_search_enabled)
        except requests.HTTPError as e:
            txt = r.text[:300] if r is not None else str(e)
            if r is not None and r.status_code == 400 and "refused" in txt.lower():
                return {"ok": False, "error": "refused"}
            if r is not None and r.status_code >= 500 and attempt < 2:
                time.sleep(4 ** attempt)
                continue
            return {"ok": False, "error": f"HTTP {r.status_code}: {txt}"}
        except (requests.RequestException, ValueError) as e:
            if attempt < 2:
                time.sleep(4 ** attempt)
                continue
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return {"ok": False, "error": "exhausted retries"}


def _normalize(data, model, web_search_enabled):
    text_parts = []
    citations = []

    for block in data.get("content", []):
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "web_search_tool_result":
            for result in block.get("content", []):
                url = result.get("url")
                if url:
                    citations.append(url)
        elif btype == "tool_use":
            pass  # internal tool call; skip

    if data.get("stop_reason") == "refusal":
        return {"ok": False, "error": "refused"}

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
