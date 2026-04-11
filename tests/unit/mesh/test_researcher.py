"""Unit tests for agent/mesh/researcher.py"""
from __future__ import annotations

import pytest
from agent.mesh.researcher import run, ResearchResult


class TestResearcher:
    @pytest.mark.asyncio
    async def test_happy_path_returns_research_result(self, sample_intent_spec, tmp_path):
        result = await run(sample_intent_spec, skills_dir=str(tmp_path / "skills"))
        assert "recommended_stack" in result
        assert "skills_written" in result
        assert "references" in result

    @pytest.mark.asyncio
    async def test_skills_files_written_to_disk(self, sample_intent_spec, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = await run(sample_intent_spec)
        assert len(result["skills_written"]) > 0

    @pytest.mark.asyncio
    async def test_recommended_stack_keys_match_domains(self, sample_intent_spec, tmp_path):
        result = await run(sample_intent_spec, skills_dir=str(tmp_path / "skills"))
        for domain in sample_intent_spec["integrations"]:
            assert any(domain.lower() in k.lower() for k in result["recommended_stack"])

    @pytest.mark.asyncio
    async def test_missing_intent_spec_raises(self):
        with pytest.raises((KeyError, ValueError)):
            await run({})
