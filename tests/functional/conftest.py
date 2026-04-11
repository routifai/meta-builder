"""
Session-scoped pipeline fixture for functional tests.

Runs the full implemented pipeline exactly ONCE per pytest session.
All functional test modules share this one expensive result.

The pipeline under test:
    prompt_parser → ambiguity_scorer → defaults_agent → researcher

Goal used: "build an agent capable of deep research and deploy to fly.io"
This goal is intentionally slightly vague on build_target to exercise real parser behavior.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv()

FUNCTIONAL_GOAL = "build an agent capable of deep research and deploy to fly.io"


@pytest.fixture(scope="session")
def pipeline_run(tmp_path_factory):
    """
    Run the intent block + researcher once per session. Returns a dict with:
      - goal: str
      - parsed: ParsedGoal
      - scored: ScoredUnknowns
      - spec: IntentSpec  (None if HumanInputRequired was raised)
      - human_input_required: list[str]  (non-empty if spec is None)
      - research: ResearchResult  (None if spec is None or researcher failed)
      - skills_dir: Path  (where skill files were written)
      - error: Exception | None
    """
    from agent.intent.prompt_parser import parse_prompt
    from agent.intent.ambiguity_scorer import score_unknowns
    from agent.intent.defaults_agent import fill_defaults, HumanInputRequired
    from agent.mesh.researcher import run as researcher_run

    tmp = tmp_path_factory.mktemp("functional_run")
    skills_dir = tmp / "skills"
    skills_dir.mkdir()

    result: dict = {
        "goal": FUNCTIONAL_GOAL,
        "parsed": None,
        "scored": None,
        "spec": None,
        "human_input_required": [],
        "research": None,
        "skills_dir": skills_dir,
        "error": None,
    }

    try:
        result["parsed"] = parse_prompt(FUNCTIONAL_GOAL)
        result["scored"] = score_unknowns(result["parsed"])

        try:
            result["spec"] = fill_defaults(result["scored"], result["parsed"])
        except HumanInputRequired as exc:
            result["human_input_required"] = exc.fields
            return result

        result["research"] = asyncio.run(
            researcher_run(result["spec"], skills_dir=str(skills_dir))
        )

    except Exception as exc:
        result["error"] = exc
        raise

    return result
