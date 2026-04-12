"""
Deployer — Block 2.

Input:  ctx: RunContext (populated by coder + tester phases)
Output: DeployerResult
  {
    "dockerfile_path": str,      # relative path inside workspace/
    "workflow_paths": list[str], # GitHub Actions YAML files, workspace-relative
    "staging_url": str | None,   # if staging env provisioned
    "smoke_tests_passed": bool,
    "secrets_injected": list[str],
  }

Sandbox constraints:
  - Docker build context = workspace/ only (no access to parent repo)
  - Dockerfile and workflow files are written via write_file (sandbox-enforced)
  - All run_command calls use workspace as cwd

Writes Dockerfile + GitHub Actions YAML.
Provisions staging env. Runs smoke tests. Manages secrets injection.
"""
from __future__ import annotations

from typing import TypedDict

from agent.shared.capabilities import run_command, write_file
from agent.shared.run_context import RunContext


class DeployerResult(TypedDict):
    dockerfile_path: str
    workflow_paths: list[str]
    staging_url: str | None
    smoke_tests_passed: bool
    secrets_injected: list[str]


async def run(ctx: RunContext) -> DeployerResult:
    """
    Write deployment config; build Docker image from workspace/; run smoke tests.

    The Docker build context is strictly ctx.workspace_path — the deployer
    never references files outside the sandbox.
    """
    raise NotImplementedError
