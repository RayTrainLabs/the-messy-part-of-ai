#!/usr/bin/env python3
"""
extract_citations.py — Enrich AEO-01 scored_rows.jsonl with cited URLs parsed
from the raw LLM responses.

For each scored row, finds the matching raw response and extracts URLs using
three patterns:
  1. Markdown links: [text](url)
  2. Plain URLs: https://example.com/path
  3. Domain-prefixed paths: example.com/path (without protocol)

Writes the same scored_rows.jsonl with an added `cited_urls` field per row
(list of normalized URLs).

Known limits (intentionally NOT supported):
  - Internationalized domain names (IDN / punycode like xn--bcher-kva.example)
    are not recognized; the regex character class is ASCII-only.
  - HTML entities inside URLs (e.g., &amp;) are not decoded; they pass through
    verbatim in the captured URL string.
  - URLs with literal commas in the path are truncated at the first comma so
    that comma-separated URL lists parse as multiple URLs.
  - Balanced parentheses inside paths (e.g., Wikipedia "_(disambig)" URLs) are
    handled on a best-effort basis only via trailing-punct balancing.

Usage:
    python3 extract_citations.py \\
      --raw   runs/2026-05-04/raw_responses.jsonl \\
      --scored runs/2026-05-04/scored_rows.jsonl \\
      [--in-place]
"""

import argparse
import json
import re
import sys
from pathlib import Path


# Match markdown links [text](url)
_MD_LINK_RE = re.compile(r"\[(?:[^\]]+)\]\((https?://[^\s)]+)\)")
# Match plain URLs (http/https).
# Note: comma is intentionally EXCLUDED from the path character class so that
# "Sources: https://a.com, https://b.com" yields two URLs, not one. This is a
# small backward-incompatibility trade-off: URLs with literal commas in their
# paths will be truncated at the comma. LLM-cited URLs rarely contain literal
# commas, so we accept this trade-off in exchange for robust multi-URL parsing.
_URL_RE = re.compile(r"https?://[\w\-./?=&%#:+~@]+", re.IGNORECASE)
# Match bare domain.tld/path occurrences (no protocol).
# Supports one or more subdomain labels (e.g., m.example.com, de.shop.example.co.uk).
# TLD list includes common modern TLDs (.app, .dev, .ai, .tech) in addition to
# the legacy set. Path is captured greedily but excludes commas (see _URL_RE note).
_BARE_DOMAIN_RE = re.compile(
    r"(?<![\w./@-])"
    r"((?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+"
    r"(?:tech|info|com|org|net|app|dev|biz|io|co|uk|de|fr|au|ca|us|ai|me))"
    r"(?:/[\w\-./?=&%#:+~@!*$'()]*)?",
    re.IGNORECASE,
)


def _strip_trailing_punct(url: str) -> str:
    """Strip trailing sentence/quote punctuation from a captured URL.

    Special-case: a trailing ')' is preserved when the URL contains a matching
    '(' (best-effort balanced-parens detection for Wikipedia-style URLs such as
    https://en.wikipedia.org/wiki/Foo_(bar)). When a URL ends with multiple
    punctuation characters we strip from the outside in, but stop stripping ')'
    as soon as parentheses become balanced.
    """
    while url and url[-1] in ".,;:!?)]}>\"'":
        if url[-1] == ")" and url.count("(") >= url.count(")"):
            # Balanced or unmatched-opening: trailing ')' is part of the path.
            break
        url = url[:-1]
    return url


def normalize_url(url: str) -> str:
    """Lowercase, strip protocol/www/query/fragment/trailing slash."""
    if not url:
        return ""
    u = url.strip().lower()
    u = _strip_trailing_punct(u)
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    # Drop query + fragment
    u = re.split(r"[?#]", u, maxsplit=1)[0]
    u = u.rstrip("/")
    return u


def extract_urls_from_text(text: str) -> list[str]:
    """Return a deduplicated list of normalized URLs found in `text`."""
    if not text:
        return []
    found = []

    for m in _MD_LINK_RE.finditer(text):
        found.append(m.group(1))

    for m in _URL_RE.finditer(text):
        found.append(m.group(0))

    for m in _BARE_DOMAIN_RE.finditer(text):
        # Reconstruct full match (domain + optional path)
        s, e = m.span()
        # Walk back/forward to capture optional path component
        token = text[s:e]
        # If preceded by '://' it's part of a URL we already captured — skip
        if s >= 3 and text[s-3:s] == "://":
            continue
        found.append(token)

    # Normalize + dedupe while preserving order
    seen = set()
    out = []
    for raw in found:
        norm = normalize_url(raw)
        if not norm or "." not in norm:
            continue
        # Skip pure-domain references that are too generic to be useful citations
        # (we want real source URLs, not "see openai.com" mentions)
        if "/" not in norm:
            # Domain-only citations are useful too (brand name dropped)
            # Keep but mark by suffix-free form
            pass
        if norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw",    required=True, help="raw_responses.jsonl")
    ap.add_argument("--scored", required=True, help="scored_rows.jsonl (will be enriched)")
    ap.add_argument("--in-place", action="store_true",
                    help="Overwrite the scored file (default: write to <scored>.cited.jsonl)")
    args = ap.parse_args()

    raw_path    = Path(args.raw)
    scored_path = Path(args.scored)
    if not raw_path.exists():
        print(f"ERROR: raw file not found: {raw_path}", file=sys.stderr)
        sys.exit(1)
    if not scored_path.exists():
        print(f"ERROR: scored file not found: {scored_path}", file=sys.stderr)
        sys.exit(1)

    # Index raw responses by row_id (fallback to query_id + engine)
    raw_index = {}
    with raw_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = obj.get("row_id") or f"{obj.get('query_id')}|{obj.get('engine')}"
            # Common fields the response might live under
            text = (
                obj.get("response")
                or obj.get("raw_response")
                or obj.get("text")
                or obj.get("content")
                or ""
            )
            raw_index[key] = text

    # Enrich scored rows
    output = []
    enriched_count = 0
    with scored_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = row.get("row_id") or f"{row.get('query_id')}|{row.get('engine')}"
            text = raw_index.get(key, "")
            cited = extract_urls_from_text(text)
            row["cited_urls"] = cited
            if cited:
                enriched_count += 1
            output.append(row)

    out_path = scored_path if args.in_place else scored_path.with_suffix(".cited.jsonl")
    with out_path.open("w", encoding="utf-8") as f:
        for row in output:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Enriched {len(output)} rows ({enriched_count} have cited URLs) → {out_path}")


if __name__ == "__main__":
    main()
