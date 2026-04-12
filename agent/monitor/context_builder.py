"""
Context builder — Block 4.

Input:  classified_anomaly: ClassifiedAnomaly
Output: FixContext
  {
    "stack_trace": str,
    "relevant_skills": list[str],   # content of matching skills/ entries
    "relevant_files": list[str],    # source files likely involved
    "run_id": str,
    "anomaly": dict,
  }

Pulls stack trace, reads relevant skills/ entries,
packages everything for the fix agent.
"""
from __future__ import annotations

from typing import TypedDict


class FixContext(TypedDict):
    stack_trace: str
    relevant_skills: list[str]
    relevant_files: list[str]
    run_id: str
    anomaly: dict


async def build(classified_anomaly: dict) -> FixContext:
    """Package stack trace + skills context for fix agent."""
    raise NotImplementedError
