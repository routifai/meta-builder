# meta-builder — Project Reference

## Session protocol

At the start of every session, read these three files before writing any code:

```
memory/progress.md       ← current phase, per-agent status, immediate next step
memory/constraints.md    ← non-negotiables that must never be violated
memory/agent-contracts.md ← agreed input/output TypedDict shapes per agent
```

At the end of every session, update `memory/progress.md` to reflect what changed.

---

## Mission

**A goal goes in. A deployed, monitored application comes out.**

meta-builder is a fully autonomous software delivery system. When a human writes a one-sentence goal ("build an MCP server for Perplexity, deploy to Fly"), the system owns the entire lifecycle: research → architect → code → test → deploy → monitor → self-heal. Zero developer involvement after the intent spec is written.

---

## Pipeline (18 agents, 4 blocks)

```
Intent block:    prompt_parser → ambiguity_scorer → defaults_agent
Mesh block:      researcher ‖ architect → coder → tester → deployer → monitor_setup
Router block:    signal_collector → scorer → router
Monitor/fix:     log_watcher → anomaly_classifier → context_builder
                 → fix_agent → validator → skills_updater
```

All state flows through Redis (`TaskGraph` in `agent/shared/state.py`).
Full I/O contracts per agent → `memory/agent-contracts.md`.

---

## Architecture decisions

**Deep Agents v0.5 over CrewAI**
- Async non-blocking subagents — true parallelism for the mesh block
- Pluggable virtual filesystem backends — maps directly to `skills/` store
- LangGraph durable execution — monitor agents run indefinitely without drift
- LangSmith tracing built in — full audit per agent call
- MCP via `langchain-mcp-adapters` — no custom integration needed

**Why Redis for task graph**
- 18 agents write status concurrently; atomic hash operations prevent races
- Pub/sub for agent events — monitor block subscribes to mesh completions
- Persistent across restarts; fast enough for real-time status

**Why `skills/` is append-only**
- `SkillsStore.write_new` raises `FileExistsError` if file exists
- Agents must use `SkillsStore.append` for updates — knowledge only grows
- Fly mounts `/app/skills` as a persistent volume — survives deploys

**Why confidence router never blocks the human**
- Score > 85 + CI green + smoke tests pass → auto-merge and deploy, notify after
- Score low → async ping; human reviews when free; pipeline does not wait

**Why decision_log raises on failure**
- Agents must not proceed past irreversible actions if logging failed
- Audit trail is the debugging interface for the fix agent

---

## Key files

| Path | Role |
|------|------|
| `.agent/intent-spec.json` | Live input per run |
| `.agent/task-graph.json` | Node status template |
| `agent/orchestrator.py` | Entry point (`python -m agent.orchestrator`) |
| `agent/shared/intent_spec.py` | Load/validate/save intent; `DEFAULTS` + `REQUIRED_FIELDS` |
| `agent/shared/state.py` | `TaskGraph` (Redis) + `SkillsStore` (append-only FS) |
| `agent/shared/decision_log.py` | Append-only audit JSONL |
| `agent/intent/prompt_parser.py` | Anthropic tool-use → `ParsedGoal`; `KNOWN_DOMAINS` must match `skills/*.md` stems |
| `agent/intent/ambiguity_scorer.py` | Rule-based field scores; threshold 0.7 |
| `mcp/filesystem_server.py` | FastMCP — exposes `skills/` to external agents |

---

## Intent spec shape

```json
{
  "run_id": "unique per run",
  "goal": "natural language description",
  "integrations": ["mcp", "perplexity"],
  "deploy_target": "fly.io",
  "llm": { "provider": "anthropic", "model": "claude-sonnet-4-6", "temperature": 0 },
  "preferences": { "risk": "low", "notify": "on_failure", "auto_merge_if_ci_green": true }
}
```

---

## Build rule

One agent per commit. Implement → tests green → commit → next agent.
Commit format: `agent(<name>): unit tests green`
Never commit with `@pytest.mark.skip` still on a test class.

## Communication rule

Whenever asking the user to confirm, continue, or proceed, always state:
- What was just completed
- What the next step is (agent name, test command, and what it does)

Never end a message with "want me to keep going?" or "shall I continue?" without naming the next step explicitly.

---

## Known gaps (must fix before first deploy)

- `agent/__main__.py` missing — CI calls `python -m agent.orchestrator`
- `agent/monitor/health_server.py` missing — `fly.toml` references it
- Dockerfile CMD is `log_watcher` — misaligned with Fly multi-process config
- `.env.example` missing — no documented list of required env vars
