"""Unit tests for agent/monitor/fix_agent.py"""
from __future__ import annotations

import pytest
from agent.monitor.fix_agent import run, FixResult


@pytest.mark.skip(reason="Not implemented yet — Phase 1 step 18")
class TestFixAgent:
    @pytest.mark.asyncio
    async def test_returns_fix_result_shape(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        context = {
            "stack_trace": "Traceback...",
            "relevant_skills": ["# MCP Protocol\n..."],
            "relevant_files": ["agent/mesh/coder.py"],
            "run_id": "r1",
            "anomaly": {"type": "bug"},
        }
        result = await run(context)
        assert "branch_name" in result
        assert "pr_url" in result
        assert "files_changed" in result
        assert "patch_summary" in result
        assert "decision_log_path" in result

    @pytest.mark.asyncio
    async def test_decision_log_written_before_pr(self, tmp_path, monkeypatch):
        """decision_log_path must point to an existing file after run completes."""
        monkeypatch.chdir(tmp_path)
        context = {
            "stack_trace": "...", "relevant_skills": [], "relevant_files": [],
            "run_id": "r1", "anomaly": {"type": "bug"},
        }
        result = await run(context)
        from pathlib import Path
        assert Path(result["decision_log_path"]).exists()

    @pytest.mark.asyncio
    async def test_no_secret_values_in_patch(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        context = {
            "stack_trace": "...", "relevant_skills": [], "relevant_files": [],
            "run_id": "r1", "anomaly": {"type": "config"},
        }
        result = await run(context)
        assert "sk-ant-" not in result.get("patch_summary", "")
