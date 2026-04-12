"""
Validator — Block 4.

Input:  fix_result: FixResult, run_id: str
Output: ValidationResult
  {
    "tests_passed": bool,
    "regressions_found": bool,
    "confidence": float,        # 0-100; must be > 85 for auto-merge
    "failures": list[dict],
  }

Runs tests on patch, checks for regressions, scores fix confidence.
Auto-merge is ONLY allowed if confidence > 85.
"""
from __future__ import annotations

from typing import TypedDict

FIX_MERGE_THRESHOLD = 85.0


class ValidationResult(TypedDict):
    tests_passed: bool
    regressions_found: bool
    confidence: float
    failures: list[dict]


async def validate(fix_result: dict, run_id: str) -> ValidationResult:
    """Run tests on patch; return confidence score."""
    raise NotImplementedError
