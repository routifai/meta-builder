"""
Defaults agent — Block 1, Agent 3.

Input:  scored_unknowns: ScoredUnknowns, parsed_goal: ParsedGoal
Output: IntentSpec (fully populated, ready for mesh)

Fills all can_default fields with industry best practices.
Raises HumanInputRequired if any must_ask fields remain unfilled.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TypedDict

from agent.shared.intent_spec import DEFAULTS, IntentSpec, validate


class HumanInputRequired(Exception):
    """Raised when a field cannot be defaulted and human input is needed."""

    def __init__(self, fields: list[str]):
        self.fields = fields
        super().__init__(f"Human input required for: {fields}")


def fill_defaults(scored_unknowns: dict, parsed_goal: dict) -> IntentSpec:
    """
    Resolve defaults for all can_default fields.
    Raises HumanInputRequired if any must_ask fields remain unfilled.

    Args:
        scored_unknowns: output of ambiguity_scorer.score_unknowns()
        parsed_goal:     output of prompt_parser.parse_prompt()
    """
    must_ask: list[str] = scored_unknowns.get("must_ask", [])
    if must_ask:
        raise HumanInputRequired(must_ask)

    entities: dict = parsed_goal.get("entities", {})

    # Start from defaults, then layer in everything we know from the parsed goal
    spec: dict = {
        **DEFAULTS,
        "raw_goal":    parsed_goal.get("raw_goal", ""),
        "build_target": entities.get("build_target") or "",
        "integrations": entities.get("integrations") or [],
        "deploy_target": entities.get("deploy_target") or DEFAULTS.get("deploy_target", "fly.io"),
        "run_id":      str(uuid.uuid4()),
        "created_at":  datetime.now(timezone.utc).isoformat(),
    }

    # deploy_target has no entry in DEFAULTS — set the system default here
    if not spec.get("deploy_target"):
        spec["deploy_target"] = "fly.io"

    return validate(spec)
