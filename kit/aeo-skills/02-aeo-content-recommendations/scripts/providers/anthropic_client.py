"""Anthropic adapter — Messages API, used as the recommendation judge.

(Same interface as skill 01's anthropic_client.py — copied so this skill
runs standalone. If a third skill needs the same client, promote to
AEO skills/_shared/providers/.)
"""

import json
import os
import time

import requests

PROVIDER_NAME = "Anthropic"
ENDPOINT = "https://api.anthropic.com/v1/messages"
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


def judge(system_prompt, user_payload, model=None):
    body = {
        "model": model or JUDGE_MODEL,
        "max_tokens": 4000,
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
    }

    for attempt in range(3):
        try:
            r = requests.post(ENDPOINT, headers=_headers(), json=body, timeout=TIMEOUT)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 4 ** attempt))
                time.sleep(wait); continue
            r.raise_for_status()
            data = r.json()
            text_parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
            return "\n".join(text_parts).strip()
        except requests.HTTPError:
            if r is not None and r.status_code >= 500 and attempt < 2:
                time.sleep(4 ** attempt); continue
            raise RuntimeError(f"Anthropic judge failed: HTTP {r.status_code}: {r.text[:300]}")
        except (requests.RequestException, ValueError) as e:
            if attempt < 2:
                time.sleep(4 ** attempt); continue
            raise RuntimeError(f"Anthropic judge failed: {type(e).__name__}: {e}")
    raise RuntimeError("Anthropic judge failed: exhausted retries")
