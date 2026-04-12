# Hard Constraints

## Skills

- `skills/*.md` is **append-only** — `SkillsStore.write_new` raises `FileExistsError` if the file exists; use `SkillsStore.append` for updates.
- `skills/` stem names must stay in sync with `KNOWN_DOMAINS` in `agent/intent/prompt_parser.py`. Adding a new skill requires adding its domain there too.
- Skills are mounted as a persistent volume on Fly (`/app/skills`) — they survive deploys and accumulate knowledge across runs.

## Intent spec

- `REQUIRED_FIELDS` in `agent/shared/intent_spec.py` must always be present and non-empty — the validator raises on missing fields.
- `run_id` is unique per run; never reuse it.
- Never mutate a committed intent spec mid-run; if goals change, start a new run.

## State / Redis

- Redis key pattern: `task-graph:{run_id}:node:{agent_name}` — do not change this without updating `TaskGraph._node_key`.
- All 18 agent names in `ALL_AGENTS` (`agent/shared/state.py`) must match the node names in `.agent/task-graph.json`.
- `publish_event` is fire-and-forget; never await a response on the pub/sub channel.

## Decision log

- `decision-log/` is append-only JSONL — never truncate or delete entries.
- `decision-log/` is in `.gitignore` — runtime only, not committed.

## Tests

- Commit only when tests are green — no exceptions.
- Tests that are `@pytest.mark.skip` are **not** green; unskip and fix before committing.
- The full test suite must pass: `pytest tests/` with no `-k` filtering before any merge.

## Security

- `.env` is in `.gitignore` — never commit it. API keys live in `.env` and in CI/Fly secrets only.
- Never hardcode credentials, tokens, or URLs in source files.

## Versioning

- Package version is in `pyproject.toml`. Bump only at release.
- Python minimum: 3.12 (per `pyproject.toml`). No syntax or APIs below 3.12.

## CI / Fly

- The build workflow triggers on changes to `.agent/intent-spec.json` on `main` only.
- The fix workflow is dispatch-only — never trigger it manually mid-build.
- Fly process names in `fly.toml` must match the Python module paths under `agent/monitor/`.
- `health_server` must respond `200 OK` at `/health` — Fly health checks depend on this.
