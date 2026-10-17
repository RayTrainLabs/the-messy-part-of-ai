"""Perplexity Sonar adapter — native answer engine with built-in web grounding."""

import os
import time

import requests

ENGINE_ID = "llm_perplexity"
PROVIDER_NAME = "Perplexity"
ENDPOINT = "https://api.perplexity.ai/chat/completions"
DEFAULT_MODEL = "sonar-pro"
TIMEOUT = 120


def is_available():
    return bool(os.environ.get("PERPLEXITY_API_KEY"))


def _headers():
    return {
        "Authorization": f"Bearer {os.environ['PERPLEXITY_API_KEY']}",
        "Content-Type":  "application/json",
    }


def call(query, brand_profile=None, model=None, **kwargs):
    body = {
        "model": model or DEFAULT_MODEL,
        "messages": [{"role": "user", "content": query}],
        "return_citations": True,
        "return_related_questions": False,
    }

    for attempt in range(3):
        try:
            r = requests.post(ENDPOINT, headers=_headers(), json=body, timeout=TIMEOUT)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 4 ** attempt))
                time.sleep(wait)
                continue
            r.raise_for_status()
            data = r.json()
            return _normalize(data, body["model"])
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


def _normalize(data, model):
    choices = data.get("choices") or []
    text = choices[0]["message"]["content"] if choices else ""
    citations = data.get("citations") or []

    return {
        "ok": True,
        "engine_type": "llm",
        "model": model,
        "web_search_enabled": True,
        "llm_answer_text": text.strip() if text else "",
        "citation_urls": list(dict.fromkeys(citations)),
        "serp_results": None,
        "serp_organic_count": None,
        "serp_ai_overview": None,
        "raw": data,
    }
