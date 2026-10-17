"""Snapshot tests for render_dashboard.py.

These tests verify the renderer produces structurally-correct HTML for a tiny
fixed input. Intent is regression protection, not pixel-perfect output.

The script is invoked via subprocess; it is never imported (it is a script
with side effects on import).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


TARGET_BRAND = "Acme"
COMPETITORS_DIRECT = ["Beta Co", "Gamma Labs"]
COMPETITORS_INDIRECT = ["Delta Inc"]


def _fmt_chart_label(d: date) -> str:
    if sys.platform != "win32":
        return d.strftime("%b %-d'%y")
    return d.strftime("%b %d'%y").lstrip("0").replace(" 0", " ")


def _write_brand_profile(path: Path) -> None:
    payload = {
        "brand_name": TARGET_BRAND,
        "brand_aliases": ["acme corp"],
        "competitors": {
            "direct": [
                f"{COMPETITORS_DIRECT[0]} (beta.co) -- a direct competitor",
                f"{COMPETITORS_DIRECT[1]} (gamma.io) -- another direct competitor",
            ],
            "indirect": [
                f"{COMPETITORS_INDIRECT[0]} (delta.example) -- indirect rival",
            ],
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_queries(path: Path) -> None:
    payload = {
        "queries": [
            {
                "id": "Q01",
                "category": "A",
                "category_name": "Core",
                "intent": "problem-centric",
                "stage": "awareness",
                "specificity": "mid",
                "length_bucket": "short",
                "contains_brand": False,
                "contains_competitor": False,
                "has_geo_context": False,
                "query": "best widgets for daily use",
            },
            {
                "id": "Q02",
                "category": "B",
                "category_name": "Brand",
                "intent": "branded",
                "stage": "consideration",
                "specificity": "high",
                "length_bucket": "short",
                "contains_brand": True,
                "contains_competitor": False,
                "has_geo_context": False,
                "query": "acme widget reviews",
            },
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _scored_row(query_id: str, query_tested: str, engine: str, brands: list[str]) -> dict:
    return {
        "row_id": f"{query_id}-{engine}",
        "query_id": query_id,
        "query_tested": query_tested,
        "engine": engine,
        "response_summary": "synthetic",
        "brand_mentioned": brands[0] if brands else "",
        "brands_mentioned_list": brands,
        "citation_frequency_score": 1,
        "share_of_voice_percentage": 25.0,
        "positional_authority_score": 3,
        "sentiment_direction_score": 0,
        "response_relevance_score": 4,
        "market_position_type": "challenger",
        "discovery_role": "incumbent",
        "positioning_narrative": "n/a",
        "strength_score": 3,
        "schema_presence_observed": False,
        "cited_urls": [],
    }


def _write_scored_jsonl(path: Path, brands_per_query: dict[str, list[str]]) -> None:
    rows = []
    for q_id, q_text in [("Q01", "best widgets for daily use"), ("Q02", "acme widget reviews")]:
        for engine in ("llm_openai", "llm_gemini"):
            rows.append(
                _scored_row(q_id, q_text, engine, brands_per_query.get(q_id, []))
            )
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


def _build_fixture(tmp_path: Path) -> dict:
    """Create the minimal set of input files in tmp_path and return paths."""
    brand_profile = tmp_path / "brand_profile.json"
    queries = tmp_path / "queries.json"
    _write_brand_profile(brand_profile)
    _write_queries(queries)

    # Two dated run dirs
    runs_dir = tmp_path / "runs"
    d1 = date(2026, 1, 5)
    d2 = date(2026, 1, 19)
    sub1 = runs_dir / d1.isoformat()
    sub2 = runs_dir / d2.isoformat()
    sub1.mkdir(parents=True)
    sub2.mkdir(parents=True)

    # Run 1: only Beta Co mentioned
    _write_scored_jsonl(
        sub1 / "scored_rows.jsonl",
        {"Q01": ["Beta Co"], "Q02": ["Beta Co"]},
    )
    # Run 2: Acme appears in both
    _write_scored_jsonl(
        sub2 / "scored_rows.jsonl",
        {"Q01": ["Acme", "Beta Co"], "Q02": ["Acme"]},
    )

    # Latest scored file
    scored = sub2 / "scored_rows.jsonl"

    out = tmp_path / "dashboard.html"
    strategy_events = tmp_path / "strategy_events.json"

    return {
        "brand_profile": brand_profile,
        "queries": queries,
        "runs_dir": runs_dir,
        "scored": scored,
        "out": out,
        "strategy_events": strategy_events,
        "d1": d1,
        "d2": d2,
    }


def _strategy_events_payload(d1: date, d2: date) -> list[dict]:
    """A 2-row strategy_events payload: one Blog impl+attr pair and one Breakout."""
    return [
        {
            "date": _fmt_chart_label(d1),
            "label": "impl.",
            "color": "#a04545",
            "row": 3,
            "type": "Blog",
            "kind": "impl",
            "pair_id": "p1",
        },
        {
            "date": _fmt_chart_label(d2),
            "label": "attr.",
            "color": "#a04545",
            "row": 3,
            "type": "Blog",
            "kind": "attr",
            "pair_id": "p1",
        },
        {
            "date": _fmt_chart_label(d2),
            "label": "⚡+5.0pp",
            "color": "#2d6a4f",
            "row": 6,
            "type": "Breakout",
            "kind": "breakout",
        },
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(render_path: Path, fx: dict, with_events: bool = False) -> subprocess.CompletedProcess:
    if with_events:
        fx["strategy_events"].write_text(
            json.dumps(_strategy_events_payload(fx["d1"], fx["d2"])),
            encoding="utf-8",
        )
    cmd = [
        sys.executable,
        str(render_path),
        "--scored", str(fx["scored"]),
        "--brand-profile", str(fx["brand_profile"]),
        "--queries", str(fx["queries"]),
        "--runs-dir", str(fx["runs_dir"]),
        "--strategy-events", str(fx["strategy_events"]),
        "--out", str(fx["out"]),
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_dashboard_renders_without_crashing(tmp_path, render_dashboard_path):
    fx = _build_fixture(tmp_path)
    result = _run(render_dashboard_path, fx, with_events=False)
    assert result.returncode == 0, (
        f"render_dashboard.py exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert fx["out"].exists(), "Expected dashboard HTML file to be created"
    assert fx["out"].stat().st_size > 0


def test_dashboard_contains_brand_name(tmp_path, render_dashboard_path):
    fx = _build_fixture(tmp_path)
    result = _run(render_dashboard_path, fx)
    assert result.returncode == 0, result.stderr
    html = fx["out"].read_text(encoding="utf-8")
    assert TARGET_BRAND in html, f"Target brand {TARGET_BRAND!r} not found in HTML"


def test_dashboard_has_all_competitor_lines(tmp_path, render_dashboard_path):
    fx = _build_fixture(tmp_path)
    result = _run(render_dashboard_path, fx)
    assert result.returncode == 0, result.stderr
    html = fx["out"].read_text(encoding="utf-8")
    for comp in COMPETITORS_DIRECT + COMPETITORS_INDIRECT:
        assert comp in html, f"Competitor {comp!r} not found in HTML"


def test_lane_labels_render_when_strategy_events_present(tmp_path, render_dashboard_path):
    fx = _build_fixture(tmp_path)
    result = _run(render_dashboard_path, fx, with_events=True)
    assert result.returncode == 0, result.stderr
    html = fx["out"].read_text(encoding="utf-8")
    # The lane label cell carries the content type. With Blog + Breakout events
    # we expect both lane label spans to be present.
    assert "callout-lane-label" in html, "Expected lane label cell class to be present"
    assert ">Blog<" in html, "Expected Blog lane label to render"


def test_pair_bars_render_with_correct_colspan(tmp_path, render_dashboard_path):
    fx = _build_fixture(tmp_path)
    result = _run(render_dashboard_path, fx, with_events=True)
    assert result.returncode == 0, result.stderr
    html = fx["out"].read_text(encoding="utf-8")
    # Two run dates: impl at d1 (idx 0), attr at d2 (idx 1). Span = 1 - 0 + 1 = 2.
    pattern = re.compile(r'<th class="pair-bar" colspan="(\d+)"')
    matches = pattern.findall(html)
    assert matches, "Expected at least one pair-bar <th colspan=...> cell"
    assert "2" in matches, (
        f"Expected a pair-bar with colspan=2 for 2-run span; got colspans {matches}"
    )


def test_breakout_pills_render(tmp_path, render_dashboard_path):
    fx = _build_fixture(tmp_path)
    result = _run(render_dashboard_path, fx, with_events=True)
    assert result.returncode == 0, result.stderr
    html = fx["out"].read_text(encoding="utf-8")
    assert "⚡" in html, "Expected lightning-bolt character in breakout pill"


def test_no_important_in_callout_css(tmp_path, render_dashboard_path):
    fx = _build_fixture(tmp_path)
    result = _run(render_dashboard_path, fx, with_events=True)
    assert result.returncode == 0, result.stderr
    html = fx["out"].read_text(encoding="utf-8")
    # Look for `!important` inside .callout-row or .pair-bar rule bodies.
    bad_patterns = [
        re.compile(r"\.callout-row[^{}]*\{[^}]*!important", re.DOTALL),
        re.compile(r"\.pair-bar[^{}]*\{[^}]*!important", re.DOTALL),
    ]
    for pat in bad_patterns:
        m = pat.search(html)
        assert m is None, (
            f"Found !important in callout/pair-bar CSS rule: {m.group(0)[:120]!r}"
        )


def test_chart_javascript_has_lane_label_rendering(tmp_path, render_dashboard_path):
    fx = _build_fixture(tmp_path)
    result = _run(render_dashboard_path, fx, with_events=True)
    assert result.returncode == 0, result.stderr
    html = fx["out"].read_text(encoding="utf-8")
    # The JS should declare a laneLabel map and create pair-bar rectangles.
    assert "laneLabel" in html, "Expected laneLabel block in chart JS"
    assert "pair-bar" in html, "Expected pair-bar rect creation in chart JS"


# ---------------------------------------------------------------------------
# Log format tests
# ---------------------------------------------------------------------------


def _run_with_log_format(render_path: Path, fx: dict, log_format: str | None) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(render_path),
        "--scored", str(fx["scored"]),
        "--brand-profile", str(fx["brand_profile"]),
        "--queries", str(fx["queries"]),
        "--runs-dir", str(fx["runs_dir"]),
        "--strategy-events", str(fx["strategy_events"]),
        "--out", str(fx["out"]),
    ]
    if log_format is not None:
        cmd += ["--log-format", log_format]
    return subprocess.run(cmd, capture_output=True, text=True)


class TestRendererLogFormat:
    def test_renderer_text_mode_default(self, tmp_path, render_dashboard_path):
        fx = _build_fixture(tmp_path)
        result = _run_with_log_format(render_dashboard_path, fx, log_format=None)
        assert result.returncode == 0, result.stderr
        # In text mode, stderr lines must NOT be parseable as JSON objects.
        lines = [ln for ln in result.stderr.splitlines() if ln.strip()]
        assert lines, "Expected at least one log line on stderr"
        for ln in lines:
            try:
                obj = json.loads(ln)
                # If it parsed, must not look like our structured payload.
                assert not (isinstance(obj, dict) and {"ts", "level", "logger", "msg"} <= set(obj.keys())), (
                    f"Unexpected JSON log line in text mode: {ln!r}"
                )
            except json.JSONDecodeError:
                pass

    def test_renderer_json_log_format(self, tmp_path, render_dashboard_path):
        fx = _build_fixture(tmp_path)
        result = _run_with_log_format(render_dashboard_path, fx, log_format="json")
        assert result.returncode == 0, result.stderr
        lines = [ln for ln in result.stderr.splitlines() if ln.strip()]
        assert lines, "Expected at least one JSON log line on stderr"
        for ln in lines:
            obj = json.loads(ln)
            assert isinstance(obj, dict)
            for key in ("ts", "level", "logger", "msg"):
                assert key in obj, f"Missing {key!r} in log line: {ln!r}"

    def test_renderer_log_includes_dashboard_path(self, tmp_path, render_dashboard_path):
        fx = _build_fixture(tmp_path)
        result = _run_with_log_format(render_dashboard_path, fx, log_format="json")
        assert result.returncode == 0, result.stderr
        out_name = Path(fx["out"]).name
        matched = False
        for ln in result.stderr.splitlines():
            if not ln.strip():
                continue
            obj = json.loads(ln)
            if "Dashboard written to" in obj.get("msg", "") and out_name in obj.get("msg", ""):
                matched = True
                break
        assert matched, "Expected a log line announcing the dashboard output path"
