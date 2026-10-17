"""Pytest fixtures for AEO-04 content attribution tests.

Modules are loaded by file path via importlib because the parent directory
"AEO skills/04-aeo-content-attribution" contains a space and cannot be a
normal Python package.
"""

import importlib.util
from datetime import date
from pathlib import Path

import pytest


# tests/conftest.py is at: <REPO>/AEO skills/04-aeo-content-attribution/tests/conftest.py
# parents: [0]=tests, [1]=04-aeo-content-attribution, [2]=AEO skills, [3]=REPO
REPO = Path(__file__).resolve().parents[3]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def ac():
    path = REPO / "AEO skills" / "04-aeo-content-attribution" / "scripts" / "attribute_content.py"
    return _load("attribute_content", path)


@pytest.fixture(scope="session")
def ec():
    path = REPO / "AEO skills" / "01-aeo-brand-visibility-analysis" / "scripts" / "extract_citations.py"
    return _load("extract_citations", path)


@pytest.fixture
def sample_run_rows():
    """4 scored_rows dicts with mixed brand mentions and cited_urls."""
    return [
        {
            "query_tested": "best squats leggings for women",
            "brands_mentioned_list": ["Gymshark", "Lululemon"],
            "cited_urls": ["gymshark.com/blog/squat-proof"],
        },
        {
            "query_tested": "top protein powder",
            "brands_mentioned_list": ["Optimum Nutrition"],
            "cited_urls": [],
        },
        {
            "query_tested": "squat proof leggings review",
            "brands_mentioned_list": ["Gymshark Ltd", "Nike"],
            "cited_urls": ["https://www.gymshark.com/blog/squat-proof"],
        },
        {
            "query_tested": "running shoes guide",
            "brands_mentioned_list": ["Nike", "Adidas"],
            "cited_urls": ["nike.com/running"],
        },
    ]


@pytest.fixture
def sample_planner_rows():
    """3 planner rows: one expected primary cluster match, one cluster non-match, one with publish_date that has no neighbor run."""
    return [
        {
            "publish_date": date(2026, 1, 10),
            "content_type": "Blog",
            "title_url": "https://gymshark.com/blog/squat-proof",
            "target_cluster": "squat proof leggings",
            "lag_days": 7,
            "status": "live",
        },
        {
            "publish_date": date(2026, 1, 10),
            "content_type": "FAQ",
            "title_url": "https://gymshark.com/faq/protein",
            "target_cluster": "protein powder",
            "lag_days": 7,
            "status": "live",
        },
        {
            "publish_date": date(2026, 3, 1),  # outside the runs window → insufficient_history
            "content_type": "Press",
            "title_url": "https://gymshark.com/press/release",
            "target_cluster": "running shoes",
            "lag_days": 7,
            "status": "live",
        },
    ]


@pytest.fixture
def sample_runs(sample_run_rows):
    """3 runs spanning 3 dates. Brand presence climbs across runs."""
    # Run 1 (baseline): brand mentioned in 1/4 rows = 25%
    run1 = [
        {"query_tested": r["query_tested"],
         "brands_mentioned_list": (["Gymshark"] if i == 0 else [b for b in r["brands_mentioned_list"] if "Gymshark" not in b]),
         "cited_urls": []}
        for i, r in enumerate(sample_run_rows)
    ]
    # Run 2 (attr window for jan 10 + 7 = jan 17): brand in 3/4 rows + citation present
    run2 = sample_run_rows
    # Run 3 (later): keep high presence
    run3 = sample_run_rows
    return [
        (date(2026, 1, 5), run1),
        (date(2026, 1, 17), run2),
        (date(2026, 1, 31), run3),
    ]
