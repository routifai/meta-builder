"""Unit tests for agent/monitor/validator.py"""
from __future__ import annotations

import pytest
from agent.monitor.validator import validate, ValidationResult, FIX_MERGE_THRESHOLD


@pytest.mark.skip(reason="Not implemented yet — Phase 1 step 19")
class TestValidator:
    @pytest.mark.asyncio
    async def test_returns_validation_result_shape(self, run_id):
        fix = {"branch_name": "fix/bug-123", "pr_url": "https://github.com/...",
               "files_changed": ["main.py"], "patch_summary": "fixed null check",
               "decision_log_path": "decision-log/r1/fix_agent/ts.json"}
        result = await validate(fix, run_id)
        assert "tests_passed" in result
        assert "regressions_found" in result
        assert "confidence" in result
        assert "failures" in result

    @pytest.mark.asyncio
    async def test_confidence_is_0_to_100(self, run_id):
        fix = {"branch_name": "fix/bug", "pr_url": "", "files_changed": [],
               "patch_summary": "", "decision_log_path": ""}
        result = await validate(fix, run_id)
        assert 0.0 <= result["confidence"] <= 100.0

    @pytest.mark.asyncio
    async def test_auto_merge_only_above_threshold(self, run_id):
        """Caller must check: confidence >= FIX_MERGE_THRESHOLD before merging."""
        fix = {"branch_name": "fix/bug", "pr_url": "", "files_changed": [],
               "patch_summary": "", "decision_log_path": ""}
        result = await validate(fix, run_id)
        # Just verify threshold constant is accessible and is 85
        assert FIX_MERGE_THRESHOLD == 85.0
