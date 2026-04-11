"""
Ambiguity scorer — Block 1, Agent 2.

Scores each unknown field: 0.0 = safe to default, 1.0 = must ask human.
Uses rule-based heuristics — no LLM call needed here. The scoring logic
is deterministic: unknown fields that have safe industry defaults score low,
fields where a wrong guess would be destructive score high.

Input:  parsed_goal: ParsedGoal
Output: ScoredUnknowns dict
  {
    "scores": {field_name: float},   # 0.0–1.0 per field
    "must_ask": list[str],           # fields scored >= MUST_ASK_THRESHOLD
    "can_default": list[str],        # fields scored <  MUST_ASK_THRESHOLD
  }
"""
from __future__ import annotations

from typing import TypedDict

MUST_ASK_THRESHOLD = 0.7

# Scores for fields that are absent or None.
# Rationale per field:
#   build_target   — missing means we can't build anything; must ask
#   deploy_target  — "prod" or absent is fine; default to fly.io (low risk)
#   integrations   — empty list is a valid state; safe to default to []
#   llm_model      — always has a safe default (claude-sonnet-4-6)
#   llm_provider   — always has a safe default (anthropic)
#   risk_tolerance — stable is the safe default
#   notification_preference — async is the safe default
#   auto_merge_if_ci_green  — True is the safe default
_FIELD_SCORES: dict[str, float] = {
    "build_target":              0.85,  # must ask — no safe default
    "deploy_target":             0.20,  # can default to fly.io
    "integrations":              0.10,  # empty list is valid
    "llm_model":                 0.05,
    "llm_provider":              0.05,
    "llm_base_url":              0.05,
    "risk_tolerance":            0.10,
    "notification_preference":   0.05,
    "auto_merge_if_ci_green":    0.05,
}


class ScoredUnknowns(TypedDict):
    scores: dict[str, float]
    must_ask: list[str]
    can_default: list[str]


def score_unknowns(parsed_goal: dict) -> ScoredUnknowns:
    """
    Score each unknown field from a ParsedGoal.

    Only fields listed in parsed_goal["unknown_fields"] and None-valued
    entities are scored. Known/filled fields are ignored.
    """
    if not isinstance(parsed_goal, dict):
        raise ValueError(f"parsed_goal must be a dict, got {type(parsed_goal)}")
    if "raw_goal" not in parsed_goal:
        raise ValueError("parsed_goal missing required key 'raw_goal'")

    unknown_fields: list[str] = parsed_goal.get("unknown_fields", [])
    entities: dict = parsed_goal.get("entities", {})

    # Collect all fields that need scoring:
    # 1. Explicitly flagged as unknown by the parser
    # 2. Entity values that are None (parser couldn't fill them)
    fields_to_score: set[str] = set(unknown_fields)
    for field, value in entities.items():
        if value is None or (isinstance(value, list) and len(value) == 0):
            fields_to_score.add(field)

    scores: dict[str, float] = {}
    for field in fields_to_score:
        scores[field] = _FIELD_SCORES.get(field, 0.5)

    must_ask = sorted(f for f, s in scores.items() if s >= MUST_ASK_THRESHOLD)
    can_default = sorted(f for f, s in scores.items() if s < MUST_ASK_THRESHOLD)

    return ScoredUnknowns(
        scores=scores,
        must_ask=must_ask,
        can_default=can_default,
    )
