"""
Sandbox — per-run isolated execution environment.

Every run operates inside a strictly bounded directory tree:

  runs/{run_id}/
  ├── workspace/    ← ONLY location where agents may write files
  ├── artifacts/    ← test results, deploy logs, structured outputs
  └── logs/         ← run-level log files

SandboxManager enforces these invariants:

  - safe_path(path) resolves any path inside workspace/ and raises
    SandboxViolation if the resolved path escapes the sandbox root.
  - Path traversal via ".." is rejected before resolution.
  - Absolute paths are treated as workspace-relative (leading "/" stripped).
  - All writes must go through safe_path(); the main repo is read-only.

Usage:
    from agent.shared.sandbox import SandboxManager, SandboxViolation

    sb = SandboxManager("runs/abc-123")
    sb.create()                              # mkdir workspace/ artifacts/ logs/

    safe = sb.safe_path("src/main.py")       # → Path("runs/abc-123/workspace/src/main.py")
    safe.parent.mkdir(parents=True, exist_ok=True)
    safe.write_text(content)

    # Rejected — path escapes workspace:
    sb.safe_path("../../agent/orchestrator.py")  # raises SandboxViolation
"""
from __future__ import annotations

import shutil
from pathlib import Path


class SandboxViolation(Exception):
    """Raised when a path operation would escape the sandbox workspace."""


class SandboxManager:
    """
    Manages the per-run sandbox directory and enforces path safety.

    Args:
        sandbox_root: The run root directory (e.g. "runs/abc-123" or an
                      absolute path). workspace/, artifacts/, and logs/
                      are always subdirectories of this root.
    """

    def __init__(self, sandbox_root: str | Path) -> None:
        self.root = Path(sandbox_root)
        self.workspace = self.root / "workspace"
        self.artifacts = self.root / "artifacts"
        self.logs = self.root / "logs"

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def create(self) -> None:
        """Create workspace/, artifacts/, and logs/ if they do not exist."""
        for directory in (self.workspace, self.artifacts, self.logs):
            directory.mkdir(parents=True, exist_ok=True)

    def clean_workspace(self) -> None:
        """
        Wipe and recreate workspace/.

        Use this to reset a run without touching artifacts/ or logs/.
        """
        if self.workspace.exists():
            shutil.rmtree(self.workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)

    # ── Path safety ───────────────────────────────────────────────────────

    def safe_path(self, path: str) -> Path:
        """
        Resolve *path* inside workspace/ and validate it does not escape.

        Rules enforced (fail-fast):
          1. Any path component equal to ".." is rejected immediately.
          2. Leading "/" is stripped — all paths are workspace-relative.
          3. The resolved absolute path must be inside workspace/.

        Returns the resolved absolute Path inside workspace/.

        Raises:
            SandboxViolation: if the path would escape workspace/.

        Examples:
            sb.safe_path("src/main.py")          → .../workspace/src/main.py  ✓
            sb.safe_path("/src/main.py")          → .../workspace/src/main.py  ✓ (stripped)
            sb.safe_path("../../agent/run.py")   → SandboxViolation            ✗
            sb.safe_path("/etc/passwd")           → SandboxViolation            ✗
        """
        self._reject_traversal(path)

        # Strip leading slashes so "/src/main.py" → "src/main.py"
        cleaned = path.lstrip("/")
        if not cleaned:
            raise SandboxViolation(f"Empty path after stripping leading slashes: {path!r}")

        candidate = (self.workspace / cleaned).resolve()
        workspace_resolved = self.workspace.resolve()

        try:
            candidate.relative_to(workspace_resolved)
        except ValueError:
            raise SandboxViolation(
                f"Path escapes sandbox workspace: {path!r} → {candidate}\n"
                f"Allowed root: {workspace_resolved}"
            )

        return candidate

    def safe_artifact_path(self, path: str) -> Path:
        """
        Resolve *path* inside artifacts/ with the same safety guarantees.

        Raises:
            SandboxViolation: if the path would escape artifacts/.
        """
        self._reject_traversal(path)

        cleaned = path.lstrip("/")
        if not cleaned:
            raise SandboxViolation(f"Empty path after stripping leading slashes: {path!r}")

        candidate = (self.artifacts / cleaned).resolve()
        artifacts_resolved = self.artifacts.resolve()

        try:
            candidate.relative_to(artifacts_resolved)
        except ValueError:
            raise SandboxViolation(
                f"Path escapes sandbox artifacts: {path!r} → {candidate}\n"
                f"Allowed root: {artifacts_resolved}"
            )

        return candidate

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _reject_traversal(path: str) -> None:
        """Raise SandboxViolation if any path component is '..'."""
        if ".." in Path(path).parts:
            raise SandboxViolation(
                f"Path traversal forbidden — '..' not allowed: {path!r}"
            )
