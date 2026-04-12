"""Unit tests for agent/shared/knowledge.py"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agent.shared.knowledge import fill_knowledge_gap, get_knowledge_tool_definition


class TestFillKnowledgeGap:
    @pytest.mark.asyncio
    async def test_returns_existing_skill_without_api_call(self, tmp_path):
        """Fast path: skill exists → return immediately, no research."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "fastmcp.md").write_text("# fastmcp\n\nOverview content here.")

        mock_client = AsyncMock()
        result = await fill_knowledge_gap(
            domain="fastmcp",
            question="how to register tools",
            intent_spec={"raw_goal": "build an MCP server"},
            skills_dir=str(skills_dir),
            client=mock_client,
        )

        assert "fastmcp" in result.lower()
        mock_client.messages.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_normalises_domain_slug(self, tmp_path):
        """Spaces and uppercase are normalised to lowercase-hyphen."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "perplexity-api.md").write_text("# perplexity-api\nContent.")

        result = await fill_knowledge_gap(
            domain="Perplexity API",
            question="authentication",
            intent_spec={"raw_goal": "build a search tool"},
            skills_dir=str(skills_dir),
        )
        assert "perplexity" in result.lower()

    @pytest.mark.asyncio
    async def test_researches_missing_domain(self, tmp_path):
        """Slow path: skill missing → calls researcher, writes file, returns content."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        fake_skill_content = "# new-domain\n\n## Overview\nFake content.\n\nrecommended_tool: fake-lib"

        mock_client = AsyncMock()

        with patch(
            "agent.shared.knowledge.get_search_mode", return_value="tavily"
        ), patch(
            "agent.shared.knowledge._research_tavily",
            new=AsyncMock(return_value={
                "skill_content": fake_skill_content,
                "recommended_tool": "fake-lib",
                "references": ["https://example.com"],
            }),
        ):
            result = await fill_knowledge_gap(
                domain="new-domain",
                question="how to use it",
                intent_spec={"raw_goal": "build something"},
                skills_dir=str(skills_dir),
                client=mock_client,
            )

        assert result == fake_skill_content
        # Skill file should be written for future calls
        assert (skills_dir / "new-domain.md").exists()

    @pytest.mark.asyncio
    async def test_missing_domain_written_to_skills(self, tmp_path):
        """After gap is filled, the skill must be written to disk."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        content = "# test-lib\nContent.\nrecommended_tool: test-lib"

        with patch("agent.shared.knowledge.get_search_mode", return_value="tavily"), \
             patch("agent.shared.knowledge._research_tavily",
                   new=AsyncMock(return_value={
                       "skill_content": content, "recommended_tool": "test-lib",
                       "references": [],
                   })):
            await fill_knowledge_gap(
                domain="test-lib",
                question="basic usage",
                intent_spec={"raw_goal": "test"},
                skills_dir=str(skills_dir),
            )

        assert (skills_dir / "test-lib.md").read_text() == content

    @pytest.mark.asyncio
    async def test_empty_domain_raises(self, tmp_path):
        with pytest.raises(ValueError, match="domain"):
            await fill_knowledge_gap(
                domain="",
                question="anything",
                intent_spec={"raw_goal": "test"},
                skills_dir=str(tmp_path / "skills"),
            )

    @pytest.mark.asyncio
    async def test_race_condition_existing_file_returns_content(self, tmp_path):
        """If file appears between read and write (race), return existing content."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        existing = "# race-domain\nAlready written."

        def write_and_raise(*args, **kwargs):
            # Simulate another coroutine writing the file first
            (skills_dir / "race-domain.md").write_text(existing)
            raise FileExistsError("race-domain")

        with patch("agent.shared.knowledge.get_search_mode", return_value="tavily"), \
             patch("agent.shared.knowledge._research_tavily",
                   new=AsyncMock(return_value={
                       "skill_content": "new content", "recommended_tool": "x",
                       "references": [],
                   })):
            from agent.shared.state import SkillsStore
            with patch.object(SkillsStore, "write_new", side_effect=write_and_raise):
                result = await fill_knowledge_gap(
                    domain="race-domain",
                    question="usage",
                    intent_spec={"raw_goal": "test"},
                    skills_dir=str(skills_dir),
                )

        assert result == existing


class TestGetKnowledgeToolDefinition:
    def test_returns_valid_tool_definition(self):
        tool = get_knowledge_tool_definition()
        assert tool["name"] == "fill_knowledge_gap"
        assert "input_schema" in tool
        assert "domain" in tool["input_schema"]["properties"]
        assert "question" in tool["input_schema"]["properties"]
        assert tool["input_schema"]["required"] == ["domain", "question"]

    def test_description_is_non_empty(self):
        tool = get_knowledge_tool_definition()
        assert len(tool["description"]) > 50
