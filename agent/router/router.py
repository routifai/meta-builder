"""
Router — Block 3, Agent 3.

Input:  score_result: ScoreResult, intent_spec: IntentSpec
Output: RouterDecision
  {
    "action": "auto_merge" | "async_ping" | "hold",
    "reason": str,
    "pr_merged": bool,
    "notification_sent": bool,
  }

score >= AUTO_MERGE_THRESHOLD + auto_merge_enabled -> auto-merge and notify after.
score < threshold -> async ping to human (non-blocking).
Never blocks the pipeline.
"""
from __future__ import annotations

from typing import Literal, TypedDict

from agent.router.scorer import AUTO_MERGE_THRESHOLD


class RouterDecision(TypedDict):
    action: Literal["auto_merge", "async_ping", "hold"]
    reason: str
    pr_merged: bool
    notification_sent: bool


async def route(score_result: dict, intent_spec: dict) -> RouterDecision:
    """Route to auto-merge or async human ping based on confidence score."""
    raise NotImplementedError
