"""
Session-scoped pipeline fixtures for functional tests.

Two fixtures, each runs once per pytest session:

  pipeline_run     — "build an agent capable of deep research and deploy to fly.io"
                     Exercises: vague build_target, no integrations, deploy target defaulted.

  pipeline_run_mcp — "build an MCP server for Perplexity search and deploy to fly.io"
                     Exercises: known build_target, explicit integration, all fields resolved.

All functional test modules share these — expensive API calls happen exactly once.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv()

FUNCTIONAL_GOAL = "build an agent capable of deep research and deploy to fly.io"
FUNCTIONAL_GOAL_MCP = "build an MCP server for Perplexity search and deploy to fly.io"


def _run_pipeline(goal: str, skills_dir: Path) -> dict:
    """Shared pipeline execution — intent block + researcher + architect."""
    from agent.intent.prompt_parser import parse_prompt
    from agent.intent.ambiguity_scorer import score_unknowns
    from agent.intent.defaults_agent import fill_defaults, HumanInputRequired
    from agent.mesh.researcher import run as researcher_run
    from agent.mesh.architect import run as architect_run

    result: dict = {
        "goal": goal,
        "parsed": None,
        "scored": None,
        "spec": None,
        "human_input_required": [],
        "research": None,
        "architecture": None,
        "skills_dir": skills_dir,
        "error": None,
    }

    async def _async_pipeline():
        result["parsed"] = parse_prompt(goal)
        result["scored"] = score_unknowns(result["parsed"])

        try:
            result["spec"] = fill_defaults(result["scored"], result["parsed"])
        except HumanInputRequired as exc:
            result["human_input_required"] = exc.fields
            return

        # Researcher and architect run concurrently — same as production mesh block
        research, arch = await asyncio.gather(
            researcher_run(result["spec"], skills_dir=str(skills_dir)),
            architect_run(result["spec"], {}, skills_dir=str(skills_dir)),
        )
        result["research"] = research
        result["architecture"] = arch

    try:
        asyncio.run(_async_pipeline())
    except Exception as exc:
        result["error"] = exc
        raise

    return result


@pytest.fixture(scope="session")
def pipeline_run(tmp_path_factory):
    """Run the deep-research goal pipeline once per session."""
    tmp = tmp_path_factory.mktemp("functional_run")
    skills_dir = tmp / "skills"
    skills_dir.mkdir()
    return _run_pipeline(FUNCTIONAL_GOAL, skills_dir)


@pytest.fixture(scope="session")
def pipeline_run_mcp(tmp_path_factory):
    """Run the MCP/Perplexity goal pipeline once per session."""
    tmp = tmp_path_factory.mktemp("functional_run_mcp")
    skills_dir = tmp / "skills"
    skills_dir.mkdir()
    return _run_pipeline(FUNCTIONAL_GOAL_MCP, skills_dir)
