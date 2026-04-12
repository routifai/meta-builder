"""
Orchestrator — Python-driven execution loop for the full pipeline.

This is NOT an LLM agent. It is a deterministic coordinator that knows:
  - WHEN to call each agent
  - WHAT error context to pass
  - HOW MANY rounds to allow

The agents (especially coder) are the smart ones — they use LLM ReAct loops
to decide HOW to fix problems.

Pipeline phases:
    1. Intent block   — prompt_parser → ambiguity_scorer → defaults_agent
    2. Mesh           — researcher ‖ architect (concurrent)
    2b. Planner       — per-file blueprint from architecture_spec
    3. Coder loop     — up to MAX_CODER_ROUNDS; gets error context from RunContext
    3b. Plan validate — AST-based symbol check; violations feed back to coder
                        if violations persist after MAX_PLAN_FIX_ROUNDS: re-run planner
    4. Tester + retry — tester writes + runs tests; failures feed back to coder
    5. Deployer       — builds + deploys; errors feed back to coder
    6. Monitor setup
    7. Signals        — signal_collector → scorer → router

Usage:
    from agent.orchestrator import run as orchestrator_run
    ctx = await orchestrator_run(intent_spec)
"""
from __future__ import annotations

import asyncio

from agent.shared.run_context import RunContext


async def run(
    intent_spec: dict,
    *,
    skills_dir: str = "skills",
    output_dir: str = "",
) -> RunContext:
    """
    Execute the full pipeline for a validated intent spec.

    Returns the final RunContext with all phase outputs populated.
    Raises NotImplementedError for agents not yet implemented (stubs).
    """
    ctx = RunContext(
        run_id=intent_spec["run_id"],
        intent_spec=intent_spec,
        skills_dir=skills_dir,
        output_dir=output_dir,
    )

    # ── Phase 2: Mesh — researcher ‖ architect ─────────────────────────────
    ctx.mark_phase("mesh_start")
    from agent.mesh.researcher import run as researcher_run
    from agent.mesh.architect import run as architect_run

    ctx.research_result, ctx.architecture_spec = await asyncio.gather(
        researcher_run(intent_spec, skills_dir=skills_dir),
        architect_run(intent_spec, {}, skills_dir=skills_dir),
    )
    ctx.mark_phase("mesh_done")

    # ── Phase 2b: Planner — per-file implementation blueprint ─────────────
    ctx.mark_phase("planner_start")
    from agent.mesh.planner import run as planner_run  # also used in phase 3b

    ctx.plan_spec = await planner_run(
        intent_spec,
        ctx.architecture_spec,
    )
    ctx.mark_phase("planner_done")

    # ── Phase 3: Coder inner loop ──────────────────────────────────────────
    ctx.mark_phase("coder_start")
    from agent.mesh.coder import run as coder_run
    from agent.mesh.plan_validator import validate as plan_validate
    from agent.mesh.plan_validator import should_revise_plan, build_revision_note

    while not ctx.coder_should_stop():
        ctx.coder_rounds += 1
        await coder_run(ctx)

    ctx.mark_phase("coder_done")

    # ── Phase 3b: Plan validation + optional fix loop ──────────────────────
    ctx.mark_phase("plan_validate_start")

    if ctx.plan_spec:
        MAX_PLAN_FIX_ROUNDS = 2
        plan_fix_rounds = 0

        validation = plan_validate(ctx.plan_spec, ctx.file_contents)
        ctx.plan_violations = validation["violations"]

        while not ctx.plan_valid() and plan_fix_rounds < MAX_PLAN_FIX_ROUNDS:
            plan_fix_rounds += 1

            # After threshold failures, revise the plan before retrying
            if should_revise_plan(plan_fix_rounds, ctx.plan_violations):
                revision_note = build_revision_note(ctx.plan_violations)
                ctx.planner_revision += 1
                ctx.plan_spec = await planner_run(
                    ctx.intent_spec,
                    ctx.architecture_spec,
                    revision_note=revision_note,
                )

            ctx.coder_rounds = 0
            while not ctx.coder_should_stop():
                ctx.coder_rounds += 1
                await coder_run(ctx)

            validation = plan_validate(ctx.plan_spec, ctx.file_contents)
            ctx.plan_violations = validation["violations"]

    ctx.mark_phase("plan_validate_done")

    # ── Phase 4: Tester + optional coder retry ─────────────────────────────
    ctx.mark_phase("tester_start")
    from agent.mesh.tester import run as tester_run

    while ctx.tester_rounds < ctx.MAX_TESTER_ROUNDS:
        ctx.tester_rounds += 1
        await tester_run(ctx)
        if not ctx.test_failures:
            break
        # Push failures back into coder for another pass
        ctx.coder_rounds = 0  # reset so coder gets a fresh MAX_CODER_ROUNDS
        while not ctx.coder_should_stop():
            ctx.coder_rounds += 1
            await coder_run(ctx)

    ctx.mark_phase("tester_done")

    # ── Phase 5: Deployer + optional coder retry ───────────────────────────
    ctx.mark_phase("deploy_start")
    from agent.mesh.deployer import run as deployer_run

    for _ in range(ctx.MAX_DEPLOY_RETRIES):
        ctx.deploy_retries += 1
        await deployer_run(ctx)
        if ctx.smoke_tests_passed:
            break
        # Deployer signals a code fix is needed — not a deploy config fix
        if ctx.deploy_failure_reason:
            ctx.coder_rounds = 0
            while not ctx.coder_should_stop():
                ctx.coder_rounds += 1
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
