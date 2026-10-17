"""Apify adapter — Google SERP via apify/google-search-scraper (free actor).

Originally targeted apidojo/google-search-scraper, but that actor is paid /
rental-only and returns `[{demo: true}, ...]` for accounts that have not
rented it. Switched to apify/google-search-scraper which works on the free
plan ($5/mo credit) using the per-query `queries` field.

Country normalization: brand profile geo strings like "India" or "US mid-market"
are mapped to 2-letter ISO codes via a small map (extend as needed).

Response shape returned by apify/google-search-scraper differs from apidojo:
items are page-level and contain a nested `organicResults` array. Normalized
below.

Docs: https://apify.com/apify/google-search-scraper
"""

import os
import time
from urllib.parse import urlparse

import requests

ENGINE_ID = "serp_google"
PROVIDER_NAME = "Apify"
ACTOR_ID = "apify~google-search-scraper"
ENDPOINT = f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items"
TIMEOUT = 240

# Map common brand-profile geo strings to ISO 3166-1 alpha-2 codes.
_GEO_MAP = {
    "india": "in", "in": "in",
    "united states": "us", "us": "us", "usa": "us",
    "united kingdom": "uk", "uk": "uk", "gb": "uk",
    "canada": "ca",
    "australia": "au",
    "germany": "de",
    "france": "fr",
    "japan": "jp",
    "singapore": "sg",
    "uae": "ae",
}


def _country_code(brand_profile):
    market_focus = (brand_profile or {}).get("market_focus", {}) or {}
    geos = market_focus.get("geo") or ["us"]
    raw = geos[0] if geos else "us"
    if not isinstance(raw, str):
        return "us"
    s = raw.strip().lower()
    if s in _GEO_MAP:
        return _GEO_MAP[s]
    # Try first word
    first = s.split()[0] if s else "us"
    return _GEO_MAP.get(first, first[:2] if len(first) >= 2 else "us")


def is_available():
    return bool(os.environ.get("APIFY_TOKEN"))


def call(query, brand_profile=None, **kwargs):
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        return {"ok": False, "error": "APIFY_TOKEN not set"}

    country = _country_code(brand_profile)

    body = {
        "queries":          query if isinstance(query, str) else "\n".join(query),
        "maxPagesPerQuery": 1,
        "resultsPerPage":   10,
        "countryCode":      country,
        "languageCode":     "en",
    }

    for attempt in range(3):
        try:
            r = requests.post(f"{ENDPOINT}?token={token}", json=body, timeout=TIMEOUT)
            if r.status_code == 429:
                time.sleep(4 ** attempt)
                continue
            r.raise_for_status()
            data = r.json()
            return _normalize(data, query if isinstance(query, str) else query[0])
        except requests.HTTPError as e:
            if r.status_code >= 500 and attempt < 2:
                time.sleep(4 ** attempt)
                continue
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:300] if hasattr(r, 'text') else e}"}
        except (requests.RequestException, ValueError) as e:
            if attempt < 2:
                time.sleep(4 ** attempt)
                continue
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    return {"ok": False, "error": "exhausted retries"}


def _normalize(items, query_str):
    """apify/google-search-scraper returns one item per Google results page.
    Each item has top-level keys: searchQuery, url, hasNextPage, organicResults,
    relatedQueries, paidResults, paidProducts, peopleAlsoAsk, etc.
    """
    if not items or not isinstance(items, list):
        return {"ok": False, "error": "empty apify response"}

    # First (only) page item
    page = items[0]
    organic = page.get("organicResults") or []

    serp_results = []
    citation_urls = []
    ai_overview = None
    related_questions = []

    for i, item in enumerate(organic[:10], start=1):
        url = item.get("url")
        if not url:
            continue
        serp_results.append({
            "position": item.get("position") or i,
            "title":    item.get("title"),
            "url":      url,
            "snippet":  item.get("description") or item.get("snippet"),
            "domain":   urlparse(url).netloc.replace("www.", ""),
        })
        citation_urls.append(url)

    paa = page.get("peopleAlsoAsk") or []
    related_questions = [q.get("question") for q in paa if q.get("question")]

    # Featured snippet / AI overview if present
    fs = page.get("aiOverview") or page.get("featuredSnippet")
    if fs and isinstance(fs, dict):
        ai_overview = fs.get("text") or fs.get("description") or fs.get("snippet")

    return {
        "ok": True,
        "engine_type": "serp",
        "model": "google-serp-via-apify",
        "web_search_enabled": True,
        "llm_answer_text": None,
        "citation_urls": citation_urls,
        "serp_results": serp_results,
        "serp_organic_count": len(serp_results),
        "serp_ai_overview": ai_overview,
        "related_questions": related_questions,
        "raw": page,
    }
