"""
Smoke runner — runs the implemented pipeline stages against a real goal.

Usage:
    python scripts/smoke.py "build an agent capable of deep research"
    python scripts/smoke.py "build an MCP server for Perplexity search and deploy to fly.io"

Writes research output to  runs/<run_id>/skills/  (never touches the main skills/ store).
Exits 0 in all cases — HumanInputRequired and NotImplementedError are expected, not errors.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Ensure the project root is on sys.path when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

DEFAULT_GOAL = "build an MCP server for Perplexity search and deploy to fly.io"

DIVIDER = "─" * 60


def _elapsed(t0: float) -> str:
    return f"{time.perf_counter() - t0:.2f}s"


def _print_stage(name: str, output: dict, elapsed: str) -> None:
    print(f"\n{DIVIDER}")
    print(f"  STAGE: {name}  ({elapsed})")
    print(DIVIDER)
    print(json.dumps(output, indent=2, default=str))


def _print_banner(goal: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  meta-builder smoke run")
    print(f"  goal: {goal!r}")
    print(f"{'=' * 60}")


def _print_stop(reason: str) -> None:
    print(f"\n{DIVIDER}")
    print(f"  STOPPED: {reason}")
    print(DIVIDER)


async def main(goal: str) -> None:
    from agent.intent.prompt_parser import parse_prompt
    from agent.intent.ambiguity_scorer import score_unknowns
    from agent.intent.defaults_agent import fill_defaults, HumanInputRequired
    from agent.mesh.researcher import run as researcher_run

    _print_banner(goal)

    # ------------------------------------------------------------------
    # Stage 1 — prompt_parser
    # ------------------------------------------------------------------
    print("\n[1/4] prompt_parser — extracting entities from goal...")
    t0 = time.perf_counter()
    try:
        parsed = parse_prompt(goal)
    except Exception as exc:
        _print_stop(f"prompt_parser raised {type(exc).__name__}: {exc}")
        return
    _print_stage("prompt_parser", parsed, _elapsed(t0))

    # ------------------------------------------------------------------
    # Stage 2 — ambiguity_scorer
    # ------------------------------------------------------------------
    print("\n[2/4] ambiguity_scorer — scoring unknown fields...")
    t0 = time.perf_counter()
    try:
        scored = score_unknowns(parsed)
    except Exception as exc:
        _print_stop(f"ambiguity_scorer raised {type(exc).__name__}: {exc}")
        return
    _print_stage("ambiguity_scorer", scored, _elapsed(t0))

    if scored["must_ask"]:
        print(
            f"\n  ⚠  HumanInputRequired — parser could not determine: {scored['must_ask']}"
        )
        print("     The goal is too ambiguous. Try adding more specifics, e.g.:")
        print(f'     python scripts/smoke.py "{goal} using a python-library and deploy to fly.io"')
        return

    # ------------------------------------------------------------------
    # Stage 3 — defaults_agent
    # ------------------------------------------------------------------
    print("\n[3/4] defaults_agent — filling defaults and generating run_id...")
    t0 = time.perf_counter()
    try:
        spec = fill_defaults(scored, parsed)
    except HumanInputRequired as exc:
        _print_stop(
            f"HumanInputRequired — fields need clarification: {exc.fields}\n"
            "     Retry with a more specific goal."
        )
        return
    except Exception as exc:
        _print_stop(f"defaults_agent raised {type(exc).__name__}: {exc}")
        return
    _print_stage("defaults_agent (intent_spec)", spec, _elapsed(t0))

    # ------------------------------------------------------------------
    # Stage 4 — researcher
    # Writes to runs/<run_id>/skills/ — never pollutes the main skills/ store
    # ------------------------------------------------------------------
    run_id = spec["run_id"]
    smoke_skills_dir = str(Path("runs") / run_id / "skills")
    Path(smoke_skills_dir).mkdir(parents=True, exist_ok=True)

    print(f"\n[4/4] researcher — researching domains (skills → {smoke_skills_dir})...")
    t0 = time.perf_counter()
    try:
        research = await researcher_run(spec, skills_dir=smoke_skills_dir)
    except NotImplementedError:
        _print_stop("researcher: not yet implemented")
        return
    except Exception as exc:
        _print_stop(f"researcher raised {type(exc).__name__}: {exc}")
        raise
    _print_stage("researcher", research, _elapsed(t0))

    # ------------------------------------------------------------------
    # Show skill file contents
    # ------------------------------------------------------------------
    print(f"\n{DIVIDER}")
    print("  SKILL FILES WRITTEN")
    print(DIVIDER)
    for rel_path in research.get("skills_written", []):
        full_path = Path(smoke_skills_dir) / Path(rel_path).name
        if full_path.exists():
            content = full_path.read_text()
            print(f"\n  ── {rel_path} ({len(content)} chars) ──")
            # Print first 20 lines
            lines = content.splitlines()[:20]
            for line in lines:
                print(f"  {line}")
            if len(content.splitlines()) > 20:
                print(f"  ... ({len(content.splitlines()) - 20} more lines)")

    # ------------------------------------------------------------------
    # What's next
    # ------------------------------------------------------------------
    print(f"\n{DIVIDER}")
    print("  NEXT STAGES (not yet implemented)")
    print(DIVIDER)
    remaining = ["architect", "coder", "tester", "deployer", "monitor_setup",
                 "signal_collector", "scorer", "router"]
    for i, stage in enumerate(remaining, start=5):
        print(f"  [{i}] {stage}")

    print(f"\n  Run ID: {run_id}")
    print(f"  Skills written to: {smoke_skills_dir}/")
    print()


if __name__ == "__main__":
    goal = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GOAL
    asyncio.run(main(goal))
