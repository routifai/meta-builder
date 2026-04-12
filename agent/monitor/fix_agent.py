"""
Fix agent — Block 4.

Input:  fix_context: FixContext
Output: FixResult
  {
    "branch_name": str,
    "pr_url": str,
    "files_changed": list[str],
    "patch_summary": str,
    "decision_log_path": str,   # written before any irreversible action
  }

Reads context package, writes targeted patch, opens branch and PR.
Writes to decision-log/ BEFORE opening the PR (irreversible action).
"""
from __future__ import annotations

from typing import TypedDict


class FixResult(TypedDict):
    branch_name: str
    pr_url: str
    files_changed: list[str]
    patch_summary: str
    decision_log_path: str


async def run(fix_context: dict) -> FixResult:
    """Write patch, log decision, open branch and PR."""
    raise NotImplementedError
