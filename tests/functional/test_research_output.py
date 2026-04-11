"""
Functional tests on the researcher output.

All tests share the session-scoped pipeline_run fixture (one real API call).
Tests are automatically skipped if the intent block was blocked by HumanInputRequired.
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
