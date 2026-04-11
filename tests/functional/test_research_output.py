"""
Functional tests on the researcher output.

Uses two session-scoped fixtures:
  pipeline_run     — vague goal, no integrations (tests fallback domain handling)
  pipeline_run_mcp — MCP/Perplexity goal with explicit integrations (tests domain coverage)
"""
from __future__ import annotations

import pytest


def _require_research(pipeline_run: dict):
    """Skip if pipeline didn't reach researcher stage."""
    if pipeline_run["human_input_required"]:
        pytest.skip(
            f"Intent block blocked — HumanInputRequired: {pipeline_run['human_input_required']}"
        )
    if pipeline_run["research"] is None:
        pytest.skip("Researcher did not run")


class TestResearchResult:
    def test_recommended_stack_is_non_empty(self, pipeline_run):
        _require_research(pipeline_run)
        stack = pipeline_run["research"]["recommended_stack"]
        assert isinstance(stack, dict)
        assert len(stack) > 0, "Researcher returned empty recommended_stack"

    def test_recommended_stack_values_are_strings(self, pipeline_run):
        _require_research(pipeline_run)
        for domain, tool in pipeline_run["research"]["recommended_stack"].items():
            assert isinstance(domain, str), f"Domain key is not string: {domain!r}"
            assert isinstance(tool, str), f"Tool value for {domain!r} is not string: {tool!r}"

    def test_skills_written_is_non_empty(self, pipeline_run):
        _require_research(pipeline_run)
        written = pipeline_run["research"]["skills_written"]
        assert isinstance(written, list)
        assert len(written) > 0, "Researcher wrote no skill files"

    def test_skills_written_to_disk(self, pipeline_run):
        _require_research(pipeline_run)
        skills_dir = pipeline_run["skills_dir"]
        for rel_path in pipeline_run["research"]["skills_written"]:
            # skills_written contains paths like "skills/perplexity-api.md"
            # actual file is in skills_dir / filename
            from pathlib import Path
            name = Path(rel_path).name
            full = skills_dir / name
            assert full.exists(), (
                f"Skill file listed in skills_written but not on disk: {full}"
            )

    def test_skill_files_have_content(self, pipeline_run):
        _require_research(pipeline_run)
        skills_dir = pipeline_run["skills_dir"]
        from pathlib import Path
        for rel_path in pipeline_run["research"]["skills_written"]:
            name = Path(rel_path).name
            full = skills_dir / name
            if full.exists():
                content = full.read_text()
                assert len(content) > 100, (
                    f"Skill file {name!r} is suspiciously short ({len(content)} chars)"
                )

    def test_skill_files_start_with_heading(self, pipeline_run):
        _require_research(pipeline_run)
        skills_dir = pipeline_run["skills_dir"]
        from pathlib import Path
        for rel_path in pipeline_run["research"]["skills_written"]:
            name = Path(rel_path).name
            full = skills_dir / name
            if full.exists():
                first_line = full.read_text().splitlines()[0]
                assert first_line.startswith("#"), (
                    f"Skill file {name!r} does not start with a markdown heading: {first_line!r}"
                )

    def test_references_is_list(self, pipeline_run):
        _require_research(pipeline_run)
        refs = pipeline_run["research"]["references"]
        assert isinstance(refs, list)

    def test_domains_cover_integrations(self, pipeline_run):
        _require_research(pipeline_run)
        spec = pipeline_run["spec"]
        if not spec:
            pytest.skip("No spec")
        integrations = spec.get("integrations", [])
        if not integrations:
            pytest.skip("No integrations in spec")
        stack_keys = " ".join(pipeline_run["research"]["recommended_stack"].keys()).lower()
        for integration in integrations:
            assert integration.lower() in stack_keys, (
                f"Integration {integration!r} not covered in recommended_stack keys: "
                f"{list(pipeline_run['research']['recommended_stack'].keys())}"
            )


class TestResearchQuality:
    """Qualitative checks on the synthesized skill docs."""

    def test_recommended_stack_contains_tool_names(self, pipeline_run):
        """Each recommended tool should look like a library name, not an empty string."""
        _require_research(pipeline_run)
        for domain, tool in pipeline_run["research"]["recommended_stack"].items():
            assert tool.strip(), f"Empty recommended tool for domain {domain!r}"
            assert len(tool) < 100, (
                f"recommended_tool for {domain!r} looks like a sentence, not a tool name: {tool!r}"
            )

    def test_at_least_one_reference_per_domain_when_tavily(self, pipeline_run):
        """When Tavily is active, researcher should have gathered URLs."""
        _require_research(pipeline_run)
        import os
        if not os.environ.get("TAVILY_API_KEY"):
            pytest.skip("Tavily not active — references not expected")
        refs = pipeline_run["research"]["references"]
        assert len(refs) > 0, "Tavily is active but researcher returned no references"

    def test_skill_files_mention_recommended_tool(self, pipeline_run):
        """Each skill file should mention its recommended tool somewhere in its content."""
        _require_research(pipeline_run)
        from pathlib import Path
        skills_dir = pipeline_run["skills_dir"]
        stack = pipeline_run["research"]["recommended_stack"]

        for domain, tool in stack.items():
            # Find the skill file for this domain
            candidate = skills_dir / f"{domain}.md"
            if not candidate.exists():
                continue
            content = candidate.read_text().lower()
            # Strip to just the first word of the tool name for a lenient check
            tool_hint = tool.split()[0].lower().rstrip(".,;")
            assert tool_hint in content, (
                f"Skill file {domain}.md does not mention its recommended tool {tool!r}"
            )


class TestMCPPipelineResearch:
    """
    Researcher tests using the MCP/Perplexity goal — has explicit integrations,
    known build_target, and deploy_target. This fixture exercises the full
    domain-coverage path that the vague goal skips over.
    """

    def test_recommended_stack_non_empty(self, pipeline_run_mcp):
        _require_research(pipeline_run_mcp)
        assert len(pipeline_run_mcp["research"]["recommended_stack"]) >= 2, (
            "MCP goal should produce at least 2 domain entries (integration + build target)"
        )

    def test_domains_cover_integrations(self, pipeline_run_mcp):
        """Perplexity is an explicit integration — its domain must appear in the stack."""
        _require_research(pipeline_run_mcp)
        spec = pipeline_run_mcp["spec"]
        integrations = spec.get("integrations", [])
        assert integrations, "MCP fixture should have at least one integration"
        stack_keys = " ".join(pipeline_run_mcp["research"]["recommended_stack"].keys()).lower()
        for integration in integrations:
            assert integration.lower() in stack_keys, (
                f"Integration {integration!r} not covered in recommended_stack: "
                f"{list(pipeline_run_mcp['research']['recommended_stack'].keys())}"
            )

    def test_mcp_domain_in_stack(self, pipeline_run_mcp):
        """build_target=mcp-server must map to the mcp-protocol domain."""
        _require_research(pipeline_run_mcp)
        stack_keys = list(pipeline_run_mcp["research"]["recommended_stack"].keys())
        assert any("mcp" in k.lower() for k in stack_keys), (
            f"mcp-protocol domain missing from stack: {stack_keys}"
        )

    def test_skills_written_for_mcp_and_perplexity(self, pipeline_run_mcp):
        _require_research(pipeline_run_mcp)
        skills_dir = pipeline_run_mcp["skills_dir"]
        written_names = [
            p.name for p in skills_dir.iterdir() if p.suffix == ".md"
        ]
        assert any("perplexity" in n for n in written_names), (
            f"No perplexity skill file written. Files: {written_names}"
        )
        assert any("mcp" in n for n in written_names), (
            f"No mcp skill file written. Files: {written_names}"
        )

    def test_concurrent_research_all_domains_written(self, pipeline_run_mcp):
        """With concurrent gather, all domains must complete — none silently dropped."""
        _require_research(pipeline_run_mcp)
        stack = pipeline_run_mcp["research"]["recommended_stack"]
        skills_written = pipeline_run_mcp["research"]["skills_written"]
        assert len(stack) == len(skills_written), (
            f"Domain count mismatch: {len(stack)} in stack vs {len(skills_written)} files written.\n"
            f"Stack: {list(stack.keys())}\nFiles: {skills_written}"
        )
