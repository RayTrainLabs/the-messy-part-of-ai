#!/usr/bin/env python3
"""
Phase 1 — Website scraping.

Crawls the brand's website and writes one clean markdown file per page to
output/website_pages/, plus a structured index at output/website_pages/_index.json.

Modes:
  - Apify (preferred when APIFY_TOKEN is set) — uses apify/website-content-crawler
  - Local (fallback) — uses requests + beautifulsoup4 with sitemap-aware discovery

Usage:
    python scrape_website.py "https://acme.com" \
        --max-pages 250 --max-depth 4 \
        --out-dir output/website_pages/

    python scrape_website.py "https://acme.com" --include-subdomains true ...
"""

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
from xml.etree import ElementTree as ET

import requests

THIS_DIR = Path(__file__).parent
sys.path.insert(0, str(THIS_DIR))
from providers import apify_crawler  # noqa: E402

# Lazy-import bs4 so --help works without it installed (Apify mode doesn't need it).
try:
    from bs4 import BeautifulSoup
    _BS4_OK = True
except ImportError:
    _BS4_OK = False


UA = "Mozilla/5.0 (compatible; AEOContentBot/1.0; +https://github.com/anthropics/skills)"
TIMEOUT = 20

UGC_HINTS = [
    "testimonial", "testimonials", "review", "reviews", "customer-story",
    "customer-stories", "case-stud", "g2", "capterra", "trustpilot",
]


# ---------- common helpers ----------

def slugify(url):
    p = urlparse(url)
    path = p.path.strip("/").replace("/", "-") or "home"
    path = re.sub(r"[^a-zA-Z0-9-]", "-", path)
    path = re.sub(r"-+", "-", path)[:80]
    return path or "page"


def classify_page_type(url, title, h1, body_text):
    u = (url or "").lower()
    t = (title or "").lower()
    body_lower = (body_text or "").lower()

    if re.search(r"/blog(/|$)|/articles?(/|$)|/news(/|$)|/posts?(/|$)", u):
        return "blog"
    if re.search(r"/pricing(/|$)|/plans(/|$)", u):
        return "pricing"
    if re.search(r"/customers?(/|$)|/case-stud|/stories?(/|$)|/success-stories?(/|$)", u):
        return "customer-story"
    if re.search(r"/features?(/|$)|/product(s)?(/|$)|/platform(/|$)|/solutions?(/|$)", u):
        return "product"
    if re.search(r"/about|/team|/careers?|/jobs(/|$)|/our-story", u):
        return "company"
    if re.search(r"/docs?(/|$)|/help(/|$)|/support(/|$)|/api(/|$)|/reference(/|$)", u):
        return "docs"
    if re.search(r"/legal(/|$)|/privacy|/terms|/security|/compliance", u):
        return "legal"
    if re.search(r"/vs/|/compare/|/comparison", u) or " vs " in t:
        return "comparison"
    if re.search(r"/integrations?(/|$)|/connectors?(/|$)", u):
        return "integration"
    if urlparse(url).path.strip("/") == "":
        return "marketing"
    return "other"


def detect_ugc(url, title, body_text):
    u = (url or "").lower()
    t = (title or "").lower()
    if any(hint in u or hint in t for hint in UGC_HINTS):
        return True
    body_lower = (body_text or "").lower()
    # Heuristic: lots of star-rating or reviewer-name patterns
    if re.search(r"\bstar(s)?\s*(out of|/)\s*5\b", body_lower) and body_lower.count("review") >= 4:
        return True
    return False


def write_markdown_file(out_dir, page_id, page_record, body_md):
    slug = slugify(page_record["url"])
    fname = f"{page_id}__{slug}.md"
    path = out_dir / fname

    fm_lines = ["---"]
    for k in ("url", "title", "h1", "meta_description", "page_type", "is_ugc", "scraped_at"):
        v = page_record.get(k)
        if v is None or v == "":
            continue
        if isinstance(v, bool):
            fm_lines.append(f"{k}: {str(v).lower()}")
        else:
            fm_lines.append(f"{k}: {str(v).replace(chr(10), ' ').strip()}")

    if page_record.get("internal_links_out_list"):
        fm_lines.append("internal_links_out:")
        for u in page_record["internal_links_out_list"][:50]:
            fm_lines.append(f"  - {u}")
    if page_record.get("external_links_out_list"):
        fm_lines.append("external_links_out:")
        for u in page_record["external_links_out_list"][:20]:
            fm_lines.append(f"  - {u}")
    fm_lines.append("---")
    fm_lines.append("")

    body = body_md.strip() + "\n"
    path.write_text("\n".join(fm_lines) + body, encoding="utf-8")
    return fname


def extract_links(soup, base_url):
    base_netloc = urlparse(base_url).netloc
    internal, external = [], []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(base_url, href)
        full = urldefrag(full)[0].rstrip("/")
        if not full:
            continue
        host = urlparse(full).netloc
        if not host:
            continue
        if host == base_netloc or host.endswith("." + base_netloc):
            internal.append(full)
        else:
            external.append(full)
    return list(dict.fromkeys(internal)), list(dict.fromkeys(external))


def html_to_markdown(html, base_url):
    """Light-touch HTML -> readable plain-markdown extraction for the local fallback.

    The judge LLM in Phase 2 only needs readable prose to reason about content; it
    does not need carefully reconstructed lists / code blocks. Strip nav/footer/etc,
    preserve heading hierarchy and paragraphs, and dump everything else as text.
    Apify mode bypasses this entirely (the crawler returns clean markdown directly).
    """
    soup = BeautifulSoup(html, "lxml")
    for s in soup(["script", "style", "noscript", "iframe", "form", "svg"]):
        s.decompose()

    main = soup.body or soup
    main_soup = BeautifulSoup(str(main), "lxml")
    for s in main_soup(["nav", "header", "footer", "aside"]):
        s.decompose()

    out = []
    for el in main_soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote"]):
        text = el.get_text(separator=" ", strip=True)
        if not text:
            continue
        if el.name.startswith("h"):
            level = int(el.name[1])
            out.append("#" * level + " " + text)
        elif el.name == "li":
            out.append("- " + text)
        elif el.name == "blockquote":
            out.append("> " + text)
        else:
            out.append(text)
        out.append("")  # blank line separator

    md = re.sub(r"\n{3,}", "\n\n", "\n".join(out).strip())
    return md, soup


# ---------- Apify mode ----------

def crawl_apify(start_url, max_pages, max_depth, include_subdomains, respect_robots, out_dir):
    print(f"Mode: apify   actor: apify/website-content-crawler", file=sys.stderr)
    items = apify_crawler.crawl(
        start_url=start_url,
        max_pages=max_pages,
        max_depth=max_depth,
        include_subdomains=include_subdomains,
        respect_robots=respect_robots,
    )
    print(f"Apify returned {len(items)} pages.", file=sys.stderr)

    pages = []
    for i, item in enumerate(items, start=1):
        url = item.get("url") or item.get("loadedUrl")
        if not url:
            continue
        title = (item.get("metadata") or {}).get("title") or item.get("title") or ""
        meta_desc = (item.get("metadata") or {}).get("description") or ""
        body_md = item.get("markdown") or ""
        body_text = item.get("text") or ""
        h1 = ""
        m = re.search(r"^#\s+(.+)$", body_md, re.MULTILINE)
        if m:
            h1 = m.group(1).strip()

        is_ugc = detect_ugc(url, title, body_text)
        page_type = classify_page_type(url, title, h1, body_text)
        if is_ugc:
            page_type = "ugc" if page_type == "other" else page_type

        # links: Apify gives us links in metadata sometimes; fall back to none
        internal_links = (item.get("metadata") or {}).get("internalLinks") or []
        external_links = (item.get("metadata") or {}).get("externalLinks") or []

        wc = len(re.findall(r"\b\w+\b", body_text))
        h2s = re.findall(r"^##\s+(.+)$", body_md, re.MULTILINE)

        pid = f"p{i:03d}"
        rec = {
            "id": pid,
            "url": url,
            "title": title,
            "h1": h1 or title,
            "meta_description": meta_desc,
            "page_type": page_type,
            "is_ugc": is_ugc,
            "word_count": wc,
            "h2_headings": h2s[:20],
            "internal_links_out": len(internal_links),
            "external_links_out": len(external_links),
            "internal_links_out_list": internal_links[:50],
            "external_links_out_list": external_links[:20],
            "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "scraped_ok": bool(body_md or body_text),
        }
        if not rec["scraped_ok"]:
            pages.append(rec); continue

        rec["path_md"] = write_markdown_file(out_dir, pid, rec, body_md or body_text)
        pages.append(rec)
    return pages


# ---------- local mode ----------

def discover_sitemap_urls(start_url):
    base = start_url.rstrip("/")
    candidates = [f"{base}/sitemap.xml", f"{base}/sitemap_index.xml", f"{base}/sitemap-index.xml"]
    found = []
    for sm in candidates:
        try:
            r = requests.get(sm, headers={"User-Agent": UA}, timeout=TIMEOUT)
        except requests.RequestException:
            continue
        if r.status_code != 200 or "xml" not in r.headers.get("content-type", "").lower():
            continue
        try:
            root = ET.fromstring(r.text)
        except ET.ParseError:
            continue
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        # If it's an index, recurse one level
        for sub in root.findall("sm:sitemap/sm:loc", ns):
            try:
                sr = requests.get(sub.text, headers={"User-Agent": UA}, timeout=TIMEOUT)
                if sr.status_code == 200:
                    sub_root = ET.fromstring(sr.text)
                    found += [u.text for u in sub_root.findall("sm:url/sm:loc", ns) if u.text]
            except Exception:
                pass
        found += [u.text for u in root.findall("sm:url/sm:loc", ns) if u.text]
    return list(dict.fromkeys(found))


def fetch_one(url):
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", "").lower():
            return None
        return {"url": r.url, "html": r.text}
    except requests.RequestException:
        return None


def crawl_local(start_url, max_pages, max_depth, include_subdomains, out_dir, respect_robots=True):
    if not _BS4_OK:
        print("ERROR: local crawl requires beautifulsoup4 + lxml.\n"
              "  Install with:  pip install -r ../requirements.txt   (the AEO skills/ root)\n"
              "  Or set APIFY_TOKEN to use the apify/website-content-crawler instead.",
              file=sys.stderr)
        sys.exit(1)

    print("Mode: local   (set APIFY_TOKEN for higher-fidelity JS rendering)", file=sys.stderr)
    base_netloc = urlparse(start_url).netloc

    # robots.txt parsing — stdlib urllib.robotparser; cheap, no extra dep
    rp = None
    if respect_robots:
        from urllib.robotparser import RobotFileParser
        try:
            rp = RobotFileParser()
            rp.set_url(f"{urlparse(start_url).scheme}://{base_netloc}/robots.txt")
            rp.read()
            print(f"robots.txt loaded from {base_netloc}/robots.txt", file=sys.stderr)
        except Exception as e:
            print(f"warning: could not load robots.txt ({e}); proceeding without robots checks",
                  file=sys.stderr)
            rp = None

    # Seed from sitemap if available, otherwise just the start URL
    seed_urls = discover_sitemap_urls(start_url)
    print(f"Discovered {len(seed_urls)} URLs from sitemap.", file=sys.stderr)
    if not seed_urls:
        seed_urls = [start_url]

    # Filter to in-scope URLs (and robots-allowed if applicable)
    def in_scope(u):
        if not u: return False
        h = urlparse(u).netloc
        if not h: return False
        if h == base_netloc:
            pass
        elif include_subdomains and h.endswith("." + base_netloc):
            pass
        else:
            return False
        if rp and not rp.can_fetch(UA, u):
            return False
        return True

    queue = [(u, 0) for u in seed_urls if in_scope(u)][:max_pages * 3]
    seen = set()
    pages = []
    next_id = 1

    while queue and len(pages) < max_pages:
        batch = []
        new_queue = []
        for u, d in queue:
            url_norm = urldefrag(u)[0].rstrip("/")
            if url_norm in seen:
                continue
            seen.add(url_norm)
            batch.append((url_norm, d))
            if len(batch) >= 10:
                break
        queue = queue[len(batch):] + new_queue

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(fetch_one, u): (u, d) for u, d in batch}
            for fut in as_completed(futures):
                u, d = futures[fut]
                got = fut.result()
                if not got:
                    continue
                if len(pages) >= max_pages:
                    break

                body_md, soup = html_to_markdown(got["html"], got["url"])
                title_tag = soup.find("title")
                title = title_tag.get_text(strip=True) if title_tag else ""
                h1_tag = soup.find("h1")
                h1 = h1_tag.get_text(strip=True) if h1_tag else ""
                md_tag = soup.find("meta", attrs={"name": "description"})
                meta_desc = md_tag.get("content", "").strip() if md_tag else ""
                body_text = soup.get_text(separator=" ", strip=True)

                internal, external = extract_links(soup, got["url"])
                # Enqueue more in-scope links if depth allows
                if d < max_depth:
                    for nxt in internal[:30]:
                        if nxt not in seen and in_scope(nxt):
                            queue.append((nxt, d + 1))

                is_ugc = detect_ugc(got["url"], title, body_text)
                page_type = classify_page_type(got["url"], title, h1, body_text)
                if is_ugc:
                    page_type = "ugc" if page_type == "other" else page_type

                wc = len(re.findall(r"\b\w+\b", body_text))
                h2s = re.findall(r"^##\s+(.+)$", body_md, re.MULTILINE)

                pid = f"p{next_id:03d}"; next_id += 1
                rec = {
                    "id": pid,
                    "url": got["url"],
                    "title": title,
                    "h1": h1,
                    "meta_description": meta_desc,
                    "page_type": page_type,
                    "is_ugc": is_ugc,
                    "word_count": wc,
                    "h2_headings": h2s[:20],
                    "internal_links_out": len(internal),
                    "external_links_out": len(external),
                    "internal_links_out_list": internal[:50],
                    "external_links_out_list": external[:20],
                    "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "scraped_ok": bool(body_md and wc > 20),
                }
                rec["path_md"] = write_markdown_file(out_dir, pid, rec, body_md)
                pages.append(rec)
                if len(pages) % 10 == 0:
                    print(f"  ... crawled {len(pages)} pages", file=sys.stderr)

    return pages


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("homepage")
    ap.add_argument("--max-pages", type=int, default=250)
    ap.add_argument("--max-depth", type=int, default=4)
    ap.add_argument("--include-subdomains", default="false",
                    choices=["true", "false"])
    ap.add_argument("--respect-robots", default="true",
                    choices=["true", "false"])
    ap.add_argument("--language", default="en")
    ap.add_argument("--out-dir", default="output/website_pages/")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    include_subs = args.include_subdomains == "true"
    respect_robots = args.respect_robots == "true"

    if apify_crawler.is_available():
        try:
            pages = crawl_apify(args.homepage, args.max_pages, args.max_depth,
                                include_subs, respect_robots, out_dir)
        except Exception as e:
            print(f"Apify failed ({e}); falling back to local crawler.", file=sys.stderr)
            pages = crawl_local(args.homepage, args.max_pages, args.max_depth,
                                include_subs, out_dir, respect_robots=respect_robots)
    else:
        pages = crawl_local(args.homepage, args.max_pages, args.max_depth,
                            include_subs, out_dir, respect_robots=respect_robots)

    successful = [p for p in pages if p.get("scraped_ok")]
    by_type = {}
    for p in successful:
        by_type[p["page_type"]] = by_type.get(p["page_type"], 0) + 1
    ugc_count = sum(1 for p in successful if p.get("is_ugc"))

    index = {
        "homepage": args.homepage,
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": "apify" if apify_crawler.is_available() else "local",
        "page_count": len(successful),
        "pages": successful,
    }
    with open(out_dir / "_index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    print(f"\nDone. {len(successful)}/{len(pages)} pages saved successfully.", file=sys.stderr)
    print(f"Page-type breakdown: {by_type}", file=sys.stderr)
    print(f"UGC pages flagged: {ugc_count} (excluded from edit-target list)", file=sys.stderr)
    print(f"Index -> {out_dir / '_index.json'}", file=sys.stderr)


if __name__ == "__main__":
    main()
