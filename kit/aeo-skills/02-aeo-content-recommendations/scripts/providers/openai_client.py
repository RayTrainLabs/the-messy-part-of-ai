"""OpenAI adapter — Responses API, used as the recommendation judge."""

import json
import os
import time

import requests

PROVIDER_NAME = "OpenAI"
ENDPOINT = "https://api.openai.com/v1/responses"
JUDGE_MODEL = "gpt-5.4-nano"
TIMEOUT = 120


def is_available():
    return bool(os.environ.get("OPENAI_API_KEY"))


def _headers():
    return {
        "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
        "Content-Type":  "application/json",
    }


def judge(system_prompt, user_payload, model=None):
    body = {
        "model": model or JUDGE_MODEL,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "max_output_tokens": 4000,
        "text": {"format": {"type": "json_object"}},
    }

    for attempt in range(3):
        try:
            r = requests.post(ENDPOINT, headers=_headers(), json=body, timeout=TIMEOUT)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 4 ** attempt))
                time.sleep(wait); continue
            r.raise_for_status()
            data = r.json()
            text_parts = []
            for item in data.get("output") or []:
                if item.get("type") == "message":
                    for c in item.get("content", []):
                        if c.get("type") == "output_text":
                            text_parts.append(c.get("text", ""))
            if not text_parts and data.get("output_text"):
                text_parts.append(data["output_text"])
            return "\n".join(text_parts).strip()
        except requests.HTTPError:
            if r is not None and r.status_code >= 500 and attempt < 2:
                time.sleep(4 ** attempt); continue
            raise RuntimeError(f"OpenAI judge failed: HTTP {r.status_code}: {r.text[:300]}")
        except (requests.RequestException, ValueError) as e:
            if attempt < 2:
                time.sleep(4 ** attempt); continue
            raise RuntimeError(f"OpenAI judge failed: {type(e).__name__}: {e}")
    raise RuntimeError("OpenAI judge failed: exhausted retries")
