"""
Orchestrator — Python-driven execution loop for the full pipeline.

This is NOT an LLM agent. It is a deterministic coordinator that knows:
  - WHEN to call each agent
  - WHAT error context to pass
  - HOW MANY rounds to allow

The agents (especially coder and critic) are the smart ones — they use LLM
loops to decide HOW to fix problems. The orchestrator decides WHEN to stop.

Pipeline phases:
    1.  Intent block      — prompt_parser → ambiguity_scorer → defaults_agent
    1b. Feasibility       — feasibility_critic blocks impossible goals
    1c. Requirement       — requirement_closure fills missing operational params
    2.  Mesh (concurrent) — researcher ‖ architect
    2b. Planner           — per-file implementation blueprint
    2c. Critic (plan)     — critic.evaluate_plan → approve/revise/block
    3.  Coder loop        — up to MAX_CODER_ROUNDS; gets error context from RunContext
    3b. Plan validate     — AST symbol check; violations feed back to coder
    3c. Critic (code)     — critic.evaluate_code → approve/revise (max MAX_CRITIC_ROUNDS)
    4.  Tester            — write tests + run them
    4b. Critic (tests)    — critic.evaluate_tests → approve/revise
    4c. Tester retry      — test failures feed back to coder
    5.  Deployer          — Dockerfile + deploy + smoke tests
    6.  Monitor setup
    7.  Signals           — signal_collector → scorer → router

Exit conditions on critic "block":
    - Stored in ctx.critic_*_result with decision="block"
    - Pipeline halts at that phase and returns ctx (for human review)

Usage:
    ctx = await orchestrator_run(intent_spec)
    if ctx.critic_plan_result and ctx.critic_plan_result["decision"] == "block":
        # escalate to human
"""
from __future__ import annotations

import asyncio

from agent.shared.run_context import RunContext
from agent.shared import telemetry

MAX_CRITIC_ROUNDS = 2
MAX_PLAN_FIX_ROUNDS = 2


async def run(
    intent_spec: dict,
    *,
    skills_dir: str = "skills",
    output_dir: str = "",
) -> RunContext:
    """
    Execute the full pipeline for a validated intent spec.

    Returns RunContext — check ctx.critic_*_result["decision"] for blocks.
    Raises NotImplementedError for agents not yet implemented (stubs).
    """
    ctx = RunContext(
        run_id=intent_spec["run_id"],
        intent_spec=intent_spec,
        skills_dir=skills_dir,
        output_dir=output_dir,
    )
    ctx.sandbox.create()  # set up workspace/ artifacts/ logs/

    # ── Phase 1b: Feasibility critic ──────────────────────────────────────
    ctx.mark_phase("feasibility_start")
    from agent.intent.feasibility_critic import evaluate as feasibility_evaluate

    with telemetry.span("feasibility_critic"):
        feasibility = await feasibility_evaluate(intent_spec)
    ctx.feasibility_result = dict(feasibility)

    if feasibility["decision"] == "block":
        ctx.mark_phase("feasibility_blocked")
        return ctx  # pipeline halts — nothing to build

    # If the critic refined the goal, update the spec before proceeding
    if feasibility["decision"] == "refine" and feasibility.get("refined_goal"):
        intent_spec = dict(intent_spec)
        intent_spec["raw_goal"] = feasibility["refined_goal"]
        ctx.intent_spec = intent_spec

    ctx.mark_phase("feasibility_done")

    # ── Phase 1c: Requirement closure ─────────────────────────────────────
    ctx.mark_phase("closure_start")
    from agent.intent.requirement_closure import close as closure_close

    closure = closure_close(intent_spec)
    ctx.closure_result = dict(closure)

    if closure["status"] == "needs_input":
        # Return so the caller can surface ctx.closure_result["questions"] to the user
        ctx.mark_phase("closure_needs_input")
        return ctx

    # Apply auto-filled fields to intent_spec
    if closure["auto_filled"]:
        intent_spec = {**intent_spec, **closure["auto_filled"]}
        ctx.intent_spec = intent_spec

    ctx.mark_phase("closure_done")

    # ── Phase 2: Mesh — researcher ‖ architect (concurrent) ───────────────
    ctx.mark_phase("mesh_start")
    from agent.mesh.researcher import run as researcher_run
    from agent.mesh.architect import run as architect_run

    with telemetry.span("mesh.researcher+architect"):
        ctx.research_result, ctx.architecture_spec = await asyncio.gather(
            researcher_run(intent_spec, skills_dir=skills_dir),
            architect_run(intent_spec, {}, skills_dir=skills_dir),
        )
    ctx.mark_phase("mesh_done")

    # ── Phase 2b: Planner ─────────────────────────────────────────────────
    ctx.mark_phase("planner_start")
    from agent.mesh.planner import run as planner_run

    with telemetry.span("planner"):
        ctx.plan_spec = await planner_run(intent_spec, ctx.architecture_spec)
    ctx.mark_phase("planner_done")

    # ── Phase 2c: Critic — plan review ────────────────────────────────────
    ctx.mark_phase("critic_plan_start")
    from agent.mesh.critic import evaluate_plan as critic_plan

    plan_critic_rounds = 0
    while plan_critic_rounds < MAX_CRITIC_ROUNDS:
        plan_critic_rounds += 1
        ctx.critic_rounds += 1
        with telemetry.span(f"critic.plan.round{plan_critic_rounds}"):
            result = await critic_plan(ctx.plan_spec, ctx.architecture_spec, intent_spec)
        ctx.critic_plan_result = dict(result)

        if result["decision"] == "block":
            ctx.mark_phase("critic_plan_blocked")
            return ctx

        if result["decision"] == "approve":
            break

        # revise: re-run planner with critic's instructions
        ctx.planner_revision += 1
        with telemetry.span(f"planner.revision{ctx.planner_revision}"):
            ctx.plan_spec = await planner_run(
                intent_spec,
                ctx.architecture_spec,
                revision_note=result["revision_instructions"],
            )

    ctx.mark_phase("critic_plan_done")

    # ── Phase 3: Coder inner loop ──────────────────────────────────────────
    ctx.mark_phase("coder_start")
    from agent.mesh.coder import run as coder_run
    from agent.mesh.plan_validator import validate as plan_validate
    from agent.mesh.plan_validator import should_revise_plan, build_revision_note

    while not ctx.coder_should_stop():
        ctx.coder_rounds += 1
        with telemetry.span(f"coder.round{ctx.coder_rounds}"):
            await coder_run(ctx)

    ctx.mark_phase("coder_done")

    # ── Phase 3b: Plan validation ──────────────────────────────────────────
    ctx.mark_phase("plan_validate_start")
    if ctx.plan_spec:
        plan_fix_rounds = 0
        validation = plan_validate(ctx.plan_spec, ctx.file_contents)
        ctx.plan_violations = validation["violations"]

        while not ctx.plan_valid() and plan_fix_rounds < MAX_PLAN_FIX_ROUNDS:
            plan_fix_rounds += 1
            if should_revise_plan(plan_fix_rounds, ctx.plan_violations):
                ctx.planner_revision += 1
                with telemetry.span(f"planner.revision{ctx.planner_revision}"):
                    ctx.plan_spec = await planner_run(
                        intent_spec,
                        ctx.architecture_spec,
                        revision_note=build_revision_note(ctx.plan_violations),
                    )
            ctx.coder_rounds = 0
            while not ctx.coder_should_stop():
                ctx.coder_rounds += 1
                with telemetry.span(f"coder.round{ctx.coder_rounds}"):
                    await coder_run(ctx)
            validation = plan_validate(ctx.plan_spec, ctx.file_contents)
            ctx.plan_violations = validation["violations"]

    ctx.mark_phase("plan_validate_done")

    # ── Phase 3c: Critic — code review ────────────────────────────────────
    ctx.mark_phase("critic_code_start")
    from agent.mesh.critic import evaluate_code as critic_code

    code_critic_rounds = 0
    while code_critic_rounds < MAX_CRITIC_ROUNDS:
        code_critic_rounds += 1
        ctx.critic_rounds += 1
        with telemetry.span(f"critic.code.round{code_critic_rounds}"):
            result = await critic_code(ctx.file_contents, ctx.plan_spec or {}, intent_spec)
        ctx.critic_code_result = dict(result)

        if result["decision"] == "block":
            ctx.mark_phase("critic_code_blocked")
            return ctx

        if result["decision"] == "approve":
            break

        # revise: push instructions as test failures to drive another coder round
        ctx.test_failures = [
            {"test": "critic_review", "error": result["revision_instructions"]}
        ]
        ctx.coder_rounds = 0
        while not ctx.coder_should_stop():
            ctx.coder_rounds += 1
            with telemetry.span(f"coder.round{ctx.coder_rounds}"):
                await coder_run(ctx)
        ctx.test_failures = []  # clear after coder pass

    ctx.mark_phase("critic_code_done")

    # ── Phase 4: Tester ───────────────────────────────────────────────────
    ctx.mark_phase("tester_start")
    from agent.mesh.tester import run as tester_run
    from agent.mesh.critic import evaluate_tests as critic_tests

    while ctx.tester_rounds < ctx.MAX_TESTER_ROUNDS:
        ctx.tester_rounds += 1
        with telemetry.span(f"tester.round{ctx.tester_rounds}"):
            await tester_run(ctx)

        # Phase 4b: Critic — test quality review
        with telemetry.span(f"critic.tests.round{ctx.tester_rounds}"):
            test_critic_result = await critic_tests(
                ctx.file_contents, ctx.tests_written, intent_spec
            )
        ctx.critic_test_result = dict(test_critic_result)
        ctx.critic_rounds += 1

        if test_critic_result["decision"] == "block":
            ctx.mark_phase("critic_test_blocked")
            return ctx

        if test_critic_result["decision"] == "revise":
            # Push revision instructions as test failures → tester re-runs
            ctx.test_failures = [
                {
                    "test": "critic_test_review",
                    "error": test_critic_result["revision_instructions"],
                }
            ] + ctx.test_failures
            ctx.coder_rounds = 0
            while not ctx.coder_should_stop():
                ctx.coder_rounds += 1
                with telemetry.span(f"coder.round{ctx.coder_rounds}"):
                    await coder_run(ctx)
            ctx.test_failures = []
            continue

        # approve: check actual test pass/fail
        if not ctx.test_failures:
            break

        ctx.coder_rounds = 0
        while not ctx.coder_should_stop():
            ctx.coder_rounds += 1
            with telemetry.span(f"coder.round{ctx.coder_rounds}"):
                await coder_run(ctx)

    ctx.mark_phase("tester_done")

    # ── Phase 5: Deployer ─────────────────────────────────────────────────
    ctx.mark_phase("deploy_start")
    from agent.mesh.deployer import run as deployer_run

    for _ in range(ctx.MAX_DEPLOY_RETRIES):
        ctx.deploy_retries += 1
        with telemetry.span(f"deployer.attempt{ctx.deploy_retries}"):
            await deployer_run(ctx)
        if ctx.smoke_tests_passed:
            break
        if ctx.deploy_failure_reason:
            ctx.coder_rounds = 0
            while not ctx.coder_should_stop():
                ctx.coder_rounds += 1
                with telemetry.span(f"coder.round{ctx.coder_rounds}"):
                    await coder_run(ctx)

    ctx.mark_phase("deploy_done")

    # ── Phase 6: Monitor setup ─────────────────────────────────────────────
    ctx.mark_phase("monitor_start")
    from agent.mesh.monitor_setup import run as monitor_run

    await monitor_run(ctx)
    ctx.mark_phase("monitor_done")

    # ── Phase 7: Signals → scorer → router ───────────────────────────────
    ctx.mark_phase("router_start")
    from agent.router.signal_collector import run as signal_run
    from agent.router.scorer import run as scorer_run
    from agent.router.router import run as router_run

    await signal_run(ctx)
    await scorer_run(ctx)
    await router_run(ctx)
    ctx.mark_phase("router_done")

    return ctx
