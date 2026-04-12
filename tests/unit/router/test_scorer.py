"""Unit tests for agent/router/scorer.py"""
from __future__ import annotations

import pytest
from agent.router.scorer import score, ScoreResult, AUTO_MERGE_THRESHOLD


@pytest.fixture
def all_green_signals():
    return {
        "ci_passed": True,
        "smoke_tests_passed": True,
        "coverage_pct": 92.0,
        "lint_passed": True,
        "type_check_passed": True,
        "test_failures": [],
        "deploy_succeeded": True,
    }


@pytest.fixture
def failing_signals():
    return {
        "ci_passed": False,
        "smoke_tests_passed": False,
        "coverage_pct": 30.0,
        "lint_passed": False,
        "type_check_passed": False,
        "test_failures": [{"test": "test_main", "error": "AssertionError"}],
        "deploy_succeeded": False,
    }


@pytest.mark.skip(reason="Not implemented yet — Phase 1 step 12")
class TestScorer:
    def test_returns_score_result_shape(self, all_green_signals):
        result = score(all_green_signals)
        assert "confidence" in result
        assert "risk_dimensions" in result
        assert "breakdown" in result

    def test_all_green_confidence_above_threshold(self, all_green_signals):
        result = score(all_green_signals)
        assert result["confidence"] >= AUTO_MERGE_THRESHOLD

    def test_all_failing_confidence_below_threshold(self, failing_signals):
        result = score(failing_signals)
        assert result["confidence"] < AUTO_MERGE_THRESHOLD

    def test_confidence_is_0_to_100(self, all_green_signals):
        result = score(all_green_signals)
        assert 0.0 <= result["confidence"] <= 100.0

    def test_breakdown_contributions_sum_to_confidence(self, all_green_signals):
        result = score(all_green_signals)
        total = sum(result["breakdown"].values())
        assert abs(total - result["confidence"]) < 0.01

    def test_empty_signals_raises(self):
        with pytest.raises((KeyError, ValueError)):
            score({})
