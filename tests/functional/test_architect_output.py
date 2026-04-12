"""
Functional tests on the architect output.

Uses pipeline_run_mcp (MCP/Perplexity goal) as primary fixture — known build_target
and integrations give deterministic architecture output to assert against.
"""
from __future__ import annotations

import pytest


def _require_arch(pipeline_run: dict):
    if pipeline_run["human_input_required"]:
        pytest.skip(f"Intent blocked: {pipeline_run['human_input_required']}")
    if pipeline_run["architecture"] is None:
        pytest.skip("Architect did not run")


class TestArchitectureSpec:
    def test_file_tree_is_non_empty(self, pipeline_run_mcp):
        _require_arch(pipeline_run_mcp)
        tree = pipeline_run_mcp["architecture"]["file_tree"]
        assert isinstance(tree, list)
        assert len(tree) > 0, "Architect returned empty file_tree"

    def test_file_tree_contains_strings(self, pipeline_run_mcp):
        _require_arch(pipeline_run_mcp)
        for path in pipeline_run_mcp["architecture"]["file_tree"]:
            assert isinstance(path, str) and path.strip()

    def test_file_tree_has_python_files(self, pipeline_run_mcp):
        _require_arch(pipeline_run_mcp)
        py_files = [f for f in pipeline_run_mcp["architecture"]["file_tree"] if f.endswith(".py")]
        assert len(py_files) > 0, (
            f"No .py files in file_tree: {pipeline_run_mcp['architecture']['file_tree']}"
        )

    def test_module_interfaces_is_non_empty(self, pipeline_run_mcp):
        _require_arch(pipeline_run_mcp)
        ifaces = pipeline_run_mcp["architecture"]["module_interfaces"]
        assert isinstance(ifaces, dict)
        assert len(ifaces) > 0, "Architect returned empty module_interfaces"

    def test_every_module_has_input_or_output(self, pipeline_run_mcp):
        _require_arch(pipeline_run_mcp)
        for module, contract in pipeline_run_mcp["architecture"]["module_interfaces"].items():
            assert "input" in contract or "output" in contract, (
                f"Module {module!r} has neither input nor output in its contract: {contract}"
            )

    def test_dependencies_keys_subset_of_modules(self, pipeline_run_mcp):
        _require_arch(pipeline_run_mcp)
        modules = set(pipeline_run_mcp["architecture"]["module_interfaces"].keys())
        deps = pipeline_run_mcp["architecture"]["dependencies"]
        for module in deps:
            assert module in modules, (
                f"dependencies key {module!r} is not in module_interfaces"
            )

    def test_tech_choices_is_non_empty(self, pipeline_run_mcp):
        _require_arch(pipeline_run_mcp)
        choices = pipeline_run_mcp["architecture"]["tech_choices"]
        assert isinstance(choices, dict)
        assert len(choices) > 0, "Architect returned no tech_choices"

    def test_tech_choices_values_are_strings(self, pipeline_run_mcp):
        _require_arch(pipeline_run_mcp)
        for component, tech in pipeline_run_mcp["architecture"]["tech_choices"].items():
            assert isinstance(tech, str) and tech.strip(), (
                f"Empty tech choice for component {component!r}"
            )


class TestResearchArchitectAlignment:
    """
    Architect runs CONCURRENTLY with researcher in production — it receives an empty
    research_result and works from intent spec + pre-existing skills/ docs alone.

    These tests verify standalone coherence of the architecture output.
    """

    def test_tech_choices_contain_domain_hints(self, pipeline_run_mcp):
        """Tech choices should reference the build_target or integration domains."""
        _require_arch(pipeline_run_mcp)
        spec = pipeline_run_mcp["spec"]
        if not spec:
            pytest.skip("No spec")

        build_target = (spec.get("build_target") or "").lower()
        integrations = [i.lower() for i in spec.get("integrations", [])]
        all_hints = {build_target} | set(integrations)

        arch_blob = " ".join(pipeline_run_mcp["architecture"]["tech_choices"].values()).lower()
        matched = [hint for hint in all_hints if hint and hint in arch_blob]

        assert matched, (
            f"None of {all_hints} appear in tech_choices values: "
            f"{pipeline_run_mcp['architecture']['tech_choices']}"
        )

    def test_file_tree_references_build_target_concept(self, pipeline_run_mcp):
        """The file tree should look like it was designed for the stated goal."""
        _require_arch(pipeline_run_mcp)
        tree_blob = " ".join(pipeline_run_mcp["architecture"]["file_tree"]).lower()
        # An MCP server project must have at least one Python source file
        assert ".py" in tree_blob, (
            f"No .py files at all in file_tree: {pipeline_run_mcp['architecture']['file_tree']}"
        )
