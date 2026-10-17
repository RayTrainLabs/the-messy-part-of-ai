"""Tests for attribute_content.py."""

from datetime import date

import pytest


# ── normalize_url ─────────────────────────────────────────────────────────────

class TestNormalizeUrl:
    def test_strips_protocol(self, ac):
        assert ac.normalize_url("https://example.com/x") == "example.com/x"
        assert ac.normalize_url("http://example.com/x") == "example.com/x"

    def test_strips_www(self, ac):
        assert ac.normalize_url("https://www.example.com/x") == "example.com/x"

    def test_strips_trailing_slash(self, ac):
        assert ac.normalize_url("https://example.com/x/") == "example.com/x"

    def test_drops_query_and_fragment(self, ac):
        assert ac.normalize_url("https://example.com/x?a=1&b=2#frag") == "example.com/x"

    def test_lowercases(self, ac):
        assert ac.normalize_url("HTTPS://Example.COM/Foo") == "example.com/foo"

    def test_empty_returns_empty(self, ac):
        assert ac.normalize_url("") == ""
        assert ac.normalize_url(None) == ""

    def test_strips_trailing_punct(self, ac):
        assert ac.normalize_url("https://example.com/x.") == "example.com/x"
        assert ac.normalize_url("https://example.com/x),") == "example.com/x"


# ── url_matches ───────────────────────────────────────────────────────────────

class TestUrlMatches:
    def test_exact_normalized_match(self, ac):
        assert ac.url_matches("example.com/x", "example.com/x") is True

    def test_protocol_difference(self, ac):
        assert ac.url_matches("http://example.com/x", "https://example.com/x") is True

    def test_www_difference(self, ac):
        assert ac.url_matches("https://www.example.com/x", "http://example.com/x") is True

    def test_regional_subdomain_difference(self, ac):
        assert ac.url_matches("https://gymshark.com/x", "https://uk.gymshark.com/x") is True
        assert ac.url_matches("https://gymshark.com/x", "https://row.gymshark.com/x") is True
        assert ac.url_matches("https://gymshark.com/x", "https://us.gymshark.com/x") is True

    def test_different_domains(self, ac):
        assert ac.url_matches("https://a.com/x", "https://b.com/x") is False

    def test_query_vs_no_query(self, ac):
        assert ac.url_matches("https://a.com/x?z=1", "https://a.com/x") is True

    def test_empty_inputs(self, ac):
        assert ac.url_matches("", "https://a.com/x") is False
        assert ac.url_matches("https://a.com/x", "") is False
        assert ac.url_matches("", "") is False


# ── is_url_cited ──────────────────────────────────────────────────────────────

class TestIsUrlCited:
    def test_counts_matching_rows(self, ac):
        rows = [
            {"cited_urls": ["https://gymshark.com/x"]},
            {"cited_urls": ["https://nike.com/y"]},
            {"cited_urls": ["https://uk.gymshark.com/x"]},
        ]
        assert ac.is_url_cited("https://gymshark.com/x", rows) == 2

    def test_empty_content_url(self, ac):
        rows = [{"cited_urls": ["https://gymshark.com/x"]}]
        assert ac.is_url_cited("", rows) == 0

    def test_no_cited_urls(self, ac):
        rows = [{"cited_urls": []}, {}]
        assert ac.is_url_cited("https://gymshark.com/x", rows) == 0

    def test_does_not_double_count_single_row(self, ac):
        rows = [{"cited_urls": [
            "https://gymshark.com/x",
            "http://www.gymshark.com/x",
            "https://uk.gymshark.com/x",
        ]}]
        assert ac.is_url_cited("https://gymshark.com/x", rows) == 1


# ── _stem ─────────────────────────────────────────────────────────────────────

class TestStem:
    def test_simple_s(self, ac):
        assert ac._stem("squats") == "squat"

    def test_plural_long(self, ac):
        assert ac._stem("leggings") == "legging"

    def test_ies_to_y(self, ac):
        assert ac._stem("berries") == "berry"

    def test_es_drop(self, ac):
        assert ac._stem("boxes") == "box"

    def test_ss_exception(self, ac):
        assert ac._stem("less") == "less"

    def test_short_word(self, ac):
        # short words (< 4 chars) stay untouched per spec
        assert ac._stem("cat") == "cat"
        assert ac._stem("is") == "is"


# ── _tokenize ─────────────────────────────────────────────────────────────────

class TestTokenize:
    def test_drops_stopwords(self, ac):
        out = ac._tokenize("the best guide for squats")
        assert "the" not in out
        assert "best" not in out
        assert "guide" not in out
        assert "for" not in out
        assert "squat" in out

    def test_lowercases(self, ac):
        out = ac._tokenize("SQUATS Leggings")
        assert all(t == t.lower() for t in out)
        assert "squat" in out
        assert "legging" in out

    def test_min_length(self, ac):
        out = ac._tokenize("ab cd squats")
        assert "ab" not in out
        assert "cd" not in out
        assert "squat" in out

    def test_applies_stemming(self, ac):
        out = ac._tokenize("running squats berries")
        assert "squat" in out
        assert "berry" in out


# ── cluster_filter ────────────────────────────────────────────────────────────

class TestClusterFilter:
    def test_empty_returns_none(self, ac):
        assert ac.cluster_filter("") is None
        assert ac.cluster_filter(None) is None
        assert ac.cluster_filter(",,,") is None

    def test_strict_match_all_tokens(self, ac):
        cf = ac.cluster_filter("squat proof leggings")
        assert cf({"query_tested": "are squat proof leggings worth it"}) is True

    def test_loose_fallback_one_token(self, ac):
        cf = ac.cluster_filter("squat proof leggings")
        # only one cluster token "legging" overlaps via fallback
        assert cf({"query_tested": "comfortable leggings for women"}) is True

    def test_case_insensitive(self, ac):
        cf = ac.cluster_filter("SQUAT PROOF LEGGINGS")
        assert cf({"query_tested": "Best Squat Proof Leggings"}) is True

    def test_pluralization_handling(self, ac):
        cf = ac.cluster_filter("squat proof leggings")
        assert cf({"query_tested": "best squats and leggings for the gym"}) is True

    def test_no_overlap(self, ac):
        cf = ac.cluster_filter("squat proof leggings")
        assert cf({"query_tested": "totally unrelated query about pasta"}) is False

    def test_empty_query(self, ac):
        cf = ac.cluster_filter("squat proof leggings")
        assert cf({"query_tested": ""}) is False


# ── presence_pct ──────────────────────────────────────────────────────────────

class TestPresencePct:
    def test_empty_rows(self, ac):
        assert ac.presence_pct([], "gymshark") == 0.0

    def test_counts_hits(self, ac):
        rows = [
            {"brands_mentioned_list": ["Gymshark"]},
            {"brands_mentioned_list": ["Nike"]},
            {"brands_mentioned_list": ["Gymshark Ltd"]},
            {"brands_mentioned_list": []},
        ]
        # 2 of 4 mention gymshark → 50%
        assert ac.presence_pct(rows, "gymshark") == 50.0

    def test_query_filter_applied(self, ac):
        rows = [
            {"query_tested": "squats", "brands_mentioned_list": ["Gymshark"]},
            {"query_tested": "pasta", "brands_mentioned_list": ["Gymshark"]},
            {"query_tested": "pasta", "brands_mentioned_list": []},
        ]
        # filter to pasta only: 1/2 = 50%
        f = lambda r: r["query_tested"] == "pasta"
        assert ac.presence_pct(rows, "gymshark", f) == 50.0

    def test_query_filter_yields_no_rows(self, ac):
        rows = [{"query_tested": "x", "brands_mentioned_list": ["Gymshark"]}]
        assert ac.presence_pct(rows, "gymshark", lambda r: False) == 0.0


# ── target_in_row ─────────────────────────────────────────────────────────────

class TestTargetInRow:
    def test_exact_match(self, ac):
        assert ac.target_in_row({"brands_mentioned_list": ["Gymshark"]}, "gymshark") is True

    def test_substring_in_brand(self, ac):
        # "gymshark ltd" contains "gymshark"
        assert ac.target_in_row({"brands_mentioned_list": ["Gymshark Ltd"]}, "gymshark") is True

    def test_case_insensitive(self, ac):
        assert ac.target_in_row({"brands_mentioned_list": ["GYMSHARK"]}, "gymshark") is True

    def test_not_mentioned(self, ac):
        assert ac.target_in_row({"brands_mentioned_list": ["Nike", "Adidas"]}, "gymshark") is False

    def test_missing_field(self, ac):
        assert ac.target_in_row({}, "gymshark") is False

    def test_skips_empty_entries(self, ac):
        assert ac.target_in_row({"brands_mentioned_list": ["", None, "Gymshark"]}, "gymshark") is True


# ── closest_run_date ──────────────────────────────────────────────────────────

class TestClosestRunDate:
    def test_nearest_by_abs_delta(self, ac):
        target = date(2026, 1, 17)
        dates = [date(2026, 1, 5), date(2026, 1, 17), date(2026, 1, 31)]
        assert ac.closest_run_date(target, dates) == date(2026, 1, 17)

    def test_nearest_with_offset(self, ac):
        target = date(2026, 1, 15)
        dates = [date(2026, 1, 5), date(2026, 1, 17), date(2026, 1, 31)]
        assert ac.closest_run_date(target, dates) == date(2026, 1, 17)

    def test_empty(self, ac):
        assert ac.closest_run_date(date(2026, 1, 1), []) is None

    def test_single(self, ac):
        assert ac.closest_run_date(date(2026, 1, 1), [date(2099, 1, 1)]) == date(2099, 1, 1)


# ── parse_iso ─────────────────────────────────────────────────────────────────

class TestParseIso:
    def test_valid(self, ac):
        assert ac.parse_iso("2026-01-17") == date(2026, 1, 17)

    def test_whitespace_ok(self, ac):
        assert ac.parse_iso("  2026-01-17 ") == date(2026, 1, 17)

    def test_invalid_raises(self, ac):
        with pytest.raises(Exception):
            ac.parse_iso("not-a-date")
        with pytest.raises(Exception):
            ac.parse_iso("2026/01/17")


# ── fmt_chart_label ───────────────────────────────────────────────────────────

class TestFmtChartLabel:
    def test_format(self, ac):
        import sys
        label = ac.fmt_chart_label(date(2025, 10, 20))
        if sys.platform != "win32":
            assert label == "Oct 20'25"
        # Always end with 'YY apostrophe pattern
        assert "'25" in label
        assert "Oct" in label


# ── _classify ─────────────────────────────────────────────────────────────────

class TestClassify:
    def test_strong(self, ac):
        # cluster_lift > overall_lift + STRONG_LIFT_PP (2.0)
        assert ac._classify(5.0, 1.0) == "strong"
        assert ac._classify(2.01, 0.0) == "strong"

    def test_moderate(self, ac):
        # cluster_lift > overall_lift, but within +2pp
        assert ac._classify(2.0, 1.0) == "moderate"
        assert ac._classify(1.5, 1.0) == "moderate"

    def test_weak(self, ac):
        # 0 < cluster_lift <= overall_lift
        assert ac._classify(0.5, 1.0) == "weak"
        assert ac._classify(1.0, 1.0) == "weak"

    def test_none(self, ac):
        assert ac._classify(0, 1) == "none"
        assert ac._classify(-1, 5) == "none"


# ── compute_attribution ───────────────────────────────────────────────────────

class TestComputeAttribution:
    def test_two_runs_one_planner_row_yields_one_attribution(self, ac, sample_run_rows):
        planner = [{
            "publish_date": date(2026, 1, 10),
            "content_type": "Blog",
            "title_url": "https://gymshark.com/blog/squat-proof",
            "target_cluster": "squat proof leggings",
            "lag_days": 7,
            "status": "live",
        }]
        # baseline 25% (1/4 from constructed run), attr from rows that have 2/4 with gymshark
        run1 = [
            {"query_tested": "squats", "brands_mentioned_list": ["Gymshark"], "cited_urls": []},
            {"query_tested": "pasta", "brands_mentioned_list": [], "cited_urls": []},
            {"query_tested": "leggings", "brands_mentioned_list": [], "cited_urls": []},
            {"query_tested": "shoes", "brands_mentioned_list": [], "cited_urls": []},
        ]
        runs = [(date(2026, 1, 5), run1), (date(2026, 1, 17), sample_run_rows)]
        attrs, breakouts = ac.compute_attribution(planner, runs, "Gymshark")
        assert len(attrs) == 1
        assert attrs[0]["content_type"] == "Blog"

    def test_cited_status_and_primary(self, ac, sample_run_rows):
        planner = [{
            "publish_date": date(2026, 1, 10),
            "content_type": "Blog",
            "title_url": "https://gymshark.com/blog/squat-proof",
            "target_cluster": "squat proof leggings",
            "lag_days": 7,
            "status": "live",
        }]
        run1 = [{"query_tested": "x", "brands_mentioned_list": [], "cited_urls": []}] * 4
        runs = [(date(2026, 1, 5), run1), (date(2026, 1, 17), sample_run_rows)]
        attrs, _ = ac.compute_attribution(planner, runs, "Gymshark")
        assert attrs[0]["status"] == "cited"
        assert attrs[0]["primary"] is True
        assert attrs[0]["citation_count"] >= 1

    def test_only_one_primary_on_same_publish_date(self, ac, sample_run_rows):
        planner = [
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
                "title_url": "https://gymshark.com/blog/squat-proof",
                "target_cluster": "squat proof leggings",
                "lag_days": 7,
                "status": "live",
            },
        ]
        run1 = [{"query_tested": "x", "brands_mentioned_list": [], "cited_urls": []}] * 4
        runs = [(date(2026, 1, 5), run1), (date(2026, 1, 17), sample_run_rows)]
        attrs, _ = ac.compute_attribution(planner, runs, "Gymshark")
        primary_count = sum(1 for a in attrs if a["primary"])
        assert primary_count == 1

    def test_status_cited_beats_strong_in_tiebreaker(self, ac):
        # One row is cited; another has strong cluster lift. Cited should win primary.
        run1 = [{"query_tested": "squat leggings", "brands_mentioned_list": [], "cited_urls": []}] * 4
        run2 = [
            {"query_tested": "squat leggings",
             "brands_mentioned_list": ["Gymshark"],
             "cited_urls": ["gymshark.com/blog/cited-page"]},
            {"query_tested": "squat leggings",
             "brands_mentioned_list": ["Gymshark"],
             "cited_urls": []},
            {"query_tested": "squat leggings",
             "brands_mentioned_list": ["Gymshark"],
             "cited_urls": []},
            {"query_tested": "x",
             "brands_mentioned_list": [],
             "cited_urls": []},
        ]
        runs = [(date(2026, 1, 5), run1), (date(2026, 1, 17), run2)]
        planner = [
            {
                "publish_date": date(2026, 1, 10),
                "content_type": "Blog",
                "title_url": "https://gymshark.com/blog/cited-page",
                "target_cluster": "squat leggings",
                "lag_days": 7,
                "status": "live",
            },
            {
                "publish_date": date(2026, 1, 10),
                "content_type": "FAQ",
                "title_url": "https://gymshark.com/faq/uncited",
                "target_cluster": "squat leggings",
                "lag_days": 7,
                "status": "live",
            },
        ]
        attrs, _ = ac.compute_attribution(planner, runs, "Gymshark")
        primary = [a for a in attrs if a["primary"]]
        assert len(primary) == 1
        assert primary[0]["status"] == "cited"
        assert primary[0]["content_type"] == "Blog"

    def test_breakout_detection(self, ac):
        # baseline 0%, attr 75% → +75pp >= 3pp threshold
        run1 = [{"query_tested": "x", "brands_mentioned_list": [], "cited_urls": []}] * 4
        run2 = [
            {"query_tested": "x", "brands_mentioned_list": ["Gymshark"], "cited_urls": []},
            {"query_tested": "x", "brands_mentioned_list": ["Gymshark"], "cited_urls": []},
            {"query_tested": "x", "brands_mentioned_list": ["Gymshark"], "cited_urls": []},
            {"query_tested": "x", "brands_mentioned_list": [], "cited_urls": []},
        ]
        runs = [(date(2026, 1, 5), run1), (date(2026, 1, 17), run2)]
        _, breakouts = ac.compute_attribution([], runs, "Gymshark")
        assert len(breakouts) == 1
        assert breakouts[0]["date"] == date(2026, 1, 17)
        assert breakouts[0]["delta_pp"] >= ac.BREAKOUT_THRESHOLD_PP

    def test_no_breakout_below_threshold(self, ac):
        run1 = [{"query_tested": "x", "brands_mentioned_list": ["Gymshark"], "cited_urls": []}] * 4
        run2 = [{"query_tested": "x", "brands_mentioned_list": ["Gymshark"], "cited_urls": []}] * 4
        runs = [(date(2026, 1, 5), run1), (date(2026, 1, 17), run2)]
        _, breakouts = ac.compute_attribution([], runs, "Gymshark")
        assert breakouts == []

    def test_insufficient_history_when_single_run(self, ac):
        planner = [{
            "publish_date": date(2026, 1, 10),
            "content_type": "Blog",
            "title_url": "https://gymshark.com/x",
            "target_cluster": "x",
            "lag_days": 7,
            "status": "live",
        }]
        run1 = [{"query_tested": "x", "brands_mentioned_list": ["Gymshark"], "cited_urls": []}]
        runs = [(date(2026, 1, 5), run1)]
        attrs, _ = ac.compute_attribution(planner, runs, "Gymshark")
        assert attrs[0]["status"] == "insufficient_history"
        assert attrs[0]["primary"] is False
        assert attrs[0]["cluster_lift_pp"] is None

    def test_non_live_rows_ignored(self, ac):
        planner = [{
            "publish_date": date(2026, 1, 10),
            "content_type": "Blog",
            "title_url": "https://gymshark.com/x",
            "target_cluster": "x",
            "lag_days": 7,
            "status": "draft",
        }]
        run1 = [{"query_tested": "x", "brands_mentioned_list": [], "cited_urls": []}]
        run2 = [{"query_tested": "x", "brands_mentioned_list": ["Gymshark"], "cited_urls": []}]
        runs = [(date(2026, 1, 5), run1), (date(2026, 1, 17), run2)]
        attrs, _ = ac.compute_attribution(planner, runs, "Gymshark")
        assert attrs == []


# ── build_strategy_events ─────────────────────────────────────────────────────

class TestBuildStrategyEvents:
    def test_empty_runs_returns_empty(self, ac):
        assert ac.build_strategy_events([], [], []) == []

    def test_impl_and_attr_events_share_pair_id(self, ac):
        attrs = [{
            "publish_date": "2026-01-10",
            "attr_date":    "2026-01-17",
            "content_type": "Blog",
            "title_url":    "https://gymshark.com/x",
            "status":       "strong",
            "cluster_lift_pp": 5.0,
            "overall_lift_pp": 1.0,
            "citation_count":  0,
            "primary":         True,
        }]
        runs = [(date(2026, 1, 5), []), (date(2026, 1, 17), [])]
        events = ac.build_strategy_events(attrs, [], runs)
        impl_events = [e for e in events if e["kind"] == "impl"]
        attr_events = [e for e in events if e["kind"] == "attr"]
        assert len(impl_events) == 1
        assert len(attr_events) == 1
        assert impl_events[0]["pair_id"] == attr_events[0]["pair_id"]
        assert impl_events[0]["pair_id"] is not None

    def test_only_impl_when_not_primary(self, ac):
        attrs = [{
            "publish_date": "2026-01-10",
            "attr_date":    "2026-01-17",
            "content_type": "FAQ",
            "title_url":    "https://gymshark.com/x",
            "status":       "weak",
            "cluster_lift_pp": 0.5,
            "overall_lift_pp": 1.0,
            "citation_count":  0,
            "primary":         False,
        }]
        runs = [(date(2026, 1, 5), []), (date(2026, 1, 17), [])]
        events = ac.build_strategy_events(attrs, [], runs)
        assert len([e for e in events if e["kind"] == "attr"]) == 0
        impl = [e for e in events if e["kind"] == "impl"]
        assert len(impl) == 1
        assert impl[0]["pair_id"] is None

    def test_row_uses_content_type_lane(self, ac):
        attrs = [{
            "publish_date": "2026-01-10",
            "attr_date":    "2026-01-17",
            "content_type": "Schema",
            "title_url":    "https://x.com",
            "status":       "strong",
            "cluster_lift_pp": 5.0,
            "overall_lift_pp": 1.0,
            "citation_count":  0,
            "primary":         True,
        }]
        runs = [(date(2026, 1, 5), []), (date(2026, 1, 17), [])]
        events = ac.build_strategy_events(attrs, [], runs)
        for e in events:
            if e["kind"] in ("impl", "attr"):
                assert e["row"] == ac.CONTENT_TYPE_LANES["Schema"]

    def test_breakouts_use_breakout_lane(self, ac):
        breakouts = [{"date": date(2026, 1, 17), "delta_pp": 5.0, "presence": 30.0}]
        runs = [(date(2026, 1, 5), []), (date(2026, 1, 17), [])]
        events = ac.build_strategy_events([], breakouts, runs)
        assert len(events) == 1
        assert events[0]["row"] == ac.BREAKOUT_LANE
        assert events[0]["kind"] == "breakout"
        assert events[0]["color"] == ac.BREAKOUT_COLOR

    def test_skip_insufficient_history(self, ac):
        attrs = [{
            "publish_date": "2026-01-10",
            "attr_date":    "2026-01-17",
            "content_type": "Blog",
            "title_url":    "https://x.com",
            "status":       "insufficient_history",
            "cluster_lift_pp": None,
            "overall_lift_pp": None,
            "citation_count":  0,
            "primary":         False,
        }]
        runs = [(date(2026, 1, 5), []), (date(2026, 1, 17), [])]
        events = ac.build_strategy_events(attrs, [], runs)
        assert events == []


# ── _resolve_header ───────────────────────────────────────────────────────────

class TestResolveHeader:
    def test_case_insensitive(self, ac):
        assert ac._resolve_header(["Publish Date", "URL"], ["publish_date", "publish date"]) == "Publish Date"

    def test_returns_first_match(self, ac):
        # "publish date" matches before "Publish Date" alt name
        result = ac._resolve_header(["Publish Date", "URL"], ["publish date", "url"])
        assert result == "Publish Date"

    def test_no_match(self, ac):
        assert ac._resolve_header(["Foo", "Bar"], ["publish_date"]) is None

    def test_empty_headers(self, ac):
        assert ac._resolve_header([], ["publish_date"]) is None


# ── cluster_score ─────────────────────────────────────────────────────────────

class TestClusterScore:
    def test_full_term_match_scores_one(self, ac):
        # All cluster tokens present in the query -> 1.0
        assert ac.cluster_score("squat proof leggings", "best squat proof leggings") == 1.0

    def test_partial_token_match_between_floor_and_one(self, ac):
        # 2 of 3 cluster tokens overlap -> proportion 2/3, boosted by 1.2 = 0.8 (capped)
        s = ac.cluster_score("squat proof leggings", "squat proof gear")
        assert 0.35 < s < 1.0

    def test_single_token_overlap_hits_floor(self, ac):
        # Only "legging" overlaps -> 1/3 ~= 0.33; floor at 0.35
        s = ac.cluster_score("squat proof leggings", "comfortable leggings for women")
        assert s == 0.35

    def test_empty_cluster_returns_zero(self, ac):
        assert ac.cluster_score("", "best squat proof leggings") == 0.0

    def test_empty_query_returns_zero(self, ac):
        assert ac.cluster_score("squat proof leggings", "") == 0.0

    def test_no_overlap_returns_zero(self, ac):
        assert ac.cluster_score("squat proof leggings", "italian pasta recipes") == 0.0

    def test_stemming_applies(self, ac):
        # cluster "squats" and query "squat" should match via stemming
        assert ac.cluster_score("squats", "best squat workouts") == 1.0


# ── weighted_presence_pct ─────────────────────────────────────────────────────

class TestWeightedPresencePct:
    def test_empty_cluster_falls_back_to_unweighted(self, ac):
        rows = [
            {"query_tested": "x", "brands_mentioned_list": ["Gymshark"]},
            {"query_tested": "y", "brands_mentioned_list": ["Nike"]},
        ]
        w = ac.weighted_presence_pct(rows, "gymshark", "")
        u = ac.presence_pct(rows, "gymshark")
        assert w == u

    def test_all_rows_zero_score_returns_zero(self, ac):
        rows = [
            {"query_tested": "italian pasta recipes", "brands_mentioned_list": ["Gymshark"]},
            {"query_tested": "ferrari cars", "brands_mentioned_list": ["Gymshark"]},
        ]
        assert ac.weighted_presence_pct(rows, "gymshark", "squat proof leggings") == 0.0

    def test_all_matching_rows_hit_target_returns_100(self, ac):
        rows = [
            {"query_tested": "best squat proof leggings", "brands_mentioned_list": ["Gymshark"]},
            {"query_tested": "squat proof leggings review", "brands_mentioned_list": ["Gymshark"]},
        ]
        assert ac.weighted_presence_pct(rows, "gymshark", "squat proof leggings") == 100.0

    def test_returns_value_in_range(self, ac):
        rows = [
            {"query_tested": "best squat proof leggings", "brands_mentioned_list": ["Gymshark"]},
            {"query_tested": "comfortable leggings", "brands_mentioned_list": []},
        ]
        v = ac.weighted_presence_pct(rows, "gymshark", "squat proof leggings")
        assert 0.0 <= v <= 100.0

    def test_higher_score_rows_weight_more(self, ac):
        # Full-match row (score 1.0) has Gymshark, single-token row (score 0.35) doesn't.
        # Weighted presence should exceed 50% because the hit carries more weight.
        rows = [
            {"query_tested": "best squat proof leggings", "brands_mentioned_list": ["Gymshark"]},
            {"query_tested": "comfortable leggings", "brands_mentioned_list": []},
        ]
        v = ac.weighted_presence_pct(rows, "gymshark", "squat proof leggings")
        assert v > 50.0


# ── _cluster_term_tokens ──────────────────────────────────────────────────────

class TestClusterTermTokens:
    def test_empty_returns_empty_list(self, ac):
        assert ac._cluster_term_tokens("") == []
        assert ac._cluster_term_tokens(None) == []

    def test_single_term_yields_one_set(self, ac):
        out = ac._cluster_term_tokens("squat proof leggings")
        assert len(out) == 1
        assert "squat" in out[0]
        assert "proof" in out[0]
        assert "legging" in out[0]

    def test_multi_comma_splits_into_n_sets(self, ac):
        out = ac._cluster_term_tokens("squat proof leggings, protein powder, running shoes")
        assert len(out) == 3

    def test_stopwords_removed(self, ac):
        out = ac._cluster_term_tokens("the best leggings for women")
        # Flatten and check
        all_toks = set().union(*out) if out else set()
        assert "the" not in all_toks
        assert "best" not in all_toks
        assert "for" not in all_toks
        assert "legging" in all_toks


# ── Claim-based double-counting protection ────────────────────────────────────

class TestDoubleCountingProtection:
    def _build_runs(self):
        from datetime import date as _date
        run1 = [
            {"query_tested": "best squat proof leggings", "brands_mentioned_list": [], "cited_urls": []},
            {"query_tested": "squat proof leggings review", "brands_mentioned_list": [], "cited_urls": []},
            {"query_tested": "top protein powder", "brands_mentioned_list": [], "cited_urls": []},
            {"query_tested": "protein powder review", "brands_mentioned_list": [], "cited_urls": []},
        ]
        run2 = [
            {"query_tested": "best squat proof leggings", "brands_mentioned_list": ["Gymshark"], "cited_urls": []},
            {"query_tested": "squat proof leggings review", "brands_mentioned_list": ["Gymshark"], "cited_urls": []},
            {"query_tested": "top protein powder", "brands_mentioned_list": ["Gymshark"], "cited_urls": []},
            {"query_tested": "protein powder review", "brands_mentioned_list": ["Gymshark"], "cited_urls": []},
        ]
        return [(_date(2026, 1, 5), run1), (_date(2026, 1, 17), run2)]

    def test_identical_clusters_only_one_claims(self, ac):
        from datetime import date as _date
        planner = [
            {
                "publish_date": _date(2026, 1, 10),
                "content_type": "Blog",
                "title_url": "https://gymshark.com/blog/a",
                "target_cluster": "squat proof leggings",
                "lag_days": 7,
                "status": "live",
            },
            {
                "publish_date": _date(2026, 1, 10),
                "content_type": "FAQ",
                "title_url": "https://gymshark.com/faq/a",
                "target_cluster": "squat proof leggings",
                "lag_days": 7,
                "status": "live",
            },
        ]
        attrs, _ = ac.compute_attribution(planner, self._build_runs(), "Gymshark")
        lifts = [a["cluster_lift_pp"] for a in attrs]
        # Exactly one piece should have positive lift; the other should be 0.0
        positive = [l for l in lifts if l and l > 0]
        zero = [l for l in lifts if l == 0.0]
        assert len(positive) == 1
        assert len(zero) == 1

    def test_disjoint_clusters_both_get_lift(self, ac):
        from datetime import date as _date
        planner = [
            {
                "publish_date": _date(2026, 1, 10),
                "content_type": "Blog",
                "title_url": "https://gymshark.com/blog/leggings",
                "target_cluster": "squat proof leggings",
                "lag_days": 7,
                "status": "live",
            },
            {
                "publish_date": _date(2026, 1, 10),
                "content_type": "FAQ",
                "title_url": "https://gymshark.com/faq/protein",
                "target_cluster": "protein powder",
                "lag_days": 7,
                "status": "live",
            },
        ]
        attrs, _ = ac.compute_attribution(planner, self._build_runs(), "Gymshark")
        assert all(a["cluster_lift_pp"] > 0 for a in attrs)

    def test_claimed_queries_field_populated(self, ac):
        from datetime import date as _date
        planner = [
            {
                "publish_date": _date(2026, 1, 10),
                "content_type": "Blog",
                "title_url": "https://gymshark.com/blog/a",
                "target_cluster": "squat proof leggings",
                "lag_days": 7,
                "status": "live",
            },
            {
                "publish_date": _date(2026, 1, 10),
                "content_type": "FAQ",
                "title_url": "https://gymshark.com/faq/a",
                "target_cluster": "squat proof leggings",
                "lag_days": 7,
                "status": "live",
            },
        ]
        attrs, _ = ac.compute_attribution(planner, self._build_runs(), "Gymshark")
        claimed_counts = sorted(len(a["claimed_queries"]) for a in attrs)
        # One piece wins all tie-breaks and claims both leggings queries; other claims 0
        assert claimed_counts[0] == 0
        assert claimed_counts[1] >= 1
        # All claimed_queries must be a list type
        for a in attrs:
            assert isinstance(a["claimed_queries"], list)

    def test_piece_claiming_more_queries_wins_primary(self, ac):
        from datetime import date as _date
        # Two pieces: piece A's cluster matches both leggings queries (score 1.0),
        # piece B's cluster ("stylish leggings") shares one token but loses ties.
        # Add noise queries that stay flat so brand-wide lift < cluster lift,
        # which lets cluster status reach "moderate"/"strong" and primary be set.
        run1 = [
            {"query_tested": "best squat proof leggings", "brands_mentioned_list": [], "cited_urls": []},
            {"query_tested": "squat proof leggings review", "brands_mentioned_list": [], "cited_urls": []},
            {"query_tested": "italian pasta recipes", "brands_mentioned_list": [], "cited_urls": []},
            {"query_tested": "ferrari cars", "brands_mentioned_list": [], "cited_urls": []},
        ]
        run2 = [
            {"query_tested": "best squat proof leggings", "brands_mentioned_list": ["Gymshark"], "cited_urls": []},
            {"query_tested": "squat proof leggings review", "brands_mentioned_list": ["Gymshark"], "cited_urls": []},
            {"query_tested": "italian pasta recipes", "brands_mentioned_list": [], "cited_urls": []},
            {"query_tested": "ferrari cars", "brands_mentioned_list": [], "cited_urls": []},
        ]
        runs = [(_date(2026, 1, 5), run1), (_date(2026, 1, 17), run2)]
        planner = [
            {
                "publish_date": _date(2026, 1, 10),
                "content_type": "Blog",
                "title_url": "https://gymshark.com/blog/a",
                "target_cluster": "squat proof leggings",
                "lag_days": 7,
                "status": "live",
            },
            {
                "publish_date": _date(2026, 1, 10),
                "content_type": "FAQ",
                "title_url": "https://gymshark.com/faq/a",
                "target_cluster": "stylish leggings",
                "lag_days": 7,
                "status": "live",
            },
        ]
        attrs, _ = ac.compute_attribution(planner, runs, "Gymshark")
        primary = [a for a in attrs if a["primary"]]
        assert len(primary) == 1
        # The primary piece should be the one with more claimed queries
        primary_claim_count = len(primary[0]["claimed_queries"])
        for a in attrs:
            assert primary_claim_count >= len(a["claimed_queries"])


# ── Output schema versioning ──────────────────────────────────────────────────

class TestSchemaVersioning:
    def _run_main(self, ac, tmp_path):
        """Subprocess-call attribute_content.py against the sample inputs."""
        import subprocess
        import sys as _sys
        from pathlib import Path as _Path

        REPO = _Path(ac.__file__).resolve().parents[3]
        skill = REPO / "AEO skills" / "04-aeo-content-attribution"
        script = skill / "scripts" / "attribute_content.py"
        examples = skill / "examples"
        out_dir = tmp_path / "out"
        result = subprocess.run(
            [
                _sys.executable, str(script),
                "--content-planner", str(examples / "sample_content_planner.csv"),
                "--runs-dir", str(examples / "sample_runs"),
                "--brand-profile", str(examples / "sample_brand_profile.json"),
                "--output-dir", str(out_dir),
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
        return out_dir

    def test_attributions_has_schema_version(self, ac, tmp_path):
        import json as _json
        out_dir = self._run_main(ac, tmp_path)
        payload = _json.loads((out_dir / "attributions.json").read_text(encoding="utf-8"))
        assert payload["_schema_version"] == ac.ATTRIBUTIONS_SCHEMA_VERSION

    def test_attributions_has_generated_at_iso_z(self, ac, tmp_path):
        import json as _json
        out_dir = self._run_main(ac, tmp_path)
        payload = _json.loads((out_dir / "attributions.json").read_text(encoding="utf-8"))
        gen = payload["_generated_at"]
        assert isinstance(gen, str)
        assert gen.endswith("Z")
        # Stripping the Z, the remainder must parse as ISO 8601
        from datetime import datetime as _dt
        _dt.fromisoformat(gen[:-1])

    def test_attributions_has_target_brand_and_lists(self, ac, tmp_path):
        import json as _json
        out_dir = self._run_main(ac, tmp_path)
        payload = _json.loads((out_dir / "attributions.json").read_text(encoding="utf-8"))
        assert "target_brand" in payload
        assert payload["target_brand"]
        assert isinstance(payload["attributions"], list)
        assert isinstance(payload["breakouts"], list)

    def test_strategy_events_wrapper(self, ac, tmp_path):
        import json as _json
        out_dir = self._run_main(ac, tmp_path)
        payload = _json.loads((out_dir / "strategy_events.json").read_text(encoding="utf-8"))
        assert payload["_schema_version"] == ac.STRATEGY_EVENTS_SCHEMA_VERSION
        assert "events" in payload
        assert isinstance(payload["events"], list)
        assert payload["_generated_at"].endswith("Z")


# ── JSON structured logging ──────────────────────────────────────────────────

def _run_attr_sample(ac, tmp_path, extra_args=None):
    """Helper that runs attribute_content.py against the bundled sample inputs."""
    import subprocess
    import sys as _sys
    from pathlib import Path as _Path

    REPO = _Path(ac.__file__).resolve().parents[3]
    skill = REPO / "AEO skills" / "04-aeo-content-attribution"
    script = skill / "scripts" / "attribute_content.py"
    examples = skill / "examples"
    out_dir = tmp_path / "out"
    cmd = [
        _sys.executable, str(script),
        "--content-planner", str(examples / "sample_content_planner.csv"),
        "--runs-dir", str(examples / "sample_runs"),
        "--brand-profile", str(examples / "sample_brand_profile.json"),
        "--output-dir", str(out_dir),
    ]
    if extra_args:
        cmd += list(extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result, out_dir


class TestJsonLogging:
    def test_json_mode_emits_parseable_json_lines(self, ac, tmp_path):
        import json as _json
        result, _ = _run_attr_sample(ac, tmp_path, ["--log-format", "json"])
        assert result.returncode == 0, result.stderr
        lines = [ln for ln in result.stderr.splitlines() if ln.strip().startswith("{")]
        assert lines, "expected at least one JSON log line on stderr"
        for ln in lines:
            obj = _json.loads(ln)
            for key in ("ts", "level", "logger", "msg"):
                assert key in obj, f"missing {key} in {obj}"
            assert obj["ts"].endswith("Z")
            assert obj["level"] in {"INFO", "WARNING", "ERROR", "DEBUG"}

    def test_text_mode_does_not_emit_json(self, ac, tmp_path):
        import json as _json
        result, _ = _run_attr_sample(ac, tmp_path, ["--log-format", "text"])
        assert result.returncode == 0, result.stderr
        lines = [ln for ln in result.stderr.splitlines() if ln.strip()]
        assert lines, "expected log output on stderr"
        parsed_any = False
        for ln in lines:
            try:
                _json.loads(ln)
                parsed_any = True
            except _json.JSONDecodeError:
                pass
        assert not parsed_any, "text mode should not produce JSON-parseable lines"

    def test_default_format_is_text(self, ac, tmp_path):
        import json as _json
        result, _ = _run_attr_sample(ac, tmp_path, [])
        assert result.returncode == 0, result.stderr
        lines = [ln for ln in result.stderr.splitlines() if ln.strip()]
        for ln in lines:
            try:
                _json.loads(ln)
                pytest.fail("default mode should not emit JSON log lines")
            except _json.JSONDecodeError:
                pass

    def test_step_field_only_when_extra_passed(self, ac):
        """The JSON formatter should include 'step' only when extra={'step': ...} is provided."""
        import json as _json
        import logging as _logging

        formatter = ac._JsonFormatter()
        plain = _logging.LogRecord(
            name="attribute_content", level=_logging.INFO, pathname="x", lineno=1,
            msg="hello %s", args=("world",), exc_info=None,
        )
        with_step = _logging.LogRecord(
            name="attribute_content", level=_logging.INFO, pathname="x", lineno=1,
            msg="hello", args=(), exc_info=None,
        )
        with_step.step = "attribute_content"

        plain_payload = _json.loads(formatter.format(plain))
        step_payload = _json.loads(formatter.format(with_step))

        assert "step" not in plain_payload
        assert plain_payload["msg"] == "hello world"
        assert step_payload["step"] == "attribute_content"


# ── Threshold CLI flags ──────────────────────────────────────────────────────

class TestThresholdCliFlags:
    def test_high_breakout_threshold_yields_zero_breakouts(self, ac, tmp_path):
        import json as _json
        result, out_dir = _run_attr_sample(ac, tmp_path, ["--breakout-threshold-pp", "99.0"])
        assert result.returncode == 0, result.stderr
        payload = _json.loads((out_dir / "attributions.json").read_text(encoding="utf-8"))
        assert payload["breakouts"] == []

    def test_default_breakouts_nonempty_for_sanity(self, ac, tmp_path):
        """Sanity check: without override, the sample produces at least one breakout."""
        import json as _json
        result, out_dir = _run_attr_sample(ac, tmp_path, [])
        assert result.returncode == 0, result.stderr
        payload = _json.loads((out_dir / "attributions.json").read_text(encoding="utf-8"))
        assert len(payload["breakouts"]) > 0

    def test_high_strong_lift_yields_no_strong_status(self, ac, tmp_path):
        import json as _json
        result, out_dir = _run_attr_sample(ac, tmp_path, ["--strong-lift-pp", "1000.0"])
        assert result.returncode == 0, result.stderr
        payload = _json.loads((out_dir / "attributions.json").read_text(encoding="utf-8"))
        strong = [a for a in payload["attributions"] if a.get("status") == "strong"]
        assert strong == []
