"""
Anomaly classifier — Block 4, persistent Fly.io worker.

Input:  anomaly_event dict (from Redis pub/sub)
Output: ClassifiedAnomaly
  {
    "type": "bug" | "config" | "infra" | "regression",
    "priority": "critical" | "high" | "medium" | "low",
    "run_id": str,
    "source_event": dict,
  }
"""
from __future__ import annotations

from typing import Literal, TypedDict


class ClassifiedAnomaly(TypedDict):
    type: Literal["bug", "config", "infra", "regression"]
    priority: Literal["critical", "high", "medium", "low"]
    run_id: str
    source_event: dict


async def classify(anomaly_event: dict) -> ClassifiedAnomaly:
    """Label anomaly type and set fix priority."""
    raise NotImplementedError
