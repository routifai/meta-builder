"""
Smoke runner — runs all implemented pipeline stages against a real goal.
Shows exactly what each agent produced so you can see real end-to-end behavior.

Usage:
    python scripts/smoke.py "build an agent capable of deep research"
    python scripts/smoke.py "build an MCP server for Perplexity search and deploy to fly.io"

Writes everything to  runs/<run_id>/  — never touches the main skills/ store.
Exits 0 in all cases — HumanInputRequired and NotImplementedError are informative, not errors.

Implemented stages (auto-detected):
    [1] prompt_parser
    [2] ambiguity_scorer
    [3] defaults_agent
    [4] researcher  ──┐  concurrent
    [5] architect   ──┘
    [6] coder            (stub — stops here when not yet implemented)
    ...
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

DEFAULT_GOAL = "build an MCP server for Perplexity search and deploy to fly.io"
DIVIDER = "─" * 60


# ---------------------------------------------------------------------------
# Printing helpers
# ---------------------------------------------------------------------------

def _elapsed(t0: float) -> str:
    return f"{time.perf_counter() - t0:.2f}s"


def _print_stage(name: str, output: dict, elapsed_str: str) -> None:
    print(f"\n{DIVIDER}")
    print(f"  STAGE: {name}  ({elapsed_str})")
    print(DIVIDER)
    print(json.dumps(output, indent=2, default=str))


def _print_banner(goal: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  meta-builder smoke run")
    print(f"  goal: {goal!r}")
    print(f"{'=' * 60}")


def _print_stop(reason: str) -> None:
    print(f"\n{DIVIDER}")
    print(f"  PIPELINE STOPPED: {reason}")
    print(DIVIDER)


def _print_skill_files(skills_dir: str, skills_written: list[str]) -> None:
    print(f"\n{DIVIDER}")
    print("  SKILL FILES WRITTEN")
    print(DIVIDER)
    for rel_path in skills_written:
        full_path = Path(skills_dir) / Path(rel_path).name
        if full_path.exists():
            content = full_path.read_text()
            lines = content.splitlines()
            print(f"\n  ── {Path(rel_path).name} ({len(content)} chars) ──")
            for line in lines[:15]:
                print(f"  {line}")
            if len(lines) > 15:
                print(f"  ... ({len(lines) - 15} more lines)")


def _print_remaining(next_stage_idx: int) -> None:
    all_stages = [
        "prompt_parser", "ambiguity_scorer", "defaults_agent",
        "researcher + architect (concurrent)",
        "coder", "tester", "deployer", "monitor_setup",
        "signal_collector", "scorer", "router",
        "log_watcher", "anomaly_classifier", "context_builder",
        "fix_agent", "validator", "skills_updater",
    ]
    remaining = all_stages[next_stage_idx:]
    if remaining:
        print(f"\n{DIVIDER}")
        print("  REMAINING (not yet implemented)")
        print(DIVIDER)
        for i, name in enumerate(remaining, start=next_stage_idx + 1):
            print(f"  [{i}] {name}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def main(goal: str) -> None:
    from agent.intent.prompt_parser import parse_prompt
    from agent.intent.ambiguity_scorer import score_unknowns
    from agent.intent.defaults_agent import fill_defaults, HumanInputRequired
    from agent.mesh.researcher import run as researcher_run
    from agent.mesh.architect import run as architect_run

    _print_banner(goal)

    # ── Stage 1: prompt_parser ─────────────────────────────────────────
    print("\n[1] prompt_parser — extracting entities...")
    t0 = time.perf_counter()
    try:
        parsed = parse_prompt(goal)
    except Exception as exc:
        _print_stop(f"prompt_parser: {type(exc).__name__}: {exc}")
        return
    _print_stage("prompt_parser", parsed, _elapsed(t0))

    # ── Stage 2: ambiguity_scorer ──────────────────────────────────────
    print("\n[2] ambiguity_scorer — scoring unknown fields...")
    t0 = time.perf_counter()
    scored = score_unknowns(parsed)
    _print_stage("ambiguity_scorer", scored, _elapsed(t0))

    if scored["must_ask"]:
        _print_stop(
            f"HumanInputRequired — parser could not determine: {scored['must_ask']}\n"
            f"  Retry with a more specific goal, e.g. add the missing fields explicitly."
        )
        return

    # ── Stage 3: defaults_agent ────────────────────────────────────────
    print("\n[3] defaults_agent — filling defaults + run_id...")
    t0 = time.perf_counter()
    try:
        spec = fill_defaults(scored, parsed)
    except HumanInputRequired as exc:
        _print_stop(f"HumanInputRequired: {exc.fields}")
        return
    except Exception as exc:
        _print_stop(f"defaults_agent: {type(exc).__name__}: {exc}")
        return
    _print_stage("defaults_agent → intent_spec", spec, _elapsed(t0))

    # ── Stages 4+5: researcher ‖ architect (concurrent) ────────────────
    run_id = spec["run_id"]
    smoke_dir = Path("runs") / run_id
    smoke_skills_dir = str(smoke_dir / "skills")
    Path(smoke_skills_dir).mkdir(parents=True, exist_ok=True)

    print(f"\n[4+5] researcher ‖ architect — running concurrently...")
    print(f"      skills → {smoke_skills_dir}")
    t0 = time.perf_counter()
    try:
        research, architecture = await asyncio.gather(
            researcher_run(spec, skills_dir=smoke_skills_dir),
            architect_run(spec, {}, skills_dir=smoke_skills_dir),
        )
    except NotImplementedError as exc:
        _print_stop(f"researcher or architect not implemented: {exc}")
        _print_remaining(3)
        return
    except Exception as exc:
        _print_stop(f"researcher/architect: {type(exc).__name__}: {exc}")
        raise
    elapsed_both = _elapsed(t0)

    _print_stage("researcher", research, elapsed_both)
    _print_skill_files(smoke_skills_dir, research.get("skills_written", []))
    _print_stage("architect", architecture, elapsed_both)

    # ── Stage 6+: coder (and beyond) ──────────────────────────────────
    # Detect whether coder is implemented by attempting to import and call it
    try:
        from agent.mesh.coder import run as coder_run
        print(f"\n[6] coder — generating code from architecture...")
        t0 = time.perf_counter()
        coder_result = await coder_run(architecture, spec)
        _print_stage("coder", coder_result, _elapsed(t0))
        next_idx = 5
    except NotImplementedError:
        _print_stop("coder: not yet implemented")
        _print_remaining(4)
        _print_summary(run_id, smoke_skills_dir, research, architecture, spec)
        return
    except Exception as exc:
        _print_stop(f"coder: {type(exc).__name__}: {exc}")
        raise

    # (tester, deployer, etc. would follow the same pattern)
    _print_remaining(next_idx)
    _print_summary(run_id, smoke_skills_dir, research, architecture, spec)


def _print_summary(
    run_id: str,
    smoke_skills_dir: str,
    research: dict,
    architecture: dict,
    spec: dict,
) -> None:
    print(f"\n{'=' * 60}")
    print("  SMOKE RUN SUMMARY")
    print(f"{'=' * 60}")
    print(f"  Run ID       : {run_id}")
    print(f"  Build target : {spec.get('build_target')}")
    print(f"  Deploy target: {spec.get('deploy_target')}")
    print(f"  Skills dir   : {smoke_skills_dir}/")
    print(f"\n  Recommended stack:")
    for domain, tool in research.get("recommended_stack", {}).items():
        print(f"    {domain:25s} → {tool}")
    print(f"\n  Architecture file_tree ({len(architecture.get('file_tree', []))} files):")
    for f in architecture.get("file_tree", []):
        print(f"    {f}")
    print(f"\n  Tech choices:")
    for component, tech in architecture.get("tech_choices", {}).items():
        print(f"    {component:25s} → {tech}")
    print()


if __name__ == "__main__":
    goal = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GOAL
    asyncio.run(main(goal))
