"""Unit tests for agent/mesh/plan_validator.py"""
from __future__ import annotations

import textwrap

import pytest

from agent.mesh.plan_validator import (
    ValidationResult,
    _check_python_file,
    _parse_symbols,
    build_revision_note,
    should_revise_plan,
    validate,
)


# ---------------------------------------------------------------------------
# _parse_symbols
# ---------------------------------------------------------------------------

class TestParseSymbols:
    def test_top_level_function(self):
        src = "def foo(): pass"
        top, classes = _parse_symbols(src)
        assert "foo" in top

    def test_async_function(self):
        src = "async def bar(): pass"
        top, classes = _parse_symbols(src)
        assert "bar" in top

    def test_class_with_methods(self):
        src = textwrap.dedent("""\
            class MyClass:
                def method_one(self): pass
                async def method_two(self): pass
        """)
        top, classes = _parse_symbols(src)
        assert "MyClass" in classes
        assert "method_one" in classes["MyClass"]
        assert "method_two" in classes["MyClass"]

    def test_nested_function_not_in_top_level(self):
        src = textwrap.dedent("""\
            def outer():
                def inner(): pass
        """)
        top, classes = _parse_symbols(src)
        assert "outer" in top
        assert "inner" not in top

    def test_syntax_error_returns_empty(self):
        top, classes = _parse_symbols("def (broken syntax !!!")
        assert top == set()
        assert classes == {}

    def test_empty_source_returns_empty(self):
        top, classes = _parse_symbols("")
        assert top == set()
        assert classes == {}

    def test_imports_and_constants_ignored(self):
        src = textwrap.dedent("""\
            import os
            PORT = 8080
            from pathlib import Path
        """)
        top, classes = _parse_symbols(src)
        assert top == set()
        assert classes == {}


# ---------------------------------------------------------------------------
# _check_python_file
# ---------------------------------------------------------------------------

class TestCheckPythonFile:
    def test_all_present_returns_empty(self):
        src = textwrap.dedent("""\
            def search(query: str) -> list:
                return []

            class SearchClient:
                def fetch(self, url: str) -> dict:
                    return {}
        """)
        file_plan = {
            "functions": [{"name": "search", "signature": "...", "docstring": "..."}],
            "classes": [
                {
                    "name": "SearchClient",
                    "bases": [],
                    "docstring": "...",
                    "methods": [{"name": "fetch", "signature": "...", "docstring": "..."}],
                }
            ],
        }
        mismatches = _check_python_file("src/search.py", file_plan, src)
        assert mismatches == []

    def test_missing_function_reported(self):
        src = "x = 1"
        file_plan = {
            "functions": [{"name": "handle_search", "signature": "...", "docstring": "..."}],
            "classes": [],
        }
        mismatches = _check_python_file("src/server.py", file_plan, src)
        assert len(mismatches) == 1
        assert mismatches[0]["kind"] == "function"
        assert mismatches[0]["name"] == "handle_search"
        assert mismatches[0]["file"] == "src/server.py"

    def test_missing_class_reported(self):
        src = "def foo(): pass"
        file_plan = {
            "functions": [],
            "classes": [
                {
                    "name": "MissingClass",
                    "bases": [],
                    "docstring": "...",
                    "methods": [],
                }
            ],
        }
        mismatches = _check_python_file("src/models.py", file_plan, src)
        assert any(m["kind"] == "class" and m["name"] == "MissingClass" for m in mismatches)

    def test_missing_method_reported(self):
        src = textwrap.dedent("""\
            class MyClient:
                def connect(self): pass
        """)
        file_plan = {
            "functions": [],
            "classes": [
                {
                    "name": "MyClient",
                    "bases": [],
                    "docstring": "...",
                    "methods": [
                        {"name": "connect", "signature": "...", "docstring": "..."},
                        {"name": "disconnect", "signature": "...", "docstring": "..."},
                    ],
                }
            ],
        }
        mismatches = _check_python_file("src/client.py", file_plan, src)
        assert any(m["kind"] == "method" and m["name"] == "disconnect" for m in mismatches)
        assert not any(m["name"] == "connect" for m in mismatches)

    def test_missing_class_skips_its_methods(self):
        src = "x = 1"
        file_plan = {
            "functions": [],
            "classes": [
                {
                    "name": "Ghost",
                    "bases": [],
                    "docstring": "...",
                    "methods": [
                        {"name": "method_a", "signature": "...", "docstring": "..."},
                        {"name": "method_b", "signature": "...", "docstring": "..."},
                    ],
                }
            ],
        }
        mismatches = _check_python_file("src/ghost.py", file_plan, src)
        # Only the class itself is reported, not each method separately
        assert len(mismatches) == 1
        assert mismatches[0]["kind"] == "class"

    def test_extra_functions_not_flagged(self):
        src = textwrap.dedent("""\
            def planned(): pass
            def extra_bonus(): pass
        """)
        file_plan = {
            "functions": [{"name": "planned", "signature": "...", "docstring": "..."}],
            "classes": [],
        }
        mismatches = _check_python_file("src/utils.py", file_plan, src)
        assert mismatches == []


# ---------------------------------------------------------------------------
# validate (full integration)
# ---------------------------------------------------------------------------

class TestValidate:
    def _make_plan(self, files: list[str], functions: dict | None = None) -> dict:
        file_plans = {}
        for f in files:
            file_plans[f] = {
                "description": "test",
                "imports": [],
                "constants": [],
                "classes": [],
                "functions": [
                    {"name": fn, "signature": "...", "docstring": "..."}
                    for fn in (functions or {}).get(f, [])
                ],
                "notes": "",
            }
        return {"file_plans": file_plans, "entry_point": "", "test_strategy": ""}

    def test_all_files_present_passes(self):
        plan = self._make_plan(["src/server.py"])
        contents = {"src/server.py": "x = 1"}
        result = validate(plan, contents)
        assert result["passed"] is True
        assert result["missing_files"] == []

    def test_missing_file_fails(self):
        plan = self._make_plan(["src/server.py", "src/search.py"])
        contents = {"src/server.py": "x = 1"}
        result = validate(plan, contents)
        assert result["passed"] is False
        assert "src/search.py" in result["missing_files"]

    def test_missing_function_fails(self):
        plan = self._make_plan(["src/server.py"], functions={"src/server.py": ["handle_search"]})
        contents = {"src/server.py": "x = 1"}
        result = validate(plan, contents)
        assert result["passed"] is False
        assert any("handle_search" in v for v in result["violations"])

    def test_non_python_file_only_existence_checked(self):
        plan = self._make_plan(["requirements.txt", "Dockerfile"])
        contents = {
            "requirements.txt": "fastapi\nuvicorn\n",
            "Dockerfile": "FROM python:3.12\n",
        }
        result = validate(plan, contents)
        assert result["passed"] is True

    def test_empty_plan_spec_passes(self):
        result = validate({}, {"src/server.py": "x = 1"})
        assert result["passed"] is True

    def test_violations_are_human_readable(self):
        plan = self._make_plan(["src/missing.py", "src/present.py"], functions={"src/present.py": ["gone_fn"]})
        contents = {"src/present.py": "x = 1"}
        result = validate(plan, contents)
        assert any("MISSING FILE" in v for v in result["violations"])
        assert any("MISSING FUNCTION" in v and "gone_fn" in v for v in result["violations"])

    def test_function_present_passes(self):
        plan = self._make_plan(["src/utils.py"], functions={"src/utils.py": ["compute"]})
        contents = {"src/utils.py": "def compute(x): return x * 2"}
        result = validate(plan, contents)
        assert result["passed"] is True
        assert result["signature_mismatches"] == []


# ---------------------------------------------------------------------------
# should_revise_plan / build_revision_note
# ---------------------------------------------------------------------------

class TestRevisionHelpers:
    def test_no_violations_no_revision(self):
        assert should_revise_plan(3, []) is False

    def test_below_threshold_no_revision(self):
        assert should_revise_plan(1, ["MISSING FILE: x.py"]) is False

    def test_at_threshold_triggers_revision(self):
        assert should_revise_plan(2, ["MISSING FILE: x.py"]) is True

    def test_above_threshold_triggers_revision(self):
        assert should_revise_plan(5, ["MISSING FUNCTION: foo() in bar.py"]) is True

    def test_custom_threshold(self):
        assert should_revise_plan(1, ["v"], revision_threshold=1) is True
        assert should_revise_plan(0, ["v"], revision_threshold=1) is False

    def test_revision_note_contains_violations(self):
        violations = ["MISSING FILE: src/models.py", "MISSING FUNCTION: run() in src/main.py"]
        note = build_revision_note(violations)
        assert "src/models.py" in note
        assert "run()" in note

    def test_revision_note_truncates_long_lists(self):
        violations = [f"MISSING FUNCTION: fn_{i}() in src/x.py" for i in range(20)]
        note = build_revision_note(violations)
        assert "more" in note
