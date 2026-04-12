"""
PlanValidator — enforces that coder output matches the Planner's PlanSpec.

Runs after the coder loop exits. Violations feed back to the coder as a
targeted fix pass so the system self-corrects rather than silently drifting.

Two levels of checks:
  1. File presence  — every file in plan_spec.file_plans must exist in file_contents
  2. Symbol check   — for .py files, parse with ast and verify every function name
                      and class name (and method names) defined in the plan are
                      present in the written code

AST approach is intentionally forgiving:
  - We check names exist, not full signatures (type annotations can legitimately
    differ, especially for Optional / Union / generics)
  - We only fail on MISSING symbols, not on EXTRA symbols the coder added
  - Non-Python files (Dockerfile, requirements.txt, *.toml) get existence-only checks
"""
from __future__ import annotations

import ast
from typing import Literal, TypedDict


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class SignatureMismatch(TypedDict):
    file: str
    kind: Literal["function", "class", "method"]
    name: str
    parent: str   # class name for methods, "" for top-level


class ValidationResult(TypedDict):
    passed: bool
    missing_files: list[str]
    signature_mismatches: list[SignatureMismatch]
    violations: list[str]   # human-readable lines for coder feedback


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _parse_symbols(source: str) -> tuple[set[str], dict[str, set[str]]]:
    """
    Parse Python source and return:
      top_level_names  — set of top-level function + async function names
      class_methods    — {class_name: set of method names}
    Returns empty sets if source cannot be parsed.
    """
    top_level: set[str] = set()
    class_methods: dict[str, set[str]] = {}

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return top_level, class_methods

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            top_level.add(node.name)
        elif isinstance(node, ast.ClassDef):
            methods: set[str] = set()
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.add(child.name)
            class_methods[node.name] = methods

    return top_level, class_methods


# ---------------------------------------------------------------------------
# Core validation logic
# ---------------------------------------------------------------------------

def _check_python_file(
    path: str,
    file_plan: dict,
    source: str,
) -> list[SignatureMismatch]:
    """Check that all planned symbols exist in the written Python source."""
    mismatches: list[SignatureMismatch] = []
    top_level, class_methods = _parse_symbols(source)

    # Check top-level functions
    for fn in file_plan.get("functions", []):
        name = fn.get("name", "")
        if not name:
            continue
        if name not in top_level:
            mismatches.append(
                SignatureMismatch(file=path, kind="function", name=name, parent="")
            )

    # Check classes and their methods
    for cls in file_plan.get("classes", []):
        cls_name = cls.get("name", "")
        if not cls_name:
            continue
        if cls_name not in class_methods:
            mismatches.append(
                SignatureMismatch(file=path, kind="class", name=cls_name, parent="")
            )
            # If class is missing, its methods are trivially missing too — skip
            continue
        for method in cls.get("methods", []):
            m_name = method.get("name", "")
            if not m_name:
                continue
            if m_name not in class_methods[cls_name]:
                mismatches.append(
                    SignatureMismatch(
                        file=path, kind="method", name=m_name, parent=cls_name
                    )
                )

    return mismatches


def validate(
    plan_spec: dict,
    file_contents: dict[str, str],
) -> ValidationResult:
    """
    Validate coder output against the PlanSpec.

    Args:
        plan_spec:     PlanSpec from the planner agent (ctx.plan_spec)
        file_contents: Written file contents keyed by relative path (ctx.file_contents)

    Returns:
        ValidationResult with passed=True only when all files exist and all
        planned symbols are present in the Python files.
    """
    if not plan_spec:
        return ValidationResult(
            passed=True,
            missing_files=[],
            signature_mismatches=[],
            violations=[],
        )

    file_plans: dict[str, dict] = plan_spec.get("file_plans", {})
    missing_files: list[str] = []
    all_mismatches: list[SignatureMismatch] = []

    for path, file_plan in file_plans.items():
        if path not in file_contents:
            missing_files.append(path)
            continue

        # Only do symbol checks on Python source files
        if path.endswith(".py"):
            source = file_contents[path]
            mismatches = _check_python_file(path, file_plan, source)
            all_mismatches.extend(mismatches)

    # Build human-readable violation lines for coder feedback
    violations: list[str] = []
    for f in missing_files:
        violations.append(f"MISSING FILE: {f} (required by plan)")
    for m in all_mismatches:
        if m["kind"] == "method":
            violations.append(
                f"MISSING METHOD: {m['parent']}.{m['name']}() in {m['file']}"
            )
        elif m["kind"] == "class":
            violations.append(f"MISSING CLASS: {m['name']} in {m['file']}")
        else:
            violations.append(f"MISSING FUNCTION: {m['name']}() in {m['file']}")

    passed = not missing_files and not all_mismatches

    return ValidationResult(
        passed=passed,
        missing_files=missing_files,
        signature_mismatches=all_mismatches,
        violations=violations,
    )


# ---------------------------------------------------------------------------
# Planner revision trigger
# ---------------------------------------------------------------------------

def should_revise_plan(
    coder_rounds_since_validation: int,
    plan_violations: list[str],
    revision_threshold: int = 2,
) -> bool:
    """
    Return True when the coder has failed to satisfy the plan enough times
    that re-running the planner with additional context is worth attempting.

    The threshold is intentionally conservative: we only revise when the coder
    has had multiple passes and the same violations persist.
    """
    return bool(plan_violations) and coder_rounds_since_validation >= revision_threshold


def build_revision_note(violations: list[str]) -> str:
    """
    Produce a note for the planner's re-run explaining what went wrong.
    Injected as additional context so the planner can adjust.
    """
    lines = [
        "Previous plan caused coder failures. Violations that persisted:",
        *[f"  - {v}" for v in violations[:10]],
    ]
    if len(violations) > 10:
        lines.append(f"  ... and {len(violations) - 10} more")
    lines.append(
        "\nRevise the plan to be simpler or split responsibilities differently."
    )
    return "\n".join(lines)
