"""Scale + lazy-loading tests for AEO-04 attribution.

Generates synthetic large-scale datasets in tmp_path to confirm:
  - compute_attribution handles 1000-piece planners under 5s
  - load_runs_lazy bounds memory via LRU cache
  - eager and lazy modes produce identical attributions
  - the cluster-score LRU cache dominates at scale
"""

import json
import random
import time
from datetime import date, timedelta
from pathlib import Path


def _make_fake_rows(n_rows=200, target_hit_rate=0.4, seed=7):
    rows = []
    rng = random.Random(seed)
    for i in range(n_rows):
        rows.append({
            "row_id": f"r{i}",
            "query_id": f"Q{i % 30:02d}",
            "query_tested": f"sample query {i % 30} about leggings and sizing",
            "engine": "llm_openai",
            "brands_mentioned_list": ["Brand"] if rng.random() < target_hit_rate else [],
            "cited_urls": [],
        })
    return rows


def _write_runs_to_dir(runs_dir: Path, n_runs: int, n_rows: int, start: date) -> list:
    """Materialize n_runs scored_rows.jsonl files. Returns list of dates."""
    dates_out = []
    for i in range(n_runs):
        d = start + timedelta(days=i * 7)
        sub = runs_dir / d.isoformat()
        sub.mkdir(parents=True, exist_ok=True)
        rows = _make_fake_rows(n_rows=n_rows, target_hit_rate=0.3 + 0.005 * i, seed=i)
        with (sub / "scored_rows.jsonl").open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        dates_out.append(d)
    return dates_out


def _build_planner(n_pieces: int, publish_dates: list, cluster_text="leggings sizing") -> list:
    """1000 pieces spread evenly across the supplied publish_dates."""
    planner = []
    for i in range(n_pieces):
        pub = publish_dates[i % len(publish_dates)]
        planner.append({
            "publish_date": pub,
            "content_type": "Blog",
            "title_url":    f"https://example.com/post-{i}",
            "target_cluster": cluster_text,
            "lag_days":     7,
            "status":       "live",
        })
    return planner


class TestLoadTest:

    def test_1000_pieces_under_5s(self, ac):
        """50 runs x 200 rows; 1000-piece planner. Must finish under 5 seconds."""
        # Build runs eagerly (in-memory only; no disk needed).
        runs_list = []
        start = date(2025, 1, 1)
        for i in range(50):
            d = start + timedelta(days=i * 7)
            runs_list.append((d, _make_fake_rows(n_rows=200, target_hit_rate=0.3 + 0.005 * i, seed=i)))
        history = ac.RunHistory.eager(runs_list)

        # 1000 pieces across 50 unique publish dates, 20 per date.
        unique_pubs = [d + timedelta(days=2) for d in [r[0] for r in runs_list]]
        planner = _build_planner(1000, unique_pubs)

        # Clear caches so the test reflects cold-start scoring.
        ac._cluster_score_cached.cache_clear()
        ac._tokenize_cached.cache_clear()
        ac._cluster_term_tokens_cached.cache_clear()

        t0 = time.perf_counter()
        attributions, _ = ac.compute_attribution(planner, history, "Brand")
        elapsed = time.perf_counter() - t0

        # Stash for the cache-hit-rate test to read.
        TestLoadTest._last_elapsed = elapsed
        TestLoadTest._last_cache_info = ac._cluster_score_cached.cache_info()

        assert len(attributions) == 1000, f"Expected 1000 records, got {len(attributions)}"
        assert elapsed < 5.0, f"compute_attribution took {elapsed:.2f}s, expected < 5s"

    def test_100_runs_lazy_loading_memory_bounded(self, tmp_path, ac):
        """Lazy loader should keep the LRU cache at <= cache_size after full iteration."""
        runs_dir = tmp_path / "runs"
        _write_runs_to_dir(runs_dir, n_runs=100, n_rows=50, start=date(2024, 1, 1))

        history = ac.load_runs_lazy(str(runs_dir), cache_size=4)
        assert len(history) == 100

        # Force-touch every date to exercise the LRU.
        for d, rows in history:
            assert isinstance(rows, list)

        assert hasattr(history, "_cache")
        assert len(history._cache) <= 4, (
            f"Lazy cache held {len(history._cache)} entries, expected <= 4"
        )

    def test_eager_vs_lazy_same_output(self, tmp_path, ac):
        """10 runs on disk; both loaders should yield identical attribution output."""
        runs_dir = tmp_path / "runs"
        dates_written = _write_runs_to_dir(runs_dir, n_runs=10, n_rows=100, start=date(2025, 6, 1))

        eager = ac.load_runs(str(runs_dir))
        lazy  = ac.load_runs_lazy(str(runs_dir), cache_size=3)

        # Planner aligned to the run dates so we get real (non insufficient_history) records.
        pubs = [d + timedelta(days=1) for d in dates_written[:-1]]
        planner = _build_planner(40, pubs, cluster_text="leggings sizing")

        a_eager, b_eager = ac.compute_attribution(planner, eager, "Brand")
        a_lazy,  b_lazy  = ac.compute_attribution(planner, lazy, "Brand")

        assert len(a_eager) == len(a_lazy)
        for ae, al in zip(a_eager, a_lazy):
            assert ae["status"]           == al["status"]
            assert ae["cluster_lift_pp"]  == al["cluster_lift_pp"]
            assert ae["primary"]          == al["primary"]
            assert ae["claimed_queries"]  == al["claimed_queries"]

    def test_cluster_score_cache_hit_rate_at_scale(self, ac):
        """After the 1000-piece run, the score cache should be > 95% hits."""
        # Re-run if the prior test didn't (pytest ordering safety).
        info = getattr(TestLoadTest, "_last_cache_info", None)
        if info is None:
            self.test_1000_pieces_under_5s(ac)
            info = TestLoadTest._last_cache_info
        total = info.hits + info.misses
        assert total > 0
        ratio = info.hits / total
        assert ratio > 0.95, (
            f"Cluster-score cache hit rate {ratio:.3f} below 0.95 "
            f"(hits={info.hits}, misses={info.misses})"
        )
