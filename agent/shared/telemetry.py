"""
Telemetry — Arize Phoenix + OpenInference tracing for all Anthropic calls.

Calling setup() once at process start is enough. It auto-instruments every
anthropic.AsyncAnthropic and anthropic.Anthropic client in the process,
capturing:
  - Every messages.create call as a span (model, tokens, latency, cost)
  - Tool use blocks (name, input, output)
  - Full message content (prompt + response)

Phoenix UI runs at http://localhost:6006 by default.

Usage:
    from agent.shared.telemetry import setup
    setup()   # call once, then run the pipeline normally

Environment variables:
    PHOENIX_ENABLED=false   — skip telemetry entirely (default: true)
    PHOENIX_PORT=6006        — port for the local Phoenix server
"""
from __future__ import annotations

import os

_initialized = False


def setup(*, project_name: str = "meta-builder") -> bool:
    """
    Start Phoenix server and instrument Anthropic SDK.

    Returns True if telemetry was enabled, False if skipped.
    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _initialized
    if _initialized:
        return True

    if os.getenv("PHOENIX_ENABLED", "true").lower() in ("false", "0", "no"):
        return False

    try:
        import phoenix as px
        from openinference.instrumentation.anthropic import AnthropicInstrumentor
        from phoenix.otel import register

        port = int(os.getenv("PHOENIX_PORT", "6006"))
        os.environ.setdefault("PHOENIX_PORT", str(port))

        # Start the local Phoenix server (no-op if already running)
        px.launch_app()

        # register() auto-connects to the running Phoenix via gRPC (port 4317)
        # and sets itself as the global OTel tracer provider
        tracer_provider = register(project_name=project_name)

        # Auto-instrument all Anthropic SDK calls (sync + async)
        AnthropicInstrumentor().instrument(tracer_provider=tracer_provider)

        _initialized = True
        print(f"  Phoenix UI → http://localhost:{port}  (project: {project_name})")
        return True

    except ImportError:
        # Phoenix not installed — silently skip
        return False
    except Exception as exc:
        # Don't crash the pipeline over telemetry
        print(f"  [telemetry] setup failed (non-fatal): {exc}")
        return False


def span(name: str):
    """
    Context manager for a manual span around orchestrator phases.

    Usage:
        with telemetry.span("planner"):
            result = await planner_run(...)

    No-op if telemetry is not initialized.
    """
    if not _initialized:
        return _NoopSpan()

    try:
        from opentelemetry import trace

        tracer = trace.get_tracer("meta-builder")
        return tracer.start_as_current_span(name)
    except Exception:
        return _NoopSpan()


class _NoopSpan:
    """Context manager that does nothing — used when telemetry is off."""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass
