"""Unit tests for agent/mesh/architect.py"""
from __future__ import annotations

import pytest
from agent.mesh.architect import run, ArchitectureSpec


class TestArchitect:
    @pytest.mark.asyncio
    async def test_returns_architecture_spec_shape(self, sample_intent_spec):
        research = {"recommended_stack": {"mcp": "fastmcp"}, "skills_written": [], "references": []}
        result = await run(sample_intent_spec, research)
        assert "file_tree" in result
        assert "module_interfaces" in result
        assert "dependencies" in result
        assert "tech_choices" in result

    @pytest.mark.asyncio
    async def test_file_tree_is_list_of_strings(self, sample_intent_spec):
        research = {"recommended_stack": {}, "skills_written": [], "references": []}
        result = await run(sample_intent_spec, research)
        assert isinstance(result["file_tree"], list)
        assert all(isinstance(f, str) for f in result["file_tree"])

    @pytest.mark.asyncio
    async def test_module_interfaces_have_input_output(self, sample_intent_spec):
        research = {"recommended_stack": {}, "skills_written": [], "references": []}
        result = await run(sample_intent_spec, research)
        for module, contract in result["module_interfaces"].items():
            assert "input" in contract or "output" in contract

    @pytest.mark.asyncio
    async def test_empty_intent_raises(self):
        with pytest.raises((KeyError, ValueError)):
            await run({}, {})
