"""
Intent spec — schema + validation.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypedDict

INTENT_SPEC_PATH = Path(".agent/intent-spec.json")

VALID_RISK_TOLERANCES = ("lean", "stable")
VALID_NOTIFICATION_PREFS = ("blocked_only", "async", "never")


class IntentSpec(TypedDict):
    raw_goal: str
    build_target: str
    integrations: list[str]
    deploy_target: str
    llm_provider: str
    llm_model: str
    llm_base_url: str | None
    risk_tolerance: Literal["lean", "stable"]
    auto_merge_if_ci_green: bool
    notification_preference: Literal["blocked_only", "async", "never"]
    run_id: str
    created_at: str


REQUIRED_FIELDS = {
    "raw_goal", "build_target", "integrations", "deploy_target",
    "llm_provider", "llm_model", "risk_tolerance",
    "auto_merge_if_ci_green", "notification_preference",
    "run_id", "created_at",
}

DEFAULTS = {
    "llm_provider": "anthropic",
    "llm_model": "claude-sonnet-4-6",
    "llm_base_url": None,
    "risk_tolerance": "stable",
    "auto_merge_if_ci_green": True,
    "notification_preference": "async",
}


def validate(spec: dict) -> IntentSpec:
    """Validate a raw dict. Apply defaults for optional fields. Raise ValueError on violations."""
    # Apply defaults for optional fields before validation
    merged = {**DEFAULTS, **spec}

    # Check required fields
    for field in REQUIRED_FIELDS:
        if field not in merged or merged[field] is None and field not in ("llm_base_url",):
            if field == "llm_base_url":
                continue
            if merged.get(field) is None and field not in DEFAULTS:
                raise ValueError(f"Missing required field: {field!r}")
            if field not in merged:
                raise ValueError(f"Missing required field: {field!r}")

    # Re-check more carefully: required fields must be present AND non-None (except llm_base_url)
    for field in REQUIRED_FIELDS:
        if field == "llm_base_url":
            continue
        val = merged.get(field)
        if val is None:
            raise ValueError(f"Missing required field: {field!r}")
        if isinstance(val, str) and val.strip() == "" and field == "raw_goal":
            raise ValueError(f"Field {field!r} must not be empty")

    # Validate enum fields
    if merged["risk_tolerance"] not in VALID_RISK_TOLERANCES:
        raise ValueError(
            f"Invalid risk_tolerance {merged['risk_tolerance']!r}. "
            f"Must be one of: {VALID_RISK_TOLERANCES}"
        )
    if merged["notification_preference"] not in VALID_NOTIFICATION_PREFS:
        raise ValueError(
            f"Invalid notification_preference {merged['notification_preference']!r}. "
            f"Must be one of: {VALID_NOTIFICATION_PREFS}"
        )

    # Ensure integrations is a list
    if not isinstance(merged.get("integrations", []), list):
        raise ValueError("Field 'integrations' must be a list")

    return IntentSpec(
        raw_goal=merged["raw_goal"],
        build_target=merged["build_target"],
        integrations=list(merged.get("integrations", [])),
        deploy_target=merged["deploy_target"],
        llm_provider=merged["llm_provider"],
        llm_model=merged["llm_model"],
        llm_base_url=merged.get("llm_base_url"),
        risk_tolerance=merged["risk_tolerance"],
        auto_merge_if_ci_green=bool(merged["auto_merge_if_ci_green"]),
        notification_preference=merged["notification_preference"],
        run_id=merged["run_id"],
        created_at=merged["created_at"],
    )


def load(path: Path = INTENT_SPEC_PATH) -> IntentSpec:
    """Load and validate intent spec from disk."""
    if not path.exists():
        raise FileNotFoundError(f"Intent spec not found: {path}")
    raw = json.loads(path.read_text())
    return validate(raw)


def save(spec: IntentSpec, path: Path = INTENT_SPEC_PATH) -> None:
    """Write validated intent spec to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(spec), indent=2))
