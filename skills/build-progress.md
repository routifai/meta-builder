# build-progress

Live build log for the meta-builder project. Append a new entry at the end of each session.

---

## Session 1 — 2026-04-10

**Completed agents:** `prompt_parser`, `ambiguity_scorer`, `defaults_agent`

**Block 1 (Intent) fully green.**

| Agent | Tests | Commit |
|-------|-------|--------|
| `prompt_parser` | 15/15 | `df07e46` |
| `ambiguity_scorer` | 8/8 | `3df71e3` |
| `defaults_agent` | 7/7 | `89aa124` |

**Infrastructure built:**
- `agent/shared/intent_spec.py` — validate/load/save, REQUIRED_FIELDS, DEFAULTS
- `agent/shared/decision_log.py` — append-only JSONL audit log
- `agent/shared/state.py` — TaskGraph (Redis) + SkillsStore (append-only FS)
- `pyproject.toml` — setuptools, pytest, ruff configured
- Git remote: `git@github.com:routifai/meta-builder.git`

**Known gaps opened:**
- `agent/__main__.py` missing
- `agent/monitor/health_server.py` missing

---

## Session 2 — 2026-04-11

**Completed agents:** `researcher`

**Search layer added:** Tavily primary / Anthropic built-in `web_search_20260209` fallback (`agent/shared/search.py`).

| Agent | Tests | Commit |
|-------|-------|--------|
| `researcher` | 4/4 | `95e6779` |

**Functional smoke harness added:**
- `scripts/smoke.py` — live CLI runner, feeds real goals through the pipeline
- `tests/functional/` — session-scoped fixtures, 30 real-API assertions
- `tests/functional/conftest.py` — `pipeline_run` + `pipeline_run_mcp` session fixtures

**Gaps found by smoke run and fixed (`2696d99`):**
1. Unmapped `build_target` values silently dropped from research — added raw-slug fallback
2. Domain research was sequential — switched to `asyncio.gather` (concurrent)
3. Unit tests wrote to real `skills/` dir — fixed to use `tmp_path` via `skills_dir=` param
4. `test_domains_cover_integrations` always skipped — added `TestMCPPipelineResearch` class

---

## Session 3 — 2026-04-12

**Completed agents:** `architect`

**Mesh block integration test unskipped:** researcher ‖ architect now run concurrently in test.

| Agent | Tests | Commit |
|-------|-------|--------|
| `architect` | 4/4 unit + 1 integration | `(pending)` |

**Architect design:**
- Anthropic SDK tool use with `tool_choice` forced to `define_architecture`
- Loads pre-existing skill docs from `skills_dir` for domain context
- Runs concurrently with researcher (receives empty `research_result` in production)
- Returns `file_tree`, `module_interfaces`, `dependencies`, `tech_choices`

**Functional tests added:** `tests/functional/test_architect_output.py` — 10 tests
- Shape assertions (file_tree is list[str], every module has input/output, etc.)
- Domain coherence (tech_choices reference the build_target and integrations)
- Insight: architect runs without research output — alignment test was wrong, corrected to test standalone coherence

**Current pipeline coverage (functional):**
```
prompt_parser → ambiguity_scorer → defaults_agent → [researcher ‖ architect]
```

**Agents remaining:** coder, tester, deployer, monitor_setup, signal_collector,
scorer, router, log_watcher, anomaly_classifier, context_builder, fix_agent,
validator, skills_updater (13 agents)

---

## Running counts

| Category | Done | Remaining |
|----------|------|-----------|
| Intent agents | 3/3 | 0 |
| Mesh agents | 2/6 | 4 |
| Router agents | 0/3 | 3 |
| Monitor agents | 0/6 | 6 |
| MCP servers | 0/3 | 3 |
| Orchestrator | 0/1 | 1 |
| **Total** | **5/22** | **17** |

---

## Session 3 addendum — pivot-back design + smoke fix

**Problem found:** smoke.py was stale (stopped after researcher, architect not wired in). No test had ever run all 5 built agents in a real chain with data actually flowing between them.

**Full 5-agent smoke run confirmed working.** New `scripts/smoke.py` chains all implemented stages, detects stubs gracefully, prints a per-stage summary at the end.

**Pivot-back capability added:** `agent/shared/knowledge.py`
- `fill_knowledge_gap(domain, question, intent_spec, skills_dir)` — checks SkillsStore first (fast path), researches on-demand if missing (slow path ~5s)
- `get_knowledge_tool_definition()` — Anthropic tool schema; coder passes this in its `tools=` list
- Race condition safe (concurrent coroutines can both hit the slow path — second write is caught, existing file returned)
- 8/8 unit tests green, no API calls needed (all mocked)

**Design decision:** Coder will get `fill_knowledge_gap` as a callable tool in its Anthropic message loop. When it needs to know the FastMCP tool registration API, it calls the tool, gets the skill content, then writes the code. No orchestrator involvement.

---

## How to run

```bash
# Live smoke run
python scripts/smoke.py "build an MCP server for Perplexity search and deploy to fly.io"

# Full test suite (unit only, fast)
pytest tests/unit/ -v

# Functional verification (real API, ~45s)
pytest tests/functional/ -v

# Integration tests (real API)
pytest tests/integration/ -v
```
