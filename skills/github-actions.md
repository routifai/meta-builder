# GitHub Actions — Ephemeral Agent Workflows

## Sources
- https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows

---

## Two triggers used in this project

| Workflow | File | Trigger |
|----------|------|---------|
| `agent-build.yml` | Runs full agent mesh when intent spec is pushed | `push` to `main` on `intent-spec.json` path |
| `agent-fix.yml` | Runs fix loop when Sentry/Datadog webhook fires | `repository_dispatch` with `event_type: anomaly_detected` |

---

## `repository_dispatch` — triggering from external systems

### Workflow definition

```yaml
# .github/workflows/agent-fix.yml
name: Agent Fix Loop

on:
  repository_dispatch:
    types: [anomaly_detected]   # only fire on this event_type

jobs:
  fix:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run fix agent
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          REDIS_URL: ${{ secrets.REDIS_URL }}
          RUN_ID: ${{ github.event.client_payload.run_id }}
          ANOMALY_DATA: ${{ toJson(github.event.client_payload.anomaly) }}
        run: python -m agent.monitor.fix_agent
```

### Triggering via API (from Sentry/Datadog webhook or Fly.io worker)

```bash
curl -X POST \
  -H "Authorization: token $GITHUB_PAT" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/{owner}/{repo}/dispatches \
  -d '{
    "event_type": "anomaly_detected",
    "client_payload": {
      "run_id": "abc-123",
      "anomaly": {
        "type": "error_spike",
        "service": "api",
        "error_rate": 0.15,
        "stack_trace": "..."
      }
    }
  }'
```

**Constraints:**
- `event_type`: max 100 characters
- `client_payload`: max 10 top-level properties, max 65,535 characters total
- Workflow file **must exist on the default branch** (usually `main`) to be triggered
- `GITHUB_SHA` and `GITHUB_REF` point to default branch, not the triggering commit

### Accessing payload in steps

```yaml
- name: Use payload
  env:
    RUN_ID: ${{ github.event.client_payload.run_id }}
  run: echo "Fixing run $RUN_ID"

- name: Conditional on payload field
  if: ${{ github.event.client_payload.anomaly.type == 'error_spike' }}
  run: python -m agent.monitor.fix_agent --mode spike
```

---

## `push` trigger with path filters — agent-build.yml

```yaml
# .github/workflows/agent-build.yml
name: Agent Build

on:
  push:
    branches: [main]
    paths:
      - ".agent/intent-spec.json"   # only fire when intent spec changes

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run orchestrator
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          REDIS_URL: ${{ secrets.REDIS_URL }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          LANGSMITH_API_KEY: ${{ secrets.LANGSMITH_API_KEY }}
          LANGSMITH_TRACING: "true"
        run: python -m agent.orchestrator
```

---

## Secrets injection

Secrets are set in the GitHub repo under **Settings → Secrets and variables → Actions**.

```yaml
env:
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  REDIS_URL: ${{ secrets.REDIS_URL }}
  FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
```

**Never hardcode secrets in workflow files or Python code.** Always read from `os.environ` at runtime.

```python
import os

api_key = os.environ["ANTHROPIC_API_KEY"]   # raises KeyError if missing — fast fail
redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")  # with default
```

---

## Artifact passing between jobs

When one job produces output needed by a downstream job in the same run:

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Run build
        run: python -m agent.mesh.coder

      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: build-output
          path: artifacts/

  test:
    needs: build       # wait for build job
    runs-on: ubuntu-latest
    steps:
      - name: Download artifacts
        uses: actions/download-artifact@v4
        with:
          name: build-output
          path: artifacts/

      - name: Run tests
        run: pytest tests/
```

---

## Job outputs (small values between jobs — not files)

```yaml
jobs:
  score:
    runs-on: ubuntu-latest
    outputs:
      confidence: ${{ steps.score.outputs.confidence }}
    steps:
      - id: score
        run: echo "confidence=92" >> $GITHUB_OUTPUT

  route:
    needs: score
    runs-on: ubuntu-latest
    steps:
      - name: Auto-merge if confident
        if: ${{ needs.score.outputs.confidence > 85 }}
        run: gh pr merge --auto --squash
```

---

## Auto-merge pattern (router agent)

```yaml
- name: Merge PR if CI green
  if: ${{ env.CONFIDENCE_SCORE > 85 }}
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    PR_NUMBER: ${{ github.event.client_payload.pr_number }}
  run: |
    gh pr merge $PR_NUMBER --auto --squash \
      --repo ${{ github.repository }}
```

---

## Gotchas

- **`repository_dispatch` only fires from the default branch.** The workflow file must be on `main`/`master`; it can't be triggered from a feature branch.
- **`client_payload` is limited.** 10 top-level keys, 65 KB total. For large payloads (stack traces, logs), write to Redis and pass a `run_id` reference instead.
- **`GITHUB_TOKEN` permissions.** The default token can read/write the repo but may not create PRs across forks or trigger other workflows. For cross-repo operations, use a PAT stored as a secret.
- **Path filters use glob matching.** `paths: ["src/**"]` matches any file under `src/` recursively.
- **Artifact retention default is 90 days.** Override with `retention-days: 7` on upload step.
- **Job `needs:` creates strict ordering.** Use `needs: [build, test]` (array) to wait for multiple jobs.
