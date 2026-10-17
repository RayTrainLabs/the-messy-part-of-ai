"""SerpApi adapter — primary SERP source."""

import os
import time
from urllib.parse import urlparse

import requests

ENGINE_ID = "serp_google"
PROVIDER_NAME = "SerpApi"
ENDPOINT = "https://serpapi.com/search"
TIMEOUT = 60


def is_available():
    return bool(os.environ.get("SERPAPI_KEY"))


def call(query, brand_profile=None, **kwargs):
    api_key = os.environ.get("SERPAPI_KEY")
    if not api_key:
        return {"ok": False, "error": "SERPAPI_KEY not set"}

    market_focus = (brand_profile or {}).get("market_focus", {})
    geo = (market_focus.get("geo") or ["us"])[0]
    # Map full country names to ISO 3166-1 alpha-2 codes SerpAPI accepts
    _GEO_MAP = {
        "united kingdom": "gb", "uk": "gb", "great britain": "gb",
        "united states": "us", "usa": "us", "u.s.": "us",
        "germany": "de", "deutschland": "de",
        "france": "fr", "canada": "ca", "australia": "au",
        "netherlands": "nl", "spain": "es", "italy": "it",
        "austria": "at", "switzerland": "ch", "ireland": "ie",
        "india": "in", "japan": "jp", "brazil": "br",
    }
    gl = _GEO_MAP.get(geo.lower(), geo.lower()[:2]) if isinstance(geo, str) else "us"
    # Final safety: SerpAPI gl codes are always exactly 2 chars
    if len(gl) != 2:
        gl = "us"

    params = {
        "engine":  "google",
        "q":       query,
        "gl":      gl,
        "hl":      "en",
        "num":     10,
        "output":  "json",
        "api_key": api_key,
    }

    for attempt in range(3):
        try:
            r = requests.get(ENDPOINT, params=params, timeout=TIMEOUT)
            if r.status_code == 429:
                time.sleep(4 ** attempt)
                continue
            r.raise_for_status()
            data = r.json()
            return _normalize(data)
        except requests.HTTPError as e:
            if r.status_code >= 500 and attempt < 2:
                time.sleep(4 ** attempt)
                continue
            return {"ok": False, "error": f"HTTP {r.status_code}: {e}"}
        except (requests.RequestException, ValueError) as e:
            if attempt < 2:
                time.sleep(4 ** attempt)
                continue
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    return {"ok": False, "error": "exhausted retries"}


def _normalize(data):
    organic = data.get("organic_results") or []
    serp_results = []
    citation_urls = []
    for item in organic[:10]:
        url = item.get("link")
        if not url:
            continue
        serp_results.append({
            "position": item.get("position"),
            "title":    item.get("title"),
            "url":      url,
            "snippet":  item.get("snippet"),
            "domain":   urlparse(url).netloc.replace("www.", ""),
        })
        citation_urls.append(url)

    ai_overview = None
    ao = data.get("ai_overview") or data.get("answer_box")
    if ao:
        ai_overview = ao.get("answer") or ao.get("snippet") or ao.get("text") or None

    related = [q.get("question") for q in (data.get("related_questions") or []) if q.get("question")]

    return {
        "ok": True,
        "engine_type": "serp",
        "model": "google-serp-via-serpapi",
        "web_search_enabled": True,  # SERP is always live web
        "llm_answer_text": None,
        "citation_urls": citation_urls,
        "serp_results": serp_results,
        "serp_organic_count": len(serp_results),
        "serp_ai_overview": ai_overview,
        "related_questions": related,
        "raw": data,
    }
