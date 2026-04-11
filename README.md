# meta-builder

A fully autonomous software delivery system. Write a one-sentence goal. The system researches, architects, codes, tests, deploys, monitors, and self-heals — permanently, without asking for help.

---

## How it works

```
Human writes a goal
        ↓
  Intent resolver         parse → score → fill defaults → IntentSpec
        ↓
  Parallel agent mesh     researcher + architect + coder + tester + deployer (concurrent)
        ↓
  Router                  score CI signals → auto-merge or async ping
        ↓
  Monitor / fix loop      watch logs → classify → patch → validate → update skills (forever)
```

**17 agents. 4 blocks. One human input.**

---

## Project structure

```
agent/
  orchestrator.py         entry point — reads intent spec, fires mesh
  intent/                 prompt_parser · ambiguity_scorer · defaults_agent
  mesh/                   researcher · architect · coder · tester · deployer · monitor_setup
  router/                 signal_collector · scorer · router
  monitor/                log_watcher · anomaly_classifier · context_builder · fix_agent · validator · skills_updater
  shared/                 state (Redis task graph) · intent_spec · decision_log

skills/                   compounding knowledge base — agents read and write here
mcp/                      MCP servers: github · web_search · filesystem
.agent/                   task-graph.json · intent-spec.json (runtime state)
.github/workflows/        agent-build.yml · agent-fix.yml
docker/                   Dockerfile.agent
tests/                    unit + integration tests per agent and block
```

---

## Stack

| Layer | Technology |
|---|---|
| Agent framework | [Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview) (LangGraph runtime) |
| LLM calls | Anthropic SDK — `claude-sonnet-4-6` |
| Tool protocol | MCP (stdio transport) |
| Shared state | Redis task graph + disk `skills/` |
| Ephemeral agents | GitHub Actions |
| Persistent workers | Fly.io (monitor + fix loop, always-on) |
| Tracing | LangSmith |

---

## Setup

```bash
git clone git@github.com:routifai/meta-builder.git
cd meta-builder
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in your keys
```

**Required env vars** (see `.env.example`):
- `ANTHROPIC_API_KEY`
- `REDIS_URL`
- `GITHUB_TOKEN` + `GITHUB_REPO`
- `LANGSMITH_API_KEY` (optional but recommended)

---

## Running tests

```bash
# Full suite
pytest tests/ -v

# Shared layer only
pytest tests/unit/shared/ -v

# Single agent
pytest tests/unit/intent/test_prompt_parser.py -v
```

---

## Build progress

| Block | Agents | Status |
|---|---|---|
| Intent resolver | prompt_parser, ambiguity_scorer, defaults_agent | 🔄 in progress |
| Parallel mesh | researcher, architect, coder, tester, deployer, monitor_setup | 🔲 stub |
| Router | signal_collector, scorer, router | 🔲 stub |
| Monitor / fix loop | log_watcher, anomaly_classifier, context_builder, fix_agent, validator, skills_updater | 🔲 stub |

---

## Design principles

- **Skills-first** — before writing code, agents research and write `skills/` docs. Knowledge compounds across runs.
- **Intent spec replaces gates** — one structured spec at the start; agents fill gaps with defaults. Human only surfaces for genuine blockers.
- **Parallel mesh** — researcher and architect run concurrently; tester writes tests while coder writes code.
- **Human as stakeholder** — not in the critical path. Auto-merges when CI is green. Async ping when confidence is low.
- **Self-healing** — monitor watches production forever. Patches are written, validated, and merged automatically when confidence > 85.
- **Decision log** — every irreversible action (deploy, merge, PR) is written to `decision-log/` before it happens. Full audit trail.
