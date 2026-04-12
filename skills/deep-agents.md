# Deep Agents v0.5

## Source
https://docs.langchain.com/oss/python/deepagents/overview

## Installation

```bash
pip install -qU deepagents
```

## Core API

### `create_deep_agent()`

Primary factory function. Returns a compiled LangGraph agent.

```python
from deepagents import create_deep_agent

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",   # provider:model string
    tools=[my_tool_fn],                     # plain Python functions
    system_prompt="You are ...",
    backend=FilesystemBackend(root_dir="."),
    skills=["/skills/"],                    # skill directories to load
    subagents=[researcher_subagent],
    checkpointer=checkpointer,             # required for persistence
)

result = agent.invoke(
    {"messages": [{"role": "user", "content": "..."}]},
    config={"configurable": {"thread_id": "run-123"}},
)
print(result["messages"][-1].content)
```

Supported model string format: `"anthropic:claude-sonnet-4-6"`, `"openai:gpt-5.4"`.  
Alternatively pass an initialized `ChatAnthropic` instance directly.

### Async invocation

```python
result = await agent.ainvoke(
    {"messages": [{"role": "user", "content": "..."}]},
    config={"configurable": {"thread_id": "run-123"}},
)
```

---

## Built-in Tools

The agent automatically has access to:

| Tool | Description |
|------|-------------|
| `write_todos` | Break tasks into discrete steps (planning) |
| `ls` | List directory contents |
| `read_file` | Read a file from the virtual filesystem |
| `write_file` | Write a file |
| `edit_file` | Edit a file (old_string → new_string) |
| `glob` | Glob pattern match across paths |
| `grep` | Search file contents |
| `execute` | Run shell commands (sandbox-dependent) |
| `task` | Spawn a named subagent |

---

## Subagents

### Dictionary-based (most common)

```python
researcher = {
    "name": "researcher",
    "description": "Used for deep research tasks",     # agent uses this to match
    "system_prompt": "You are an expert researcher.",
    "tools": [internet_search],
    "model": "anthropic:claude-opus-4-6",              # optional override
    "skills": ["/skills/research/"],                   # does NOT inherit parent
}

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    subagents=[researcher],
)
```

### CompiledSubAgent (for complex LangGraph workflows)

```python
from deepagents import CompiledSubAgent

custom = CompiledSubAgent(
    name="data-analyzer",
    description="Specialized data analysis agent",
    runnable=my_compiled_langgraph,
)
```

### Isolation rules

- System prompt: **not** inherited — must be defined per subagent
- Tools: **not** inherited — explicitly specify
- Skills: **not** inherited for custom subagents; general-purpose subagents inherit parent skills
- Permissions: defaults to parent; `permissions` key **replaces entirely** (not merges)
- Model: defaults to parent model unless overridden

### Output contract

Subagents should return concise summaries. The parent receives only the final result, not intermediate tool outputs. The `task()` tool call blocks until the subagent completes (synchronous from the parent's perspective).

---

## Backends (Virtual Filesystem)

Pass one backend instance to `create_deep_agent(backend=...)`.

### Available backends

```python
from deepagents.backends import (
    StateBackend,       # ephemeral, in LangGraph state (default)
    FilesystemBackend,  # real files under root_dir
    StoreBackend,       # durable via LangGraph BaseStore (Redis, Postgres, etc.)
    LocalShellBackend,  # filesystem + shell exec on host
    CompositeBackend,   # route paths to different backends
)
```

### FilesystemBackend — recommended for this project

```python
from deepagents.backends.filesystem import FilesystemBackend

backend = FilesystemBackend(
    root_dir="/path/to/project",
    virtual_mode=True,   # ALWAYS set True — blocks traversal outside root_dir
)
```

### CompositeBackend — hybrid routing

```python
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend

backend = CompositeBackend(
    default=StateBackend(),
    routes={"/skills/": StoreBackend()},  # persist skills/ across threads
)
```

### Custom backend

Subclass `BackendProtocol` and implement: `ls`, `read`, `write`, `edit`, `glob`, `grep`.

**Gotcha:** `write` has create-only semantics on some backends. Use `edit` for in-place modification. Return structured `ReadResult(error=...)` / `WriteResult(...)` rather than raising exceptions.

---

## Skills System

Skills are directories with a `SKILL.md` file. Agents load them lazily (progressive disclosure: match description → read full file → execute).

### File structure

```
skills/
└── mcp-protocol/
    ├── SKILL.md          # required — frontmatter + instructions
    └── reference.py      # optional supporting files
```

### SKILL.md format

```markdown
---
name: mcp-protocol
description: "How to build MCP servers in Python: FastMCP decorators, tool schema, stdio/HTTP transport, request lifecycle."
license: MIT
allowed-tools: read_file, write_file
metadata:
  version: "1.0"
---
# Instructions
...
```

**Critical:** `description` must be precise — agents select skills based solely on this field. Max 1024 chars. Files must be < 10 MB. Later skill sources with identical names override earlier ones.

### Registering skills with an agent

```python
# FilesystemBackend: point to directory on disk
agent = create_deep_agent(
    backend=FilesystemBackend(root_dir="/project"),
    skills=["/project/skills/"],
    checkpointer=checkpointer,
)

# StateBackend: inject file data directly
from deepagents.backends.utils import create_file_data

files = {"/skills/mcp-protocol/SKILL.md": create_file_data(skill_md_content)}
result = agent.invoke(
    {"messages": [...], "files": files},
    config={"configurable": {"thread_id": "t1"}},
)
```

---

## LangSmith Tracing

```bash
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY="..."
```

All agent calls, subagent spawns, and tool invocations are traced automatically. No code changes required.

---

## Permissions

```python
from deepagents import FilesystemPermission

agent = create_deep_agent(
    permissions=[
        FilesystemPermission(path="/project/skills/", read=True, write=True),
        FilesystemPermission(path="/project/.env",    read=False, write=False),
    ]
)
```

Subagent `permissions` key **replaces** parent permissions entirely.

---

## Gotchas

- **Backend factory pattern is deprecated.** Pass pre-constructed instances directly; don't pass callables.
- **Subagent isolation is total.** If a subagent needs a skill, explicitly pass `skills=[...]` to it.
- **`task()` is synchronous from the parent's view.** The parent blocks until the subagent returns. Design subagents to return concise summaries, not raw data.
- **`execute` requires a sandbox backend.** `FilesystemBackend` and `LocalShellBackend` grant real host access — use `virtual_mode=True` and exclude `.env` from accessible paths.
- **`checkpointer` is required for persistence.** Without it, thread history is not retained across calls.
