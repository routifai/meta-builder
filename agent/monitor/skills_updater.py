"""
Skills updater — Block 4.

Input:  fix_result: FixResult, classified_anomaly: ClassifiedAnomaly
Output: SkillsUpdateResult
  {
    "skills_updated": list[str],    # paths of skills/ files modified
    "new_entries": list[str],       # new gotchas/patterns appended
  }

Writes fix and new learnings back to skills/ after a successful fix.
skills/ is append-only during a run — never deletes existing entries.
"""
from __future__ import annotations

from typing import TypedDict


class SkillsUpdateResult(TypedDict):
    skills_updated: list[str]
    new_entries: list[str]


async def update(fix_result: dict, classified_anomaly: dict) -> SkillsUpdateResult:
    """Append fix learnings to relevant skills/ files."""
    raise NotImplementedError
