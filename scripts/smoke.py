"""
Smoke runner — full pipeline against a real goal via orchestrator.run().

Shows exactly what each phase produced so you can see real end-to-end behavior.

Usage:
    python scripts/smoke.py "build an mcp that sends apple to mars"
    python scripts/smoke.py "build an MCP server for Perplexity search"

Pipeline phases (orchestrator):
    [1] prompt_parser
    [2] ambiguity_scorer
    [3] defaults_agent
    [1b] feasibility_critic   ← blocks impossible goals immediately
    [1c] requirement_closure  ← fills missing operational params
    [2]  researcher ‖ architect (concurrent)
    [2b] planner
    [2c] critic (plan)
    [3]  coder loop
    [3b] plan_validator
    [3c] critic (code)
    [4]  tester
    [4b] critic (tests)
    [5]  deployer
    [6]  monitor_setup
    [7]  signal_collector → scorer → router

Exits 0 in all cases — blocks and stubs are informative, not errors.
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
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _elapsed(t0: float) -> str:
    return f"{time.perf_counter() - t0:.2f}s"


def _ok(msg: str) -> str:
    return f"{GREEN}✓{RESET}  {msg}"


def _warn(msg: str) -> str:
    return f"{YELLOW}⚠{RESET}  {msg}"


def _err(msg: str) -> str:
    return f"{RED}✗{RESET}  {msg}"


def _block(msg: str) -> str:
    return f"{RED}{BOLD}BLOCKED{RESET}  {msg}"


def _section(title: str, elapsed: str = "") -> None:
    suffix = f"  ({elapsed})" if elapsed else ""
    print(f"\n{DIVIDER}")
    print(f"  {CYAN}{BOLD}{title}{RESET}{suffix}")
    print(DIVIDER)


def _dump(obj: dict, indent: int = 2) -> None:
    print(json.dumps(obj, indent=indent, default=str))


def _print_banner(goal: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {BOLD}meta-builder smoke run{RESET}")
    print(f"  goal: {CYAN}{goal!r}{RESET}")
    print(f"{'=' * 60}")


def _print_ctx_summary(ctx) -> None:
    _section("RUN SUMMARY")
    print(f"  Run ID          : {ctx.run_id}")
    print(f"  Phases hit      : {list(ctx.phase_timestamps.keys())}")
    print(f"  Critic rounds   : {ctx.critic_rounds}")
    print(f"  Coder rounds    : {ctx.coder_rounds}")
    print(f"  Tester rounds   : {ctx.tester_rounds}")
    print(f"  Files written   : {ctx.files_written}")
    print(f"  Tests written   : {ctx.tests_written}")
    print(f"  Smoke passed    : {ctx.smoke_tests_passed}")
    print(f"  Staging URL     : {ctx.staging_url}")
    if ctx.deploy_failure_reason:
        print(f"  Deploy failure  : {ctx.deploy_failure_reason}")
    print()


# ── Main ──────────────────────────────────────────────────────────────────────


async def main(goal: str) -> None:
    from agent.intent.prompt_parser import parse_prompt
    from agent.intent.ambiguity_scorer import score_unknowns
    from agent.intent.defaults_agent import fill_defaults, HumanInputRequired

    _print_banner(goal)

    # ── [1] prompt_parser ─────────────────────────────────────────────────────
    _section("[1] prompt_parser — extracting entities")
    t0 = time.perf_counter()
    try:
        parsed = parse_prompt(goal)
    except Exception as exc:
        print(_err(f"prompt_parser crashed: {type(exc).__name__}: {exc}"))
        return
    _dump(parsed)
    print(_ok(f"done {_elapsed(t0)}"))

    # ── [2] ambiguity_scorer ──────────────────────────────────────────────────
    _section("[2] ambiguity_scorer — scoring unknowns")
    t0 = time.perf_counter()
    scored = score_unknowns(parsed)
    _dump(scored)
    if scored["must_ask"]:
        print(_warn(f"must_ask fields: {scored['must_ask']}"))
        print(_warn("Continuing anyway — requirement_closure will handle gaps"))
    print(_ok(f"done {_elapsed(t0)}"))

    # ── [3] defaults_agent ────────────────────────────────────────────────────
    _section("[3] defaults_agent — filling defaults + run_id")
    t0 = time.perf_counter()
    try:
        spec = fill_defaults(scored, parsed)
    except HumanInputRequired as exc:
        print(_err(f"HumanInputRequired: {exc.fields}"))
        return
    except Exception as exc:
        print(_err(f"defaults_agent crashed: {type(exc).__name__}: {exc}"))
        return
    _dump(spec)
    print(_ok(f"done {_elapsed(t0)}"))

    # ── Orchestrator (phases 1b onwards) ──────────────────────────────────────
    _section("HANDING OFF TO ORCHESTRATOR")
    print(f"  run_id: {spec['run_id']}")

    run_id = spec["run_id"]
    output_dir = str(Path("runs") / run_id)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    t_orch = time.perf_counter()

    try:
        from agent.orchestrator import run as orchestrator_run
        ctx = await orchestrator_run(spec, output_dir=output_dir)
    except NotImplementedError as exc:
        # Expected when downstream agents are stubs — print what we got so far
        print(_warn(f"Pipeline reached a stub: {exc}"))
        _print_partial_results(exc, output_dir, run_id)
        return
    except Exception as exc:
        print(_err(f"Orchestrator crashed: {type(exc).__name__}: {exc}"))
        import traceback
        traceback.print_exc()
        return

    elapsed_orch = _elapsed(t_orch)
    print(_ok(f"Orchestrator returned in {elapsed_orch}"))

    # ── Print phase results ────────────────────────────────────────────────────

    # Phase 1b — feasibility
    if ctx.feasibility_result:
        _section("[1b] feasibility_critic result")
        _dump(ctx.feasibility_result)
        decision = ctx.feasibility_result.get("decision")
        if decision == "block":
            print(_block("Goal is not feasible. Pipeline halted."))
            if ctx.feasibility_result.get("suggestions"):
                print(f"\n  {BOLD}Alternative goals:{RESET}")
                for s in ctx.feasibility_result["suggestions"]:
                    print(f"    • {s}")
            _print_ctx_summary(ctx)
            return
        elif decision == "refine":
            print(_warn(f"Goal refined → {ctx.feasibility_result.get('refined_goal')}"))
        else:
            print(_ok("Feasibility: proceed"))

    # Phase 1c — closure
    if ctx.closure_result:
        _section("[1c] requirement_closure result")
        _dump(ctx.closure_result)
        if ctx.closure_result.get("status") == "needs_input":
            print(_warn("Pipeline needs more info from user:"))
            for q in ctx.closure_result.get("questions", []):
                print(f"    ? {q}")
            _print_ctx_summary(ctx)
            return
        if ctx.closure_result.get("auto_filled"):
            print(_ok(f"Auto-filled: {ctx.closure_result['auto_filled']}"))

    # Phase 2 — mesh
    if ctx.research_result or ctx.architecture_spec:
        _section("[2] researcher + architect")
        if ctx.research_result:
            print(f"\n  {BOLD}Research:{RESET}")
            stack = ctx.research_result.get("recommended_stack", {})
            for domain, tool in stack.items():
                print(f"    {domain:25s} → {tool}")
        if ctx.architecture_spec:
            print(f"\n  {BOLD}Architecture:{RESET}")
            for f in ctx.architecture_spec.get("file_tree", []):
                print(f"    {f}")
            for comp, tech in ctx.architecture_spec.get("tech_choices", {}).items():
                print(f"    {comp:25s} → {tech}")

    # Phase 2b — planner
    if ctx.plan_spec:
        _section("[2b] planner")
        file_plans = ctx.plan_spec.get("file_plans", {})
        print(f"  {len(file_plans)} file(s) planned:")
        for path, plan in file_plans.items():
            fns = [f["name"] for f in plan.get("functions", [])]
            cls = [c["name"] for c in plan.get("classes", [])]
            print(f"    {path}: functions={fns}, classes={cls}")

    # Phase 2c — critic plan
    if ctx.critic_plan_result:
        _section("[2c] critic — plan review")
        _dump(ctx.critic_plan_result)
        if ctx.critic_plan_result.get("decision") == "block":
            print(_block("Plan blocked. Pipeline halted."))
            _print_ctx_summary(ctx)
            return

    # Phase 3 — coder
    if ctx.files_written:
        _section("[3] coder output")
        print(f"  Files written ({len(ctx.files_written)}):")
        for f in ctx.files_written:
            print(f"    {f}")
        if ctx.lint_errors:
            print(_warn(f"Lint errors: {ctx.lint_errors}"))
        elif ctx.lint_passed:
            print(_ok("Lint passed"))
        if ctx.type_errors:
            print(_warn(f"Type errors: {ctx.type_errors}"))
        elif ctx.type_check_passed:
            print(_ok("Type check passed"))

    # Phase 3b — plan violations
    if ctx.plan_violations:
        _section("[3b] plan_validator violations")
        for v in ctx.plan_violations:
            print(f"    {_warn(v)}")

    # Phase 3c — critic code
    if ctx.critic_code_result:
        _section("[3c] critic — code review")
        _dump(ctx.critic_code_result)
        if ctx.critic_code_result.get("decision") == "block":
            print(_block("Code blocked. Pipeline halted."))
            _print_ctx_summary(ctx)
            return

    # Phase 4 — tester
    if ctx.tests_written:
        _section("[4] tester output")
        print(f"  Test files ({len(ctx.tests_written)}): {ctx.tests_written}")
        print(f"  Tests run: {ctx.tests_run}  passed: {ctx.tests_passed}  failed: {ctx.tests_failed}")
        if ctx.coverage_pct:
            print(f"  Coverage: {ctx.coverage_pct:.1f}%")

    # Phase 4b — critic tests
    if ctx.critic_test_result:
        _section("[4b] critic — test review")
        _dump(ctx.critic_test_result)
        if ctx.critic_test_result.get("decision") == "block":
            print(_block("Tests blocked. Pipeline halted."))
            _print_ctx_summary(ctx)
            return

    # Phase 5 — deployer
    _section("[5] deployer")
    if ctx.dockerfile_path:
        print(f"  Dockerfile: {ctx.dockerfile_path}")
    if ctx.staging_url:
        print(f"  Staging URL: {ctx.staging_url}")
    if ctx.smoke_tests_passed:
        print(_ok("Smoke tests PASSED — container is live"))
    elif ctx.deploy_failure_reason:
        print(_warn(f"Deploy: {ctx.deploy_failure_reason}"))

    _print_ctx_summary(ctx)


def _print_partial_results(exc: NotImplementedError, output_dir: str, run_id: str) -> None:
    """Print what we can from the orchestrator before it hit a stub."""
    _section("PARTIAL RESULTS")
    print(f"  Stopped at: {exc}")
    print(f"  Run output: {output_dir}/")

    # Show any workspace files that exist
    workspace = Path(output_dir) / "workspace"
    if workspace.exists():
        files = list(workspace.rglob("*"))
        if files:
            print(f"\n  Files in workspace ({len(files)}):")
            for f in files:
                if f.is_file():
                    print(f"    {f.relative_to(workspace)}")


if __name__ == "__main__":
    goal = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GOAL
    asyncio.run(main(goal))
