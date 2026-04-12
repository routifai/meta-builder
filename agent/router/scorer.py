"""
Scorer — Block 3, Agent 2.

Input:  signal_bundle: SignalBundle
Output: ScoreResult
  {
    "confidence": float,      # 0-100
    "risk_dimensions": dict,  # {dimension: severity}
    "breakdown": dict,        # {signal: weighted_contribution}
  }

Weights each signal, computes 0-100 confidence, tags risk dimensions.
"""
from __future__ import annotations

from typing import TypedDict

AUTO_MERGE_THRESHOLD = 85.0


class ScoreResult(TypedDict):
    confidence: float
    risk_dimensions: dict[str, str]
    breakdown: dict[str, float]


def score(signal_bundle: dict) -> ScoreResult:
    """Weight signals, compute confidence score 0-100, tag risk dimensions."""
    raise NotImplementedError
