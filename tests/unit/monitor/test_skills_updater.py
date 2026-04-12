"""Unit tests for agent/monitor/skills_updater.py"""
from __future__ import annotations

import pytest
from agent.monitor.skills_updater import update, SkillsUpdateResult


@pytest.mark.skip(reason="Not implemented yet — Phase 1 step 20")
class TestSkillsUpdater:
    @pytest.mark.asyncio
    async def test_returns_skills_update_result_shape(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        fix = {"branch_name": "fix/bug", "files_changed": ["agent/mesh/coder.py"],
               "patch_summary": "fixed null check in coder"}
        anomaly = {"type": "bug", "priority": "high", "run_id": "r1", "source_event": {}}
        result = await update(fix, anomaly)
        assert "skills_updated" in result
        assert "new_entries" in result

    @pytest.mark.asyncio
    async def test_append_only_does_not_delete_existing(self, tmp_path, monkeypatch):
        """Skills content must only grow, never shrink."""
        monkeypatch.chdir(tmp_path)
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_file = skills_dir / "anthropic-sdk.md"
        skill_file.write_text("# Original content\n")

        fix = {"branch_name": "fix/bug", "files_changed": [], "patch_summary": "fix"}
        anomaly = {"type": "bug", "priority": "low", "run_id": "r1", "source_event": {}}
        await update(fix, anomaly)

        content = skill_file.read_text()
        assert "# Original content" in content

    @pytest.mark.asyncio
    async def test_new_entries_is_list_of_strings(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        fix = {"branch_name": "fix/bug", "files_changed": [], "patch_summary": ""}
        anomaly = {"type": "bug", "priority": "low", "run_id": "r1", "source_event": {}}
        result = await update(fix, anomaly)
        assert isinstance(result["new_entries"], list)
