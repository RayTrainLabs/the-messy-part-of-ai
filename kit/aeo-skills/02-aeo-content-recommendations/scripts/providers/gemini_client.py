"""Google Gemini adapter — generateContent, used as the recommendation judge."""

import json
import os
import time

import requests

PROVIDER_NAME = "Gemini"
JUDGE_MODEL = "gemini-3-flash-preview"
TIMEOUT = 120


def is_available():
    return bool(os.environ.get("GEMINI_API_KEY"))


def _endpoint(model):
    return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def judge(system_prompt, user_payload, model=None):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    model = model or JUDGE_MODEL
    body = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user",
                      "parts": [{"text": json.dumps(user_payload, ensure_ascii=False)}]}],
        "generationConfig": {
            "maxOutputTokens": 8000,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    url = f"{_endpoint(model)}?key={api_key}"

    for attempt in range(3):
        try:
            r = requests.post(url, json=body, timeout=TIMEOUT)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 4 ** attempt))
                time.sleep(wait); continue
            r.raise_for_status()
            data = r.json()
            cands = data.get("candidates") or []
            if not cands:
                raise RuntimeError("Gemini returned no candidates")
            parts = (cands[0].get("content") or {}).get("parts") or []
            return "\n".join(p.get("text", "") for p in parts if "text" in p).strip()
        except requests.HTTPError:
            if r is not None and r.status_code >= 500 and attempt < 2:
                time.sleep(4 ** attempt); continue
            raise RuntimeError(f"Gemini judge failed: HTTP {r.status_code}: {r.text[:300]}")
        except (requests.RequestException, ValueError) as e:
            if attempt < 2:
                time.sleep(4 ** attempt); continue
            raise RuntimeError(f"Gemini judge failed: {type(e).__name__}: {e}")
    raise RuntimeError("Gemini judge failed: exhausted retries")
