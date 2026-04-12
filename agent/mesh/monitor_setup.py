"""
Monitor setup — Block 2.

Input:  intent_spec: IntentSpec, deploy_result: DeployerResult
Output: MonitorSetupResult
  {
    "alert_rules": list[dict],       # configured alert rules
    "webhook_endpoints": list[str],  # URLs wired for anomaly events
    "runbook_paths": list[str],      # stub runbook files written
    "error_rate_threshold": float,   # e.g. 0.05 = 5%
  }

Configures alert rules, error rate thresholds, webhook endpoints,
and writes runbook stubs — all before first deploy.
"""
from __future__ import annotations

from typing import TypedDict


class MonitorSetupResult(TypedDict):
    alert_rules: list[dict]
    webhook_endpoints: list[str]
    runbook_paths: list[str]
    error_rate_threshold: float


async def run(intent_spec: dict, deploy_result: dict) -> MonitorSetupResult:
    """Configure monitoring: alerts, thresholds, webhooks, runbooks."""
    raise NotImplementedError
