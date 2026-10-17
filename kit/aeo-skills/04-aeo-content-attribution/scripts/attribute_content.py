#!/usr/bin/env python3
"""
attribute_content.py — Join a content planner against historical AEO scored runs
and emit attribution + strategy-events for the AEO dashboard.

Inputs:
  - Content planner: Google Sheet (via service-account JSON) OR local CSV
  - Runs directory: contains date-named subdirs each holding scored_rows.jsonl
  - Brand profile: standard AEO-01 brand_profile.json

Outputs:
  - attributions.json:    per-row attribution detail
  - strategy_events.json: annotations in render_dashboard.py schema
  - summary.md:           human-readable rollup
"""

import argparse
import csv
import io
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Union


logger = logging.getLogger("attribute_content")


CONTENT_TYPE_COLORS = {
    "LLMs.txt":    "#7ba05b",
    "Schema":      "#386641",
    "FAQ":         "#2d6a4f",
    "Advertorial": "#8b6f47",
    "Blog":        "#a04545",
    "Press":       "#9c6644",
}
# Lane order for the callout rows on the dashboard (top → bottom).
CONTENT_TYPE_LANES = {
    "LLMs.txt":    0,
    "Schema":      1,
    "FAQ":         2,
    "Blog":        3,
    "Advertorial": 4,
    "Press":       5,
}
BREAKOUT_LANE     = 6
DEFAULT_COLOR    = "#6b7280"
BREAKOUT_COLOR   = "#2d6a4f"
BREAKOUT_THRESHOLD_PP = 3.0
STRONG_LIFT_PP        = 2.0

# Output schema version. Bump on any breaking change to the JSON shape consumers depend on.
ATTRIBUTIONS_SCHEMA_VERSION    = "1.1"
STRATEGY_EVENTS_SCHEMA_VERSION = "1.1"


# ── Date utilities ────────────────────────────────────────────────────────────

def parse_iso(d: str) -> date:
    return datetime.strptime(d.strip(), "%Y-%m-%d").date()


def fmt_chart_label(d: date) -> str:
    """Match render_dashboard.py's real-data label format: 'Oct 20'25', 'Jan 12'26'."""
    if sys.platform != "win32":
        return d.strftime("%b %-d'%y")
    return d.strftime("%b %d'%y").lstrip("0").replace(" 0", " ")


def closest_run_date(target: date, run_dates: Iterable[date]) -> Optional[date]:
    """Return the run date nearest to `target` (no future bias)."""
    run_dates = list(run_dates)
    if not run_dates:
        return None
    return min(run_dates, key=lambda d: abs((d - target).days))


# ── Content planner loading ───────────────────────────────────────────────────

PLANNER_SCHEMA = {
    "publish_date":     ["Publish Date", "publish_date", "publish date"],
    "content_type":     ["Content Type", "content_type", "type"],
    "title_url":        ["Title / URL", "Title/URL", "title", "url"],
    "target_cluster":   ["Target Query or Cluster", "target_cluster", "cluster"],
    "lag_days":         ["Expected Attribution Lag (days)", "lag", "lag_days"],
    "status":           ["Status", "status"],
}


def _resolve_header(headers, options):
    norm = {h.strip().lower(): h for h in headers}
    for opt in options:
        if opt.lower() in norm:
            return norm[opt.lower()]
    return None


def _levenshtein(a, b, cap=3):
    # Bounded edit distance. Returns cap+1 if distance exceeds cap.
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        best_in_row = curr[0]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
            if curr[j] < best_in_row:
                best_in_row = curr[j]
        if best_in_row > cap:
            return cap + 1
        prev = curr
    return prev[-1]


def _suggest_header(canonical_key, options, headers):
    # Try close-edit and substring matches against actual headers.
    candidates = []
    headers_lower = [(h, h.strip().lower()) for h in headers]
    for opt in options:
        opt_l = opt.lower()
        for orig, h_l in headers_lower:
            if opt_l in h_l or h_l in opt_l:
                candidates.append(orig)
                continue
            if _levenshtein(opt_l, h_l, cap=2) <= 2:
                candidates.append(orig)
    # Deduplicate while preserving order.
    seen = set()
    out = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _validate_headers(headers, source_label):
    cols = {k: _resolve_header(headers, opts) for k, opts in PLANNER_SCHEMA.items()}
    missing = [k for k, v in cols.items() if v is None]
    if missing:
        parts = [f"{source_label} missing required columns: {missing}."]
        parts.append(f"Headers found: {headers}.")
        suggestion_bits = []
        for key in missing:
            sugg = _suggest_header(key, PLANNER_SCHEMA[key], headers)
            if sugg:
                suggestion_bits.append(f"{key} -> maybe {sugg}")
        if suggestion_bits:
            parts.append("Suggestions: " + "; ".join(suggestion_bits))
        raise ValueError(" ".join(parts))
    return cols


_VALID_STATUSES = {"live", "planned", "paused"}


def _validate_row_warnings(raw, cols, row_index, source_label):
    raw_date = (raw.get(cols["publish_date"]) or "").strip()
    if raw_date:
        try:
            parse_iso(raw_date)
        except Exception:
            logger.warning(
                "%s row %d: unparseable Publish Date %r (expected YYYY-MM-DD); row dropped.",
                source_label, row_index, raw_date,
            )
    status_val = (raw.get(cols["status"]) or "").strip().lower()
    if status_val and status_val not in _VALID_STATUSES:
        logger.warning(
            "%s row %d: Status %r not in %s; accepting as-is.",
            source_label, row_index, status_val, sorted(_VALID_STATUSES),
        )
    ctype_val = (raw.get(cols["content_type"]) or "").strip()
    if ctype_val and ctype_val not in CONTENT_TYPE_COLORS:
        logger.warning(
            "%s row %d: Content Type %r not in %s; will render in default color.",
            source_label, row_index, ctype_val, sorted(CONTENT_TYPE_COLORS.keys()),
        )


def _extract_sheet_id(url_or_id):
    """Pull a Google Sheets ID out of a URL, or pass through if already an ID."""
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url_or_id)
    return m.group(1) if m else url_or_id.strip()


def _extract_gid(url_or_id):
    """Pull a gid from a URL (#gid=... or &gid=...). Returns None when absent."""
    m = re.search(r"[#&?]gid=([0-9]+)", url_or_id)
    return m.group(1) if m else None


def load_planner_public_url(sheet_url_or_id: str, sheet_tab: Optional[str] = None) -> list[dict[str, Any]]:
    """
    Fetch a publicly-shared Google Sheet via its CSV export endpoint.
    Sheet must be set to 'Anyone with the link can view'.
    Retries with exponential backoff (1s, 3s, 8s) on transient failures.
    Timeout configurable via env AEO_SHEET_TIMEOUT (default 15s).
    """
    sheet_id = _extract_sheet_id(sheet_url_or_id)
    gid = _extract_gid(sheet_url_or_id)
    csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    if gid:
        csv_url += f"&gid={gid}"
    elif sheet_tab:
        csv_url += f"&sheet={urllib.parse.quote(sheet_tab)}"
    logger.info("Fetching %s", csv_url)

    try:
        timeout = float(os.environ.get("AEO_SHEET_TIMEOUT", "15"))
    except ValueError:
        timeout = 15.0

    delays = [1, 3, 8]
    last_err = None
    text = None
    for attempt, delay in enumerate(delays, start=1):
        try:
            with urllib.request.urlopen(csv_url, timeout=timeout) as resp:
                text = resp.read().decode("utf-8-sig")
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                msg = (
                    f"Google Sheet not accessible (HTTP 404). The sheet ID "
                    f"{sheet_id!r} may be wrong or the sheet was deleted."
                )
            elif e.code == 403:
                msg = (
                    f"Google Sheet not public (HTTP 403). Set sharing to "
                    f"'Anyone with the link can view' for sheet {sheet_id!r}."
                )
            else:
                msg = f"HTTP {e.code} fetching Google Sheet: {e.reason}"
            last_err = RuntimeError(msg)
            # 404 and 403 will not change between retries; fail fast.
            if e.code in (403, 404):
                break
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
                last_err = RuntimeError(
                    f"Timeout after {timeout}s fetching Google Sheet (attempt {attempt}/{len(delays)})."
                )
            else:
                last_err = RuntimeError(f"Network error fetching Google Sheet: {reason}")
        except TimeoutError:
            last_err = RuntimeError(
                f"Timeout after {timeout}s fetching Google Sheet (attempt {attempt}/{len(delays)})."
            )
        except Exception as e:
            last_err = RuntimeError(f"Unexpected error fetching Google Sheet: {e}")

        if attempt < len(delays) and text is None:
            logger.warning(
                "Sheet fetch attempt %d failed: %s. Retrying in %ds.",
                attempt, last_err, delay,
            )
            time.sleep(delay)

    if text is None:
        raise last_err or RuntimeError("Failed to fetch Google Sheet after retries.")

    rows = _parse_csv_text(text, source_label="Public Google Sheet")
    return rows


def _parse_csv_text(text: str, source_label: str = "Sheet/CSV") -> list[dict[str, Any]]:
    rows = []
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    cols = _validate_headers(headers, source_label)
    # csv.DictReader has already consumed the header row, so the first data row
    # is line 2 in the source spreadsheet.
    for offset, raw in enumerate(reader, start=2):
        _validate_row_warnings(raw, cols, offset, source_label)
        try:
            pub = parse_iso(raw[cols["publish_date"]])
        except Exception:
            continue
        try:
            lag = int(float(raw[cols["lag_days"]] or 14))
        except Exception:
            lag = 14
        rows.append({
            "publish_date":   pub,
            "content_type":   (raw[cols["content_type"]] or "").strip(),
            "title_url":      (raw[cols["title_url"]] or "").strip(),
            "target_cluster": (raw[cols["target_cluster"]] or "").strip(),
            "lag_days":       lag,
            "status":         (raw[cols["status"]] or "").strip().lower(),
        })
    return rows


def load_planner_csv(path: Union[str, Path]) -> list[dict[str, Any]]:
    rows = []
    source_label = f"Content planner CSV ({path})"
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        cols = _validate_headers(headers, source_label)
        for offset, raw in enumerate(reader, start=2):
            _validate_row_warnings(raw, cols, offset, source_label)
            try:
                pub = parse_iso(raw[cols["publish_date"]])
            except Exception:
                continue
            try:
                lag = int(float(raw[cols["lag_days"]] or 14))
            except Exception:
                lag = 14
            rows.append({
                "publish_date":  pub,
                "content_type":  (raw[cols["content_type"]] or "").strip(),
                "title_url":     (raw[cols["title_url"]] or "").strip(),
                "target_cluster": (raw[cols["target_cluster"]] or "").strip(),
                "lag_days":      lag,
                "status":        (raw[cols["status"]] or "").strip().lower(),
            })
    return rows


def load_planner_sheet(sheet_id: str, sheet_tab: str, service_account_json: str) -> list[dict[str, Any]]:
    try:
        import gspread
    except ImportError:
        logger.error("gspread not installed. Run: pip install gspread google-auth")
        sys.exit(1)
    gc = gspread.service_account(filename=service_account_json)
    ws = gc.open_by_key(sheet_id).worksheet(sheet_tab)
    records = ws.get_all_records()
    if not records:
        return []
    headers = list(records[0].keys())
    cols = {k: _resolve_header(headers, opts) for k, opts in PLANNER_SCHEMA.items()}
    missing = [k for k, v in cols.items() if v is None]
    if missing:
        raise ValueError(f"Sheet missing columns: {missing}")
    rows = []
    for raw in records:
        try:
            pub = parse_iso(str(raw[cols["publish_date"]]))
        except Exception:
            continue
        try:
            lag = int(float(raw[cols["lag_days"]] or 14))
        except Exception:
            lag = 14
        rows.append({
            "publish_date":   pub,
            "content_type":   str(raw[cols["content_type"]] or "").strip(),
            "title_url":      str(raw[cols["title_url"]] or "").strip(),
            "target_cluster": str(raw[cols["target_cluster"]] or "").strip(),
            "lag_days":       lag,
            "status":         str(raw[cols["status"]] or "").strip().lower(),
        })
    return rows


# ── Run history loading ───────────────────────────────────────────────────────

def _load_jsonl_rows(rows_path: Path) -> list:
    """Read one scored_rows.jsonl file into a list of dicts. Returns [] on read errors."""
    rows = []
    try:
        with rows_path.open("r", encoding="utf-8") as fh:
            for line_no, raw_line in enumerate(fh, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as e:
                    logger.warning("%s line %d: malformed JSON, skipping (%s)",
                                   rows_path, line_no, e)
    except OSError as e:
        logger.warning("Skipping %s: read error (%s)", rows_path, e)
        return []
    return rows


def _discover_run_paths(runs_dir: Union[str, Path]) -> list[tuple[date, Path]]:
    """Walk runs_dir, return sorted list of (date, jsonl_path) pairs."""
    found: list[tuple[date, Path]] = []
    root = Path(runs_dir)
    if not root.exists():
        return found
    for child in sorted(root.iterdir()):
        date_str = None
        rows_path = None
        if child.is_dir():
            m = re.match(r"(\d{4}-\d{2}-\d{2})", child.name)
            if m:
                date_str = m.group(1)
                candidate = child / "scored_rows.jsonl"
                if candidate.exists():
                    rows_path = candidate
        elif child.is_file() and child.suffix == ".jsonl":
            m = re.match(r"(\d{4}-\d{2}-\d{2})", child.name)
            if m:
                date_str = m.group(1)
                rows_path = child
        if date_str and rows_path:
            try:
                d = parse_iso(date_str)
            except ValueError as e:
                logger.warning("Skipping %s: invalid date in name (%s)", rows_path, e)
                continue
            found.append((d, rows_path))
    return sorted(found, key=lambda x: x[0])


class RunHistory:
    """
    Sequence-like view over run history that supports both eager (in-memory)
    and lazy (load-on-access with LRU cache) backing.

    Iterating yields (date, rows) tuples in sorted-by-date order. Indexing by
    date returns rows; indexing by integer returns (date, rows). Drops in as
    a replacement for the previous list-of-tuples shape consumed by
    compute_attribution and build_strategy_events.
    """

    def __init__(self, dates: list, loader: Callable[[date], list]):
        self._dates: list = list(dates)
        self._loader = loader
        self._cache: Any = None
        self._cache_size: int = 0

    @classmethod
    def eager(cls, runs_list) -> "RunHistory":
        """Wrap a pre-loaded [(date, rows), ...] list."""
        sorted_list = sorted(runs_list, key=lambda x: x[0])
        materialized = {d: rows for d, rows in sorted_list}
        dates = [d for d, _ in sorted_list]
        def _loader(d: date) -> list:
            return materialized[d]
        return cls(dates, _loader)

    @classmethod
    def lazy_from_dir(cls, runs_dir, cache_size: int = 8) -> "RunHistory":
        """Discover dated subdirs; load scored_rows.jsonl per date on demand."""
        discovered = _discover_run_paths(runs_dir)
        # Skip files that yield zero usable rows? We can't know without reading.
        # Defer until first access; empty rows get filtered at consumption time
        # only via cache check below.
        path_map = {d: p for d, p in discovered}
        dates = [d for d, _ in discovered]

        from collections import OrderedDict
        cache: "OrderedDict[date, list]" = OrderedDict()

        def _loader(d: date) -> list:
            if d in cache:
                cache.move_to_end(d)
                return cache[d]
            rows = _load_jsonl_rows(path_map[d])
            cache[d] = rows
            cache.move_to_end(d)
            while len(cache) > cache_size:
                cache.popitem(last=False)
            return rows

        inst = cls(dates, _loader)
        inst._cache = cache  # expose for tests
        inst._cache_size = cache_size
        return inst

    def dates(self) -> list:
        return list(self._dates)

    def __iter__(self):
        for d in self._dates:
            yield d, self._loader(d)

    def __len__(self) -> int:
        return len(self._dates)

    def __getitem__(self, key):
        if isinstance(key, date):
            return self._loader(key)
        if isinstance(key, int):
            d = self._dates[key]
            return d, self._loader(d)
        raise TypeError(f"RunHistory index must be date or int, got {type(key).__name__}")

    def __contains__(self, key) -> bool:
        if isinstance(key, date):
            return key in self._dates
        return False


def load_runs(runs_dir: Union[str, Path]) -> "RunHistory":
    """
    Returns a RunHistory (eager) over (date, scored_rows) sorted by date.
    Accepts:
      runs_dir/YYYY-MM-DD/scored_rows.jsonl
      runs_dir/YYYY-MM-DD_scored_rows.jsonl

    Backward compatible: iteration yields (date, rows) and len()/indexing match
    the prior list-of-tuples shape.
    """
    discovered = _discover_run_paths(runs_dir)
    runs = []
    for d, rows_path in discovered:
        rows = _load_jsonl_rows(rows_path)
        if rows:
            runs.append((d, rows))
        else:
            logger.warning("Skipping %s: file produced zero usable rows", rows_path)
    return RunHistory.eager(runs)


def load_runs_lazy(runs_dir, cache_size: int = 8) -> "RunHistory":
    """Same as load_runs but loads each date's scored_rows.jsonl on demand."""
    return RunHistory.lazy_from_dir(runs_dir, cache_size=cache_size)


# ── Presence math ─────────────────────────────────────────────────────────────

def target_in_row(row: dict[str, Any], target_lower: str) -> bool:
    for b in row.get("brands_mentioned_list", []) or []:
        if not b:
            continue
        b_l = str(b).lower().strip()
        if b_l == target_lower or target_lower in b_l or b_l in target_lower:
            return True
    return False


def presence_pct(rows: list, target_lower: str, query_filter: Optional[Callable] = None) -> float:
    """% of rows in which target brand is mentioned, optionally filtered."""
    relevant = [r for r in rows if (query_filter is None or query_filter(r))]
    if not relevant:
        return 0.0
    hits = sum(1 for r in relevant if target_in_row(r, target_lower))
    return hits / len(relevant) * 100.0


_STOPWORDS = {
    "the","a","an","and","or","of","to","for","in","on","at","by","with","from",
    "is","are","was","were","be","been","being","do","does","did","done",
    "i","you","we","they","it","this","that","these","those","my","your","our","their",
    "how","what","when","where","why","which","who","whose","whom",
    "best","good","top","new","tips","guide","guides",  # generic SEO filler
}


# ── URL handling for citation matching ─────────────────────────────────────────

def normalize_url(url: str) -> str:
    """Lowercase, strip protocol/www/subdomain-prefix/query/fragment/trailing slash."""
    if not url:
        return ""
    u = str(url).strip().lower()
    while u and u[-1] in ".,;:!?)]}>\"'":
        u = u[:-1]
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    u = re.split(r"[?#]", u, maxsplit=1)[0]
    return u.rstrip("/")


def url_matches(content_url: str, cited_url: str) -> bool:
    """
    Return True if `cited_url` likely refers to `content_url`. We compare:
      - exact normalized match
      - cited domain+path is a prefix of content normalized URL
      - content normalized path is a suffix of cited (allowing /amp/ /print/ variants)
    """
    c = normalize_url(content_url)
    x = normalize_url(cited_url)
    if not c or not x:
        return False
    if c == x:
        return True
    # Trim regional subdomains (row., us., uk.) for comparison
    def _strip_region(u):
        return re.sub(r"^(row|us|uk|eu|de|fr|au|ca|jp|na)\.", "", u)
    if _strip_region(c) == _strip_region(x):
        return True
    # Path-suffix match: same path under same domain even if subdomain differs
    def _domain_path(u):
        parts = u.split("/", 1)
        domain = parts[0]
        path   = "/" + parts[1] if len(parts) > 1 else ""
        return domain, path
    cd, cp = _domain_path(_strip_region(c))
    xd, xp = _domain_path(_strip_region(x))
    if cd == xd and cp and xp and (cp == xp or cp.startswith(xp) or xp.startswith(cp)):
        return True
    return False


def is_url_cited(content_url: str, rows) -> int:
    """Count how many rows cite the content URL (via cited_urls field)."""
    if not content_url:
        return 0
    count = 0
    for r in rows:
        for cu in r.get("cited_urls", []) or []:
            if url_matches(content_url, cu):
                count += 1
                break
    return count


def _stem(t):
    # Cheap pluralization stripping; good enough for SEO keywords
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 3 and t.endswith("es") and not t.endswith("ses"):
        return t[:-2]
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


@lru_cache(maxsize=8192)
def _tokenize_cached(text: str) -> tuple:
    raw = re.findall(r"[a-z0-9']+", text.lower())
    return tuple(_stem(t) for t in raw if t and t not in _STOPWORDS and len(t) >= 3)


def _tokenize(text):
    """List version of _tokenize_cached. Cached internally; safe under repeated calls."""
    if text is None:
        return []
    return list(_tokenize_cached(str(text)))


@lru_cache(maxsize=4096)
def _cluster_term_tokens_cached(cluster_str: str) -> tuple:
    """Cached: tuple of frozensets, one per comma-separated cluster term."""
    if not cluster_str:
        return tuple()
    terms = [t.strip().lower() for t in cluster_str.split(",") if t.strip()]
    out = []
    for t in terms:
        toks = frozenset(_tokenize(t))
        if toks:
            out.append(toks)
    return tuple(out)


def _cluster_term_tokens(cluster_str: str) -> list:
    """Tokenize each cluster term separately. Returns list of token sets.
    Backed by an LRU cache on the immutable-tuple form."""
    return [set(s) for s in _cluster_term_tokens_cached(cluster_str or "")]


@lru_cache(maxsize=16384)
def _cluster_score_cached(cluster_str: str, query_text: str) -> float:
    """Cached score impl. Uses _cluster_term_tokens_cached + _tokenize_cached
    directly to avoid allocating intermediate sets on every call."""
    term_tokens = _cluster_term_tokens_cached(cluster_str)
    if not term_tokens:
        return 0.0
    q_tokens = frozenset(_tokenize_cached(query_text))
    if not q_tokens:
        return 0.0
    for s in term_tokens:
        if s.issubset(q_tokens):
            return 1.0
    cluster_union = frozenset().union(*term_tokens)
    union_overlap = len(cluster_union & q_tokens)
    if union_overlap == 0:
        return 0.0
    best = 0.0
    for s in term_tokens:
        overlap = len(s & q_tokens)
        if overlap == 0:
            continue
        score = overlap / len(s)
        if overlap >= 2:
            score = min(1.0, score * 1.2)
        if score > best:
            best = score
    return max(best, 0.35 if union_overlap >= 1 else 0.0)


def cluster_score(cluster_str: str, query_text: str) -> float:
    """
    Match-strength score in [0.0, 1.0] between a cluster (comma-separated keywords)
    and a query text. Full-term match -> 1.0; partial overlap scaled by token
    proportion with a 1.2x boost when >= 2 tokens match; floor of 0.35 on any
    single-token overlap. Returns 0.0 for empty inputs or no overlap.
    Cached via _cluster_score_cached.
    """
    return _cluster_score_cached(cluster_str or "", query_text or "")


def cluster_filter(cluster_str: str) -> Optional[Callable]:
    """
    Return a row-filter function: True if cluster_score(cluster_str, query_text) > 0.
    Kept as a thin wrapper around cluster_score so legacy callers stay valid.
    """
    if not cluster_str:
        return None
    term_tokens = _cluster_term_tokens(cluster_str)
    if not term_tokens:
        return None
    def _fn(row) -> bool:
        return cluster_score(cluster_str, row.get("query_tested", "")) > 0.0
    return _fn


def weighted_presence_pct(rows: list, target_lower: str, cluster_str: str) -> float:
    """
    Per-cluster target brand presence weighted by per-query match strength.

    Each matching row contributes its match score to the denominator and (score * hit)
    to the numerator. Empty cluster falls back to unweighted presence_pct.
    Returns a value in [0.0, 100.0].
    """
    if not cluster_str:
        return presence_pct(rows, target_lower)
    total_weight = 0.0
    weighted_hits = 0.0
    for r in rows:
        score = cluster_score(cluster_str, r.get("query_tested", ""))
        if score <= 0:
            continue
        total_weight += score
        if target_in_row(r, target_lower):
            weighted_hits += score
    if total_weight == 0.0:
        return 0.0
    return (weighted_hits / total_weight) * 100.0


# -- Coverage check --

def check_query_coverage(planner_rows: list[dict[str, Any]], queries: list[dict[str, Any]]) -> None:
    """
    Warn if many live planner rows have clusters that don't match any tested query.
    Informational only; does not block the run.
    """
    live_rows = [r for r in planner_rows if r.get("status") == "live" and (r.get("target_cluster") or "").strip()]
    if not live_rows or not queries:
        return

    # Normalize query strings from either {"query": ...} or {"query_tested": ...}.
    query_objs = []
    for q in queries:
        text = q.get("query") or q.get("query_tested") or ""
        if text:
            query_objs.append({"query_tested": text})

    if not query_objs:
        return

    unmatched = []
    for r in live_rows:
        cf = cluster_filter(r["target_cluster"])
        if cf is None:
            continue
        if not any(cf(q) for q in query_objs):
            unmatched.append(r)

    total = len(live_rows)
    n_unmatched = len(unmatched)
    if total == 0 or (n_unmatched / total) <= 0.25:
        return

    logger.warning(
        "Query coverage low: %d of %d live planner rows have target clusters "
        "that don't match any tested query.", n_unmatched, total,
    )
    logger.warning("  Total live rows: %d", total)
    logger.warning("  Rows with no matching query: %d", n_unmatched)
    logger.warning("  Examples (title -> cluster):")
    for r in unmatched[:5]:
        title = r.get("title_url", "") or "(no title)"
        if len(title) > 60:
            title = title[:57] + "..."
        logger.warning("    - %s -> %s", title, r.get("target_cluster", ""))
    logger.warning(
        "  Suggestion: These rows will attribute via brand-wide lift only; "
        "cluster lift will be 0. Either expand AEO-01 query generation to cover "
        "these clusters, or accept brand-wide attribution for them."
    )


# -- Attribution --

def compute_attribution(
    planner_rows: list[dict[str, Any]],
    runs: Any,
    target_brand: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Returns:
      attributions: list of dicts (per content row)
      breakouts:    list of dicts (overall-presence jumps > threshold)
    """
    target_lower = target_brand.lower()
    # Support both legacy list-of-tuples and the new RunHistory abstraction.
    run_lookup: Any
    if isinstance(runs, RunHistory):
        run_dates = runs.dates()
        run_lookup = runs  # date-indexed; loads on demand for lazy mode
    else:
        run_dates = [d for d, _ in runs]
        run_lookup = {d: rows for d, rows in runs}

    overall_series = [(d, presence_pct(run_lookup[d], target_lower)) for d in run_dates]

    # Detect breakouts: any consecutive jump > BREAKOUT_THRESHOLD_PP
    breakouts = []
    for i in range(1, len(overall_series)):
        d_prev, p_prev = overall_series[i - 1]
        d_curr, p_curr = overall_series[i]
        if p_curr - p_prev >= BREAKOUT_THRESHOLD_PP:
            breakouts.append({"date": d_curr, "delta_pp": round(p_curr - p_prev, 1), "presence": round(p_curr, 1)})

    attributions = []
    # Group by publish_date for tie-breaker
    by_pub = defaultdict(list)
    for r in planner_rows:
        if r["status"] == "live":
            by_pub[r["publish_date"]].append(r)

    for pub_date, group in sorted(by_pub.items()):
        attr_target_date = pub_date + timedelta(days=group[0]["lag_days"])

        baseline_run_date = closest_run_date(pub_date, run_dates)
        attr_run_date     = closest_run_date(attr_target_date, run_dates)

        if baseline_run_date is None or attr_run_date is None or baseline_run_date == attr_run_date:
            for r in group:
                attributions.append({
                    **_attr_record_base(r, pub_date, attr_target_date),
                    "status":           "insufficient_history",
                    "cluster_lift_pp":  None,
                    "weighted_lift_pp": None,
                    "overall_lift_pp":  None,
                    "citation_count":   0,
                    "claimed_queries":  [],
                    "primary":          False,
                })
            continue

        baseline_rows = run_lookup[baseline_run_date]
        attr_rows     = run_lookup[attr_run_date]
        overall_base  = presence_pct(baseline_rows, target_lower)
        overall_attr  = presence_pct(attr_rows, target_lower)
        overall_lift  = overall_attr - overall_base

        # Per-piece per-query match scores (weight) for both baseline + attr windows.
        # Used for: (a) weighted cluster lift; (b) double-counting protection by
        # claiming each query for the piece with the highest match score.
        unique_query_texts = set()
        for r in baseline_rows + attr_rows:
            q = r.get("query_tested", "")
            if q:
                unique_query_texts.add(q)

        piece_match_scores = []   # parallel to group; each entry: {query_text: score}
        for r in group:
            cluster = r["target_cluster"]
            scores = {}
            for q in unique_query_texts:
                s = cluster_score(cluster, q) if cluster else 0.0
                if s > 0:
                    scores[q] = s
            piece_match_scores.append(scores)

        # Claim assignment: each query goes to the piece with the highest score.
        # Ties broken by piece order (stable).
        claims = {}   # query_text -> piece_index
        for q in unique_query_texts:
            best_idx, best_score = None, 0.0
            for idx, scores in enumerate(piece_match_scores):
                s = scores.get(q, 0.0)
                if s > best_score:
                    best_idx, best_score = idx, s
            if best_idx is not None:
                claims[q] = best_idx
        claimed_by_piece = defaultdict(set)
        for q, idx in claims.items():
            claimed_by_piece[idx].add(q)

        scored = []
        for idx, r in enumerate(group):
            cluster = r["target_cluster"]
            claimed = claimed_by_piece.get(idx, set())
            if not cluster:
                # Brand-wide attribution; no cluster scope.
                cluster_lift = overall_lift
                weighted_lift = overall_lift
            elif claimed:
                # Restrict baseline/attr presence to the piece's CLAIMED queries only —
                # avoids two pieces both claiming the same lift.
                def _claim_filter(row, _claimed=claimed):
                    return row.get("query_tested", "") in _claimed
                cluster_base = presence_pct(baseline_rows, target_lower, _claim_filter)
                cluster_attr = presence_pct(attr_rows, target_lower, _claim_filter)
                cluster_lift = cluster_attr - cluster_base
                # Weighted version uses per-query match scores instead of binary filter
                wb = weighted_presence_pct(baseline_rows, target_lower, cluster)
                wa = weighted_presence_pct(attr_rows,     target_lower, cluster)
                weighted_lift = wa - wb
            else:
                # Piece's cluster matched something but lost every query tie-break.
                cluster_lift = 0.0
                weighted_lift = 0.0

            citation_count = is_url_cited(r["title_url"], attr_rows)
            base_status = _classify(cluster_lift, overall_lift)
            status = "cited" if citation_count > 0 else base_status
            scored.append((idx, r, cluster_lift, weighted_lift, status, citation_count))

        # Primary tie-breaker: cited > strong > moderate, then weighted_lift, then citation_count
        STATUS_RANK = {"cited": 4, "strong": 3, "moderate": 2, "weak": 1, "none": 0}
        scored.sort(key=lambda x: (STATUS_RANK.get(x[4], 0), x[3], x[5]), reverse=True)
        primary_assigned = False
        # Re-iterate in the SORTED order, but emit attribution records in the original
        # group order to keep output stable across re-runs (use idx).
        primary_idx = None
        for idx, r, cluster_lift, weighted_lift, status, citation_count in scored:
            if not primary_assigned and status in ("cited", "strong", "moderate"):
                primary_idx = idx
                primary_assigned = True
                break
        # Now emit in input order
        for idx, r in enumerate(group):
            entry = next(s for s in scored if s[0] == idx)
            _, _, cluster_lift, weighted_lift, status, citation_count = entry
            attributions.append({
                **_attr_record_base(r, pub_date, attr_target_date),
                "status":             status,
                "cluster_lift_pp":    round(cluster_lift, 2),
                "weighted_lift_pp":   round(weighted_lift, 2),
                "overall_lift_pp":    round(overall_lift, 2),
                "citation_count":     citation_count,
                "claimed_queries":    sorted(list(claimed_by_piece.get(idx, set()))),
                "baseline_run_date":  baseline_run_date.isoformat(),
                "attr_run_date":      attr_run_date.isoformat(),
                "primary":            (idx == primary_idx),
            })

    return attributions, breakouts


def _attr_record_base(r, pub_date, attr_target_date):
    return {
        "publish_date":    pub_date.isoformat(),
        "attr_date":       attr_target_date.isoformat(),
        "content_type":    r["content_type"],
        "title_url":       r["title_url"],
        "target_cluster":  r["target_cluster"],
        "lag_days":        r["lag_days"],
    }


def _classify(cluster_lift, overall_lift):
    if cluster_lift <= 0:
        return "none"
    if cluster_lift > overall_lift + STRONG_LIFT_PP:
        return "strong"
    if cluster_lift > overall_lift:
        return "moderate"
    return "weak"


# ── Strategy events for the dashboard ─────────────────────────────────────────

def build_strategy_events(
    attributions: list[dict[str, Any]],
    breakouts: list[dict[str, Any]],
    runs: Any,
) -> list[dict[str, Any]]:
    """
    Emit one event for impl. and (when primary) one for attr. for each attribution,
    plus one breakout event per detected jump. Each event carries a `type` (its
    content type or 'breakout') and a `row` indicating which lane the dashboard
    renderer should place it in.
    """
    if isinstance(runs, RunHistory):
        run_dates_sorted = sorted(runs.dates())
    else:
        run_dates_sorted = sorted({d for d, _ in runs})
    if not run_dates_sorted:
        return []

    def _snap(target_iso):
        target = parse_iso(target_iso)
        return closest_run_date(target, run_dates_sorted)

    events = []
    pair_counter = 0
    for a in attributions:
        if a["status"] == "insufficient_history":
            continue
        ctype = a["content_type"]
        color = CONTENT_TYPE_COLORS.get(ctype, DEFAULT_COLOR)
        lane  = CONTENT_TYPE_LANES.get(ctype, len(CONTENT_TYPE_LANES))

        impl_snap = _snap(a["publish_date"])
        pair_id = None
        if a["primary"]:
            pair_counter += 1
            pair_id = f"p{pair_counter}"

        events.append({
            "date":     fmt_chart_label(impl_snap),
            "iso_date": impl_snap.isoformat(),
            "label":    "impl.",
            "color":    color,
            "row":      lane,
            "type":     ctype,
            "kind":     "impl",
            "pair_id":  pair_id,
        })

        if a["primary"]:
            attr_snap = _snap(a["attr_date"])
            events.append({
                "date":     fmt_chart_label(attr_snap),
                "iso_date": attr_snap.isoformat(),
                "label":    "attr.",
                "color":    color,
                "row":      lane,
                "type":     ctype,
                "kind":     "attr",
                "pair_id":  pair_id,
            })

    for b in breakouts:
        events.append({
            "date":     fmt_chart_label(b["date"]),
            "iso_date": b["date"].isoformat(),
            "label":    f"⚡{b['delta_pp']:+.1f}pp",
            "color":    BREAKOUT_COLOR,
            "row":      BREAKOUT_LANE,
            "type":     "Breakout",
            "kind":     "breakout",
        })

    # Deduplicate (same date + same type + same kind) — keep first occurrence
    seen_keys = set()
    deduped = []
    for e in events:
        key = (e["date"], e["type"], e["kind"])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(e)
    return deduped


# ── Summary markdown ──────────────────────────────────────────────────────────

def write_summary(
    attributions: list[dict[str, Any]],
    breakouts: list[dict[str, Any]],
    summary_path: Union[str, Path],
) -> None:
    by_status = defaultdict(list)
    for a in attributions:
        by_status[a["status"]].append(a)
    lines = ["# Content Attribution Summary", ""]
    counts = ", ".join(f"{k}={len(v)}" for k, v in sorted(by_status.items()))
    lines += [f"**Counts:** {counts}", ""]
    if breakouts:
        lines += ["## Breakouts", ""]
        for b in breakouts:
            lines += [f"- {b['date'].isoformat()} — **+{b['delta_pp']}pp** to {b['presence']}%"]
        lines += [""]
    for status in ("cited", "strong", "moderate", "weak", "none", "insufficient_history"):
        rows = by_status.get(status, [])
        if not rows:
            continue
        lines += [f"## {status.upper()} ({len(rows)})", ""]
        lines += ["| Publish | Attr | Type | Title | Cluster Δ | Brand Δ |",
                  "|---|---|---|---|---|---|"]
        for r in rows:
            cl = "—" if r["cluster_lift_pp"] is None else f"{r['cluster_lift_pp']:+.1f}pp"
            ov = "—" if r["overall_lift_pp"] is None else f"{r['overall_lift_pp']:+.1f}pp"
            title = (r["title_url"][:40] + "…") if len(r["title_url"]) > 41 else r["title_url"]
            lines += [f"| {r['publish_date']} | {r['attr_date']} | {r['content_type']} | {title} | {cl} | {ov} |"]
        lines += [""]
    Path(summary_path).write_text("\n".join(lines), encoding="utf-8")


# ── Main ──────────────────────────────────────────────────────────────────────

class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts":     datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level":  record.levelname,
            "logger": record.name,
            "msg":    record.getMessage(),
        }
        step = getattr(record, "step", None)
        if step:
            payload["step"] = step
        return json.dumps(payload, ensure_ascii=False)


def _configure_logging(verbose: bool, log_format: str = "text") -> None:
    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger()
    # Reset handlers if re-invoked in same process
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(stream=sys.stderr)
    if log_format == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(level)


def main() -> int:
    global BREAKOUT_THRESHOLD_PP, STRONG_LIFT_PP

    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--content-planner", help="Local CSV with content planner")
    src.add_argument("--sheet-url", help="Public Google Sheet URL or ID (Anyone-with-link viewable, no auth)")
    src.add_argument("--sheet-id",  help="Google Sheet ID (requires --service-account-json)")
    ap.add_argument("--sheet-tab", default="Table1")
    ap.add_argument("--service-account-json", help="Path to service account JSON (for --sheet-id mode)")
    ap.add_argument("--runs-dir",      required=True)
    ap.add_argument("--brand-profile", required=True)
    ap.add_argument("--output-dir",    required=True)
    ap.add_argument("--breakout-threshold-pp", type=float, default=BREAKOUT_THRESHOLD_PP,
                    help=f"Period-over-period jump (in pp) that flags a breakout. Default {BREAKOUT_THRESHOLD_PP}.")
    ap.add_argument("--strong-lift-pp", type=float, default=STRONG_LIFT_PP,
                    help=f"Cluster lift over brand-wide lift (in pp) that earns 'strong' status. Default {STRONG_LIFT_PP}.")
    ap.add_argument("--lazy-runs", action="store_true",
                    help="Load each run's scored_rows.jsonl on demand with an LRU cache, "
                         "instead of reading every run into memory upfront. Recommended for "
                         "100+ runs.")
    ap.add_argument("--lazy-cache-size", type=int, default=8,
                    help="When --lazy-runs is set, how many runs to keep in RAM. Default 8.")
    ap.add_argument("--verbose", "-v", action="store_true", help="Enable debug-level logging.")
    ap.add_argument("--log-format", choices=["text", "json"], default="text",
                    help="Log output format. 'text' (default) or 'json' for structured single-line JSON.")
    args = ap.parse_args()

    _configure_logging(args.verbose, args.log_format)
    BREAKOUT_THRESHOLD_PP = float(args.breakout_threshold_pp)
    STRONG_LIFT_PP        = float(args.strong_lift_pp)

    try:
        brand_profile = json.loads(Path(args.brand_profile).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.error("Cannot read brand profile %s: %s", args.brand_profile, e)
        return 2
    target_brand = (
        brand_profile.get("brand_name")
        or brand_profile.get("brand")
        or brand_profile.get("name")
        or brand_profile.get("target_brand")
    )
    if not target_brand:
        logger.error("brand_profile must contain a 'brand_name' or 'brand' field")
        return 2

    try:
        if args.content_planner:
            planner = load_planner_csv(args.content_planner)
        elif args.sheet_url:
            planner = load_planner_public_url(args.sheet_url, args.sheet_tab)
        else:
            if not args.service_account_json:
                logger.error("--service-account-json required with --sheet-id")
                return 2
            planner = load_planner_sheet(args.sheet_id, args.sheet_tab, args.service_account_json)
    except (ValueError, RuntimeError) as e:
        logger.error("Failed to load content planner: %s", e)
        return 2

    if args.lazy_runs:
        runs = load_runs_lazy(args.runs_dir, cache_size=args.lazy_cache_size)
    else:
        runs = load_runs(args.runs_dir)
    logger.info("Loaded %d planner rows, %d run dates.", len(planner), len(runs))

    if len(runs) < 2:
        logger.warning("Need at least 2 runs to compute attribution. Emitting empty events.")

    if runs:
        latest_rows = runs[-1][1]
        unique_queries = []
        seen_q = set()
        for r in latest_rows:
            q = r.get("query_tested") or r.get("query") or ""
            if q and q not in seen_q:
                seen_q.add(q)
                unique_queries.append({"query": q})
        check_query_coverage(planner, unique_queries)

    attributions, breakouts = compute_attribution(planner, runs, target_brand)
    events = build_strategy_events(attributions, breakouts, runs)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    attributions_payload = {
        "_schema_version": ATTRIBUTIONS_SCHEMA_VERSION,
        "_generated_at":   datetime.utcnow().isoformat() + "Z",
        "target_brand":    target_brand,
        "attributions":    attributions,
        "breakouts":       [
            {"date": b["date"].isoformat(), "delta_pp": b["delta_pp"], "presence": b["presence"]}
            for b in breakouts
        ],
    }
    events_payload = {
        "_schema_version": STRATEGY_EVENTS_SCHEMA_VERSION,
        "_generated_at":   datetime.utcnow().isoformat() + "Z",
        "events":          events,
    }
    (out / "attributions.json").write_text(json.dumps(attributions_payload, indent=2), encoding="utf-8")
    (out / "strategy_events.json").write_text(json.dumps(events_payload, indent=2), encoding="utf-8")
    write_summary(attributions, breakouts, out / "summary.md")
    logger.info("Wrote %s (%d rows)", out / "attributions.json", len(attributions))
    logger.info("Wrote %s (%d events)", out / "strategy_events.json", len(events))
    logger.info("Wrote %s", out / "summary.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
