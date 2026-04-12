"""
RunContext — shared mutable state for a single pipeline run.

Every agent reads from and writes to this object. It travels through the
orchestrator as a plain Python dataclass — no Redis, no network, no async.
TaskGraph (Redis) is the durable audit trail; RunContext is the in-process
fast path.

Design principles:
  - file_contents keeps generated code in-memory so agents can read each
    other's output without touching disk.
  - test_failures, lint_errors, type_errors carry error context from one
    round to the next so coder can see exactly what to fix.
  - Guard methods (coder_should_stop) encode the stopping logic so the
    orchestrator loop stays readable.

Sandbox layout (per run):
  runs/{run_id}/
  ├── workspace/    ← ALL agent-generated code lives here (write-only zone)
  ├── artifacts/    ← test results, deploy logs, structured outputs
  └── logs/         ← run-level log files
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.shared.sandbox import SandboxManager


@dataclass
class RunContext:
    # ── Identity ──────────────────────────────────────────────────────────
    run_id: str
    intent_spec: dict

    # ── Paths ─────────────────────────────────────────────────────────────
    skills_dir: str = "skills"
    output_dir: str = ""  # if empty, defaults to runs/{run_id}/

    # ── Phase 2: Mesh outputs ─────────────────────────────────────────────
    research_result: dict | None = None
    architecture_spec: dict | None = None
    plan_spec: dict | None = None           # per-file blueprint from Planner
    plan_violations: list[str] = field(default_factory=list)  # from plan_validator
    planner_revision: int = 0               # how many times planner was re-run

    # ── Phase 3: Coder state ──────────────────────────────────────────────
    files_written: list[str] = field(default_factory=list)
    # In-memory file contents — avoids disk round-trips between agents
    file_contents: dict[str, str] = field(default_factory=dict)
    lint_errors: list[dict] = field(default_factory=list)
    type_errors: list[dict] = field(default_factory=list)
    lint_passed: bool = False
    type_check_passed: bool = False
    coder_rounds: int = 0

    # ── Phase 4: Tester state ─────────────────────────────────────────────
    tests_written: list[str] = field(default_factory=list)
    test_failures: list[dict] = field(default_factory=list)
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    coverage_pct: float = 0.0
    tester_rounds: int = 0

    # ── Phase 5: Deployer state ───────────────────────────────────────────
    dockerfile_path: str = ""
    workflow_paths: list[str] = field(default_factory=list)
    staging_url: str | None = None
    smoke_tests_passed: bool = False
    deploy_errors: list[str] = field(default_factory=list)
    deploy_failure_reason: str = ""
    deploy_retries: int = 0

    # ── Phase 7: Router state ─────────────────────────────────────────────
    signal_bundle: dict | None = None
    score_result: dict | None = None
    router_decision: dict | None = None

    # ── Timing + iteration guards ─────────────────────────────────────────
    started_at: float = field(default_factory=time.monotonic)
    phase_timestamps: dict[str, float] = field(default_factory=dict)
    MAX_CODER_ROUNDS: int = 5
    MAX_TESTER_ROUNDS: int = 3
    MAX_DEPLOY_RETRIES: int = 2

    # ── Guard methods ─────────────────────────────────────────────────────

    def coder_should_stop(self) -> bool:
        """
        True when coder should not run another round.

        Stops if:
          - max rounds reached (safety guard)
          - no lint errors, no type errors, no test failures (clean pass)
        """
        if self.coder_rounds >= self.MAX_CODER_ROUNDS:
            return True
        return (
            not self.lint_errors
            and not self.type_errors
            and not self.test_failures
        )

    def plan_valid(self) -> bool:
        """True when no plan violations remain (or no plan was generated)."""
        return not self.plan_violations

    def mark_phase(self, phase: str) -> None:
        """Record wall-clock timestamp for a named phase."""
        self.phase_timestamps[phase] = time.monotonic() - self.started_at

    def output_path(self, relative: str) -> Path:
        """
        Resolve a relative path inside this run's output directory.

        Uses output_dir if set, otherwise runs/{run_id}/.
        """
        base = Path(self.output_dir) if self.output_dir else Path("runs") / self.run_id
        return base / relative

    # ── Sandbox properties ─────────────────────────────────────────────────

    @property
    def sandbox_root(self) -> str:
        """Absolute root of this run's sandbox: runs/{run_id}/ or output_dir."""
        return str(Path(self.output_dir) if self.output_dir else Path("runs") / self.run_id)

    @property
    def workspace_path(self) -> str:
        """Path where ALL agent-generated code must be written."""
        return str(Path(self.sandbox_root) / "workspace")

    @property
    def artifacts_path(self) -> str:
        """Path for test results, deploy logs, and structured outputs."""
        return str(Path(self.sandbox_root) / "artifacts")

    @property
    def sandbox(self) -> "SandboxManager":
        """Return a SandboxManager scoped to this run's workspace."""
        from agent.shared.sandbox import SandboxManager
        return SandboxManager(self.sandbox_root)
