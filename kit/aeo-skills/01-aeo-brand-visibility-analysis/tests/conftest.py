"""Pytest fixtures for AEO-01 dashboard renderer tests.

Modules are loaded by file path via importlib because the parent directory
"AEO skills/01-aeo-brand-visibility-analysis" contains a space and cannot
be a normal Python package. Mirrors the AEO-04 conftest pattern.
"""

import importlib.util
from pathlib import Path

import pytest


# tests/conftest.py is at: <REPO>/AEO skills/01-aeo-brand-visibility-analysis/tests/conftest.py
# parents: [0]=tests, [1]=01-aeo-brand-visibility-analysis, [2]=AEO skills, [3]=REPO
REPO = Path(__file__).resolve().parents[3]
SKILL_ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def render_dashboard_path():
    return SKILL_ROOT / "scripts" / "render_dashboard.py"


@pytest.fixture(scope="session")
def rd():
    """Lazy import of render_dashboard module (only used if a test needs internals)."""
    path = SKILL_ROOT / "scripts" / "render_dashboard.py"
    return _load("render_dashboard", path)
