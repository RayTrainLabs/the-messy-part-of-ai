#!/usr/bin/env python3
"""
Fetch a fresh brand-context snapshot from a website.

Crawls the homepage and a small set of nav-linked pages (about, products, pricing,
customers, etc., discovered via heuristics — no hardcoded paths). Extracts brand
signals downstream phases use: name, tagline, value prop, products, voice
samples, logo URL, social profiles.

Usage:
    python fetch_brand_context.py https://example.com [--max-pages 12] [--out brand_raw.json]

Dependencies:
    pip install requests beautifulsoup4 lxml
"""

import argparse
import json
import re
import sys
import time
from collections import OrderedDict
from urllib.parse import urljoin, urlparse

import requests

# Lazy-import BeautifulSoup so `--help` works even when beautifulsoup4 isn't
# installed yet. This script is the documented Phase 0 fallback when no brand
# docs are supplied; surfacing a clean install hint at first real call beats
# crashing on import.
try:
    from bs4 import BeautifulSoup  # noqa: F401
    _BS4_OK = True
except ImportError:
    _BS4_OK = False


def _require_bs4():
    if not _BS4_OK:
        print("ERROR: beautifulsoup4 is required for the website crawl.\n"
              "  Install with:  pip install -r requirements.txt\n"
              "  (requirements.txt is at the AEO skills/ root, alongside this skill folder.)",
              file=sys.stderr)
        sys.exit(1)


UA = "Mozilla/5.0 (compatible; AEOBrandContextBot/1.0)"
TIMEOUT = 15

NAV_HINTS = OrderedDict([
    ("about",        ["about", "about us", "our story", "who we are", "company"]),
    ("product",      ["product", "products", "platform", "features", "solutions", "what we do"]),
    ("pricing",      ["pricing", "plans", "buy", "subscribe"]),
    ("customers",    ["customers", "case studies", "stories", "case study", "testimonials"]),
    ("contact",      ["contact", "support", "help", "locations"]),
    ("team",         ["team", "leadership", "people"]),
    ("compare",      ["vs", "comparison", "alternatives", "alternative to"]),
])

SOCIAL_HOSTS = ["linkedin.com", "twitter.com", "x.com", "facebook.com", "instagram.com",
                "youtube.com", "github.com", "tiktok.com", "pinterest.com", "crunchbase.com"]


def fetch(url):
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", "").lower():
            return None
        return {"final_url": r.url, "html": r.text}
    except requests.RequestException:
        return None


def extract_page(html, base_url):
    soup = BeautifulSoup(html, "lxml")
    for s in soup(["script", "style", "noscript"]):
        s.decompose()

    title = soup.find("title")
    h1 = soup.find("h1")
    md = soup.find("meta", attrs={"name": "description"})
    og_title = soup.find("meta", property="og:title")
    og_desc = soup.find("meta", property="og:description")
    og_image = soup.find("meta", property="og:image")
    og_site = soup.find("meta", property="og:site_name")
    icon = soup.find("link", rel=lambda v: v and "icon" in v.lower())

    body_soup = BeautifulSoup(html, "lxml")
    for s in body_soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
        s.decompose()
    body_text = body_soup.get_text(separator=" ", strip=True)

    return {
        "url": base_url,
        "title": title.get_text(strip=True) if title else None,
        "h1": h1.get_text(strip=True) if h1 else None,
        "meta_description": md.get("content", "").strip() if md else None,
        "og_title": og_title.get("content") if og_title else None,
        "og_description": og_desc.get("content") if og_desc else None,
        "og_image": urljoin(base_url, og_image.get("content")) if og_image else None,
        "og_site_name": og_site.get("content") if og_site else None,
        "favicon": urljoin(base_url, icon.get("href")) if icon and icon.get("href") else None,
        "body_preview": body_text[:2000],
    }


def find_nav_links(html, base_url):
    soup = BeautifulSoup(html, "lxml")
    base_netloc = urlparse(base_url).netloc

    candidates = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(base_url, href).split("#")[0].rstrip("/")
        if not full or urlparse(full).netloc != base_netloc:
            continue

        anchor = a.get_text(strip=True)
        if not anchor or len(anchor) > 80:
            continue

        anchor_lower = anchor.lower()
        for category, hints in NAV_HINTS.items():
            for hint in hints:
                if re.search(rf"\b{re.escape(hint)}\b", anchor_lower):
                    candidates.setdefault(full, {"url": full, "anchor": anchor, "categories": []})
                    if category not in candidates[full]["categories"]:
                        candidates[full]["categories"].append(category)
                    break

    return sorted(candidates.values(), key=lambda c: -len(c["categories"]))


def find_social_links(html):
    soup = BeautifulSoup(html, "lxml")
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        for host in SOCIAL_HOSTS:
            if host in href:
                links.add(href.split("?")[0])
                break
    return sorted(links)


def synthesize_brand_facts(home, others):
    name = (home.get("og_site_name")
            or (home.get("title") or "").split("|")[0].split("—")[0].split("·")[0].strip())
    tagline = home.get("h1") or home.get("og_description") or home.get("meta_description")
    description = home.get("meta_description") or home.get("og_description")

    voice_samples = [home.get("body_preview")] if home.get("body_preview") else []
    for p in others:
        title = (p.get("title") or "").lower()
        if "about" in title or (p.get("url", "") or "").endswith(("/about", "/about-us")):
            if p.get("body_preview"):
                voice_samples.append(p["body_preview"])

    return {
        "brand_name": name or None,
        "tagline": tagline,
        "description": description,
        "logo_url": home.get("og_image") or home.get("favicon"),
        "voice_samples": voice_samples[:3],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("homepage")
    p.add_argument("--max-pages", type=int, default=12)
    p.add_argument("--delay", type=float, default=0.4)
    p.add_argument("--out", default="brand_raw.json")
    args = p.parse_args()

    _require_bs4()
    print(f"Fetching homepage: {args.homepage}", file=sys.stderr)
    home_fetch = fetch(args.homepage)
    if not home_fetch:
        print(f"ERROR: could not fetch {args.homepage}", file=sys.stderr)
        sys.exit(1)

    home = extract_page(home_fetch["html"], home_fetch["final_url"])
    nav_candidates = find_nav_links(home_fetch["html"], home_fetch["final_url"])
    social = find_social_links(home_fetch["html"])

    other_pages = []
    seen_categories = set()
    for cand in nav_candidates:
        if len(other_pages) >= args.max_pages:
            break
        new_cats = [c for c in cand["categories"] if list(seen_categories).count(c) < 2]
        if not new_cats and seen_categories:
            continue
        time.sleep(args.delay)
        page_fetch = fetch(cand["url"])
        if not page_fetch:
            continue
        page = extract_page(page_fetch["html"], page_fetch["final_url"])
        page["nav_anchor"] = cand["anchor"]
        page["nav_categories"] = cand["categories"]
        other_pages.append(page)
        for c in cand["categories"]:
            seen_categories.add(c)

    facts = synthesize_brand_facts(home, other_pages)

    out = {
        "homepage": home_fetch["final_url"],
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "brand_facts": facts,
        "social_profiles": social,
        "homepage_data": home,
        "supporting_pages": other_pages,
        "categories_covered": sorted(seen_categories),
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"Wrote {args.out}", file=sys.stderr)
    print(f"  Brand: {facts['brand_name']}", file=sys.stderr)
    print(f"  Pages explored: {len(other_pages)} ({sorted(seen_categories)})", file=sys.stderr)


if __name__ == "__main__":
    main()
