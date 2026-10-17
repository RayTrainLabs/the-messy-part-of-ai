"""Google Gemini adapter — generateContent with google_search grounding tool."""

import json
import os
import time

import requests

ENGINE_ID = "llm_gemini"
PROVIDER_NAME = "Gemini"
DEFAULT_MODEL = "gemini-3-flash-preview"
JUDGE_MODEL = "gemini-3-flash-preview"
TIMEOUT = 120


def is_available():
    return bool(os.environ.get("GEMINI_API_KEY"))


def _endpoint(model):
    return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def call(query, brand_profile=None, model=None, **kwargs):
    model = model or DEFAULT_MODEL
    body = {
        "contents": [{"role": "user", "parts": [{"text": query}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "maxOutputTokens": 4000,
            # Disable hidden "thoughts" budget so the cap fully covers user-visible output.
            # 2.5-flash burns 15k+ tokens on thoughts when thinkingBudget is unset, leaving
            # nothing for the actual answer. 3-flash respects the same flag.
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    return _post(body, model, web_search_enabled=True, require_grounding=True)


def judge(system_prompt, user_payload, model=None, max_output_tokens=8000):
    model = model or JUDGE_MODEL
    body = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(user_payload, ensure_ascii=False)}]}],
        "generationConfig": {
            "maxOutputTokens": max_output_tokens,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    result = _post(body, model, web_search_enabled=False, require_grounding=False)
    if not result.get("ok"):
        raise RuntimeError(f"Gemini judge failed: {result.get('error')}")
    return result["llm_answer_text"]


def _post(body, model, web_search_enabled, require_grounding):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"ok": False, "error": "GEMINI_API_KEY not set"}

    url = f"{_endpoint(model)}?key={api_key}"

    for attempt in range(3):
        try:
            r = requests.post(url, json=body, timeout=TIMEOUT)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 4 ** attempt))
                time.sleep(wait)
                continue
            r.raise_for_status()
            data = r.json()
            return _normalize(data, model, web_search_enabled, require_grounding)
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


def _normalize(data, model, web_search_enabled, require_grounding):
    candidates = data.get("candidates") or []
    if not candidates:
        return {"ok": False, "error": "no candidates returned"}

    cand = candidates[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "\n".join(p.get("text", "") for p in parts if "text" in p).strip()

    citations = []
    grounding = cand.get("groundingMetadata") or {}
    for chunk in grounding.get("groundingChunks") or []:
        web = chunk.get("web") or {}
        if web.get("uri"):
            citations.append(web["uri"])

    if require_grounding and not citations and not grounding:
        return {"ok": False, "error": "ungrounded response (google_search tool did not fire)"}

    return {
        "ok": True,
        "engine_type": "llm",
        "model": model,
        "web_search_enabled": web_search_enabled,
        "llm_answer_text": text,
        "citation_urls": list(dict.fromkeys(citations)),
        "serp_results": None,
        "serp_organic_count": None,
        "serp_ai_overview": None,
        "raw": data,
    }
