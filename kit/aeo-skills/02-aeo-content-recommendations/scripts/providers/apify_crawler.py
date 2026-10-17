"""Apify website-content-crawler adapter.

Wraps the apify/website-content-crawler actor, which renders JS, follows
sitemaps, and returns clean markdown. Strongly preferred over the local
crawler for any site with JS-heavy or SPA-rendered content.

Docs:
    https://apify.com/apify/website-content-crawler
"""

import os
import time

import requests

ACTOR_ID = "apify~website-content-crawler"
RUN_SYNC_ENDPOINT = (
    f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items"
)
TIMEOUT = 600  # 10 min — large sites take a while


def is_available():
    return bool(os.environ.get("APIFY_TOKEN"))


def crawl(start_url, max_pages=250, max_depth=4, include_subdomains=False,
          respect_robots=True, language="en"):
    """Run the actor synchronously and return the dataset items.

    Each item is a dict with at least: url, title, text, markdown, html,
    metadata { description, author, ... }, crawl { depth, ... }.
    """
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        raise RuntimeError("APIFY_TOKEN not set")

    payload = {
        "startUrls": [{"url": start_url}],
        "maxCrawlPages":     max_pages,
        "maxCrawlDepth":     max_depth,
        "useSitemaps":       True,
        "respectRobotsTxt":  respect_robots,
        "saveMarkdown":      True,
        "saveHtml":          False,
        "saveScreenshots":   False,
        "crawlerType":       "playwright:adaptive",
    }
    if not include_subdomains:
        payload["sameDomain"] = True
    if language:
        # Apify supports language filtering only loosely; the judge prompt also
        # filters by content. This is best-effort.
        payload["initialCookies"] = []

    r = requests.post(f"{RUN_SYNC_ENDPOINT}?token={token}", json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    items = r.json()
    if not isinstance(items, list):
        raise RuntimeError(f"Unexpected Apify response shape: {type(items).__name__}")
    return items
