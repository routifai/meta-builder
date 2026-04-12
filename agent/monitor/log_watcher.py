"""
Log watcher — Block 4, persistent Fly.io worker.

Tails log streams from production services.
Detects error spikes above threshold.
Emits structured anomaly events to Redis pub/sub.

Output event schema (published to Redis channel events:{run_id}):
  {
    "event": "anomaly_detected",
    "run_id": str,
    "service": str,
    "error_rate": float,
    "window_seconds": int,
    "sample_errors": list[str],
    "timestamp": str,
  }
"""
from __future__ import annotations


async def run(run_id: str) -> None:
    """Tail logs forever; emit anomaly events to Redis on error spike."""
    raise NotImplementedError
