"""
Deployer v0 — local Docker build + run + HTTP health check.

No Fly.io, no cloud. The goal is to verify the generated code actually
runs in a container before we care about remote deployment.

Pipeline:
  1. LLM generates a Dockerfile from ctx.file_contents + ctx.architecture_spec
  2. Dockerfile is written to workspace/Dockerfile (sandbox-enforced)
  3. docker build -t {tag} .     (build context = workspace/)
  4. docker run -d -p {port}:{port} --name {name} {tag}
  5. Poll http://localhost:{port}{healthcheck_path} until alive or timeout
  6. Update ctx: dockerfile_path, staging_url, smoke_tests_passed, deploy_failure_reason
  7. Always stop+rm the container after the check (no dangling containers)

If the build or run fails, the reason is stored in ctx.deploy_failure_reason
so the orchestrator can feed it back to the coder.
"""
from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
from typing import TypedDict

from agent.shared.capabilities import run_command, write_file
from agent.shared.run_context import RunContext

DEPLOYER_MODEL = os.getenv("DEPLOYER_MODEL", "claude-haiku-4-5-20251001")
DEFAULT_PORT = 8080
HEALTH_TIMEOUT = 30  # seconds to wait for container to come up
HEALTH_INTERVAL = 1  # seconds between polls


# ── LLM tool schema ───────────────────────────────────────────────────────────

_DOCKERFILE_TOOL = {
    "name": "write_dockerfile",
    "description": (
        "Write a Dockerfile for the project. "
        "Include only what is strictly necessary to run the app in production."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Full Dockerfile text",
            },
            "port": {
                "type": "integer",
                "description": "Port the app listens on inside the container",
                "default": 8080,
            },
            "healthcheck_path": {
                "type": "string",
                "description": "HTTP path to probe for liveness, e.g. /health or /",
                "default": "/health",
            },
        },
        "required": ["content"],
    },
}

_SYSTEM = """\
You are an expert DevOps engineer writing minimal, correct Dockerfiles.

Rules:
- Use the smallest viable base image (python:3.12-slim for Python, node:20-slim for Node, etc.)
- Install only the packages listed in requirements.txt / package.json if present
- Set a non-root user
- EXPOSE the correct port
- CMD must start the application directly (no shell wrapper unless needed)
- Do NOT include HEALTHCHECK in the Dockerfile — it is checked externally
- Keep the file under 30 lines
"""


# ── Internal helpers ──────────────────────────────────────────────────────────


def _safe_tag(run_id: str) -> str:
    """Docker tag from run_id — lowercase alphanumeric + hyphens only."""
    return "mb-" + run_id.lower().replace("_", "-")[:40]


async def _generate_dockerfile(
    ctx: RunContext,
    *,
    client,
) -> tuple[str, int, str]:
    """
    Ask the LLM to write a Dockerfile.

    Returns (dockerfile_content, port, healthcheck_path).
    """
    # Summarize file contents for the prompt (cap at 8K chars total)
    files_summary_parts = []
    budget = 8000
    for path, content in ctx.file_contents.items():
        snippet = content[:400]
        if len(content) > 400:
            snippet += f"\n... ({len(content) - 400} more chars)"
        entry = f"### {path}\n{snippet}"
        if budget - len(entry) < 0:
            break
        files_summary_parts.append(entry)
        budget -= len(entry)
    files_summary = "\n\n".join(files_summary_parts) or "(no files written yet)"

    arch = ctx.architecture_spec or {}
    tech = arch.get("tech_choices", {})
    build_target = ctx.intent_spec.get("build_target", "")

    prompt = (
        f"Project: {ctx.intent_spec.get('raw_goal', '')}\n"
        f"Build target: {build_target}\n"
        f"Tech stack: {tech}\n\n"
        f"Files in workspace:\n{files_summary}\n\n"
        "Write a production-ready Dockerfile for this project."
    )

    response = await client.messages.create(
        model=DEPLOYER_MODEL,
        max_tokens=1024,
        system=_SYSTEM,
        tools=[_DOCKERFILE_TOOL],
        tool_choice={"type": "tool", "name": "write_dockerfile"},
        messages=[{"role": "user", "content": prompt}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "write_dockerfile":
            inp = block.input
            return (
                inp["content"],
                int(inp.get("port", DEFAULT_PORT)),
                str(inp.get("healthcheck_path", "/health")),
            )

    # Fallback: generic Python Dockerfile
    return (
        "FROM python:3.12-slim\nWORKDIR /app\nCOPY . .\n"
        "RUN pip install --no-cache-dir -r requirements.txt 2>/dev/null || true\n"
        f"EXPOSE {DEFAULT_PORT}\nCMD [\"python\", \"-m\", \"uvicorn\", \"main:app\", "
        f"\"--host\", \"0.0.0.0\", \"--port\", \"{DEFAULT_PORT}\"]\n",
        DEFAULT_PORT,
        "/health",
    )


def _wait_for_http(url: str, timeout: int = HEALTH_TIMEOUT) -> bool:
    """Poll url until it returns 2xx or timeout expires. Returns True on success."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if 200 <= resp.status < 300:
                    return True
        except Exception:
            pass
        time.sleep(HEALTH_INTERVAL)
    return False


def _stop_container(name: str) -> None:
    """Best-effort: stop and remove the container (swallow errors)."""
    import subprocess

    for cmd in [["docker", "stop", name], ["docker", "rm", name]]:
        try:
            subprocess.run(cmd, capture_output=True, timeout=15)
        except Exception:
            pass


# ── Types ─────────────────────────────────────────────────────────────────────


class DeployerResult(TypedDict):
    dockerfile_path: str
    workflow_paths: list[str]
    staging_url: str | None
    smoke_tests_passed: bool
    secrets_injected: list[str]


# ── Public API ────────────────────────────────────────────────────────────────


async def run(ctx: RunContext, *, client=None) -> None:
    """
    Deploy the workspace to a local Docker container and run a health check.

    Updates ctx fields:
      - dockerfile_path
      - staging_url
      - smoke_tests_passed
      - deploy_failure_reason
      - deploy_errors
    """
    if client is None:
        import anthropic

        client = anthropic.AsyncAnthropic()

    tag = _safe_tag(ctx.run_id)
    container_name = tag

    # ── Step 1: Generate Dockerfile ──────────────────────────────────────────
    try:
        dockerfile_content, port, health_path = await _generate_dockerfile(
            ctx, client=client
        )
    except Exception as exc:
        ctx.deploy_failure_reason = f"Dockerfile generation failed: {exc}"
        ctx.deploy_errors.append(ctx.deploy_failure_reason)
        return

    # ── Step 2: Write Dockerfile to workspace ────────────────────────────────
    try:
        write_file("Dockerfile", dockerfile_content, ctx)
        ctx.dockerfile_path = "Dockerfile"
    except Exception as exc:
        ctx.deploy_failure_reason = f"Could not write Dockerfile: {exc}"
        ctx.deploy_errors.append(ctx.deploy_failure_reason)
        return

    # ── Step 3: docker build ─────────────────────────────────────────────────
    build_result = run_command(
        ["docker", "build", "-t", tag, "."],
        ctx,
        timeout=300,
    )
    if not build_result["success"]:
        ctx.deploy_failure_reason = (
            f"docker build failed:\n{build_result['stderr'] or build_result['stdout']}"
        )
        ctx.deploy_errors.append(ctx.deploy_failure_reason)
        return

    # ── Step 4: docker run (detached) ────────────────────────────────────────
    _stop_container(container_name)  # clean up any previous run
    run_result = run_command(
        [
            "docker", "run", "-d",
            "--name", container_name,
            "-p", f"{port}:{port}",
            tag,
        ],
        ctx,
        timeout=30,
    )
    if not run_result["success"]:
        ctx.deploy_failure_reason = (
            f"docker run failed:\n{run_result['stderr'] or run_result['stdout']}"
        )
        ctx.deploy_errors.append(ctx.deploy_failure_reason)
        return

    # ── Step 5: Health check ─────────────────────────────────────────────────
    url = f"http://localhost:{port}{health_path}"
    ctx.staging_url = url

    alive = _wait_for_http(url, timeout=HEALTH_TIMEOUT)

    # ── Step 6: Record result + always clean up ──────────────────────────────
    ctx.smoke_tests_passed = alive
    if not alive:
        ctx.deploy_failure_reason = (
            f"Container started but health check timed out after {HEALTH_TIMEOUT}s: {url}"
        )
        ctx.deploy_errors.append(ctx.deploy_failure_reason)

    _stop_container(container_name)
