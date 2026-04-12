"""
Decision log — append-only audit trail.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

DECISION_LOG_DIR = Path("decision-log")


class DecisionEntry(TypedDict):
    run_id: str
    agent: str
    timestamp: str
    action: str
    reasoning: str
    inputs_summary: str
    reversible: bool


def write(
    run_id: str,
    agent: str,
    action: str,
    reasoning: str,
    inputs_summary: str,
    reversible: bool = False,
) -> Path:
    """
    Append a decision log entry.
    Returns the path of the file written.
    Raises RuntimeError if reversible=False and the write fails.
    """
    entry: DecisionEntry = {
        "run_id": run_id,
        "agent": agent,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "reasoning": reasoning,
        "inputs_summary": inputs_summary,
        "reversible": reversible,
    }

    log_dir = DECISION_LOG_DIR / run_id / agent
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        # Use timestamp with microseconds to ensure uniqueness across rapid writes
        ts = entry["timestamp"].replace(":", "-").replace("+", "Z")
        path = log_dir / f"{ts}.json"
        path.write_text(json.dumps(entry, indent=2))
        return path
    except Exception as exc:
        if not reversible:
            raise RuntimeError(
                f"Failed to write decision log for irreversible action {action!r}: {exc}"
            ) from exc
        raise


def read_all(run_id: str) -> list[DecisionEntry]:
    """Read all decision log entries for a run, sorted by timestamp."""
    run_dir = DECISION_LOG_DIR / run_id
    if not run_dir.exists():
        return []

    entries: list[DecisionEntry] = []
    for path in run_dir.rglob("*.json"):
        try:
            entries.append(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError):
            continue

    return sorted(entries, key=lambda e: e["timestamp"])
