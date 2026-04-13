"""Unit tests for agent/mesh/deployer.py"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.mesh.deployer import (
    DeployerResult,
    _safe_tag,
    _wait_for_http,
    run,
)
from agent.shared.run_context import RunContext


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_ctx(tmp_path) -> RunContext:
    ctx = RunContext(
        run_id="test-run-01",
        intent_spec={
            "run_id": "test-run-01",
            "raw_goal": "build a simple HTTP API",
            "build_target": "api",
        },
        output_dir=str(tmp_path),
    )
    ctx.sandbox.create()
    ctx.file_contents = {
        "src/main.py": "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/health')\ndef health(): return {'ok': True}\n",
        "requirements.txt": "fastapi\nuvicorn\n",
    }
    ctx.architecture_spec = {
        "tech_choices": {"framework": "fastapi"},
        "file_tree": ["src/main.py"],
        "module_interfaces": {},
    }
    return ctx


def make_dockerfile_response(content: str, port: int = 8080, health_path: str = "/health") -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = "write_dockerfile"
    block.input = {"content": content, "port": port, "healthcheck_path": health_path}
    response = MagicMock()
    response.content = [block]
    return response


def make_command_result(success: bool, stdout: str = "", stderr: str = "") -> dict:
    return {"success": success, "returncode": 0 if success else 1, "stdout": stdout, "stderr": stderr}


# ── _safe_tag ──────────────────────────────────────────────────────────────────


class TestSafeTag:
    def test_prefixed_with_mb(self):
        assert _safe_tag("abc123").startswith("mb-")

    def test_underscores_replaced(self):
        tag = _safe_tag("run_id_001")
        assert "_" not in tag

    def test_max_length(self):
        long_id = "x" * 100
        tag = _safe_tag(long_id)
        assert len(tag) <= 43  # "mb-" + 40

    def test_lowercased(self):
        tag = _safe_tag("MyRun")
        assert tag == tag.lower()


# ── _wait_for_http ─────────────────────────────────────────────────────────────


class TestWaitForHttp:
    def test_returns_true_on_immediate_200(self):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert _wait_for_http("http://localhost:8080/health", timeout=5) is True

    def test_returns_false_on_timeout(self):
        with patch("urllib.request.urlopen", side_effect=OSError("refused")):
            with patch("time.sleep"):
                result = _wait_for_http("http://localhost:9999/health", timeout=0)
        assert result is False

    def test_retries_on_error(self):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        call_count = 0

        def side_effect(url, timeout):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise OSError("not ready")
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=side_effect):
            with patch("time.sleep"):
                result = _wait_for_http("http://localhost:8080/health", timeout=10)
        assert result is True
        assert call_count == 3


# ── run() ──────────────────────────────────────────────────────────────────────


class TestDeployerRun:
    @pytest.mark.asyncio
    async def test_dockerfile_written_to_workspace(self, tmp_path):
        ctx = make_ctx(tmp_path)
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_dockerfile_response("FROM python:3.12-slim\nCMD [\"python\", \"app.py\"]\n")
        )

        with patch("agent.mesh.deployer.run_command", return_value=make_command_result(True)) as mock_cmd:
            with patch("agent.mesh.deployer._wait_for_http", return_value=True):
                with patch("agent.mesh.deployer._stop_container"):
                    await run(ctx, client=mock_client)

        assert ctx.dockerfile_path == "Dockerfile"
        dockerfile_on_disk = tmp_path / "workspace" / "Dockerfile"
        assert dockerfile_on_disk.exists()

    @pytest.mark.asyncio
    async def test_smoke_tests_passed_on_healthy_container(self, tmp_path):
        ctx = make_ctx(tmp_path)
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_dockerfile_response("FROM python:3.12-slim\n")
        )

        with patch("agent.mesh.deployer.run_command", return_value=make_command_result(True)):
            with patch("agent.mesh.deployer._wait_for_http", return_value=True):
                with patch("agent.mesh.deployer._stop_container"):
                    await run(ctx, client=mock_client)

        assert ctx.smoke_tests_passed is True
        assert ctx.deploy_failure_reason == ""

    @pytest.mark.asyncio
    async def test_smoke_tests_failed_on_health_timeout(self, tmp_path):
        ctx = make_ctx(tmp_path)
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_dockerfile_response("FROM python:3.12-slim\n")
        )

        with patch("agent.mesh.deployer.run_command", return_value=make_command_result(True)):
            with patch("agent.mesh.deployer._wait_for_http", return_value=False):
                with patch("agent.mesh.deployer._stop_container"):
                    await run(ctx, client=mock_client)

        assert ctx.smoke_tests_passed is False
        assert "health check timed out" in ctx.deploy_failure_reason
        assert len(ctx.deploy_errors) == 1

    @pytest.mark.asyncio
    async def test_docker_build_failure_sets_reason(self, tmp_path):
        ctx = make_ctx(tmp_path)
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_dockerfile_response("FROM python:3.12-slim\n")
        )

        with patch("agent.mesh.deployer.run_command", return_value=make_command_result(False, stderr="no such base image")):
            with patch("agent.mesh.deployer._stop_container"):
                await run(ctx, client=mock_client)

        assert ctx.smoke_tests_passed is False
        assert "docker build failed" in ctx.deploy_failure_reason
        assert ctx.dockerfile_path == "Dockerfile"  # file was written before build

    @pytest.mark.asyncio
    async def test_docker_run_failure_sets_reason(self, tmp_path):
        ctx = make_ctx(tmp_path)
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_dockerfile_response("FROM python:3.12-slim\n")
        )

        build_ok = make_command_result(True)
        run_fail = make_command_result(False, stderr="port already in use")

        with patch("agent.mesh.deployer.run_command", side_effect=[build_ok, run_fail]):
            with patch("agent.mesh.deployer._stop_container"):
                await run(ctx, client=mock_client)

        assert ctx.smoke_tests_passed is False
        assert "docker run failed" in ctx.deploy_failure_reason

    @pytest.mark.asyncio
    async def test_staging_url_set_to_localhost(self, tmp_path):
        ctx = make_ctx(tmp_path)
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_dockerfile_response("FROM python:3.12-slim\n", port=8080, health_path="/health")
        )

        with patch("agent.mesh.deployer.run_command", return_value=make_command_result(True)):
            with patch("agent.mesh.deployer._wait_for_http", return_value=True):
                with patch("agent.mesh.deployer._stop_container"):
                    await run(ctx, client=mock_client)

        assert ctx.staging_url == "http://localhost:8080/health"

    @pytest.mark.asyncio
    async def test_llm_error_sets_failure_reason(self, tmp_path):
        ctx = make_ctx(tmp_path)
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=RuntimeError("API timeout"))

        await run(ctx, client=mock_client)

        assert "Dockerfile generation failed" in ctx.deploy_failure_reason
        assert ctx.smoke_tests_passed is False

    @pytest.mark.asyncio
    async def test_container_always_cleaned_up_on_success(self, tmp_path):
        ctx = make_ctx(tmp_path)
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_dockerfile_response("FROM python:3.12-slim\n")
        )

        stop_calls = []

        with patch("agent.mesh.deployer.run_command", return_value=make_command_result(True)):
            with patch("agent.mesh.deployer._wait_for_http", return_value=True):
                with patch("agent.mesh.deployer._stop_container", side_effect=stop_calls.append):
                    await run(ctx, client=mock_client)

        # _stop_container called twice: before run (cleanup old) and after health check
        assert len(stop_calls) == 2

    @pytest.mark.asyncio
    async def test_no_tool_call_uses_fallback_dockerfile(self, tmp_path):
        """If LLM returns no tool_use block, a generic Dockerfile is still written."""
        ctx = make_ctx(tmp_path)
        mock_client = AsyncMock()
        empty_response = MagicMock()
        empty_response.content = []
        mock_client.messages.create = AsyncMock(return_value=empty_response)

        with patch("agent.mesh.deployer.run_command", return_value=make_command_result(True)):
            with patch("agent.mesh.deployer._wait_for_http", return_value=True):
                with patch("agent.mesh.deployer._stop_container"):
                    await run(ctx, client=mock_client)

        assert ctx.dockerfile_path == "Dockerfile"
        dockerfile_on_disk = tmp_path / "workspace" / "Dockerfile"
        assert dockerfile_on_disk.exists()
        content = dockerfile_on_disk.read_text()
        assert "FROM python" in content
