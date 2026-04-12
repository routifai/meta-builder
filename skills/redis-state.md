# Redis State — Task Graph Patterns

## Installation

```bash
pip install redis[asyncio]   # includes asyncio support
```

---

## Async client (primary pattern for this project)

```python
import redis.asyncio as redis

# Single client (use across the process lifetime)
r = redis.from_url("redis://localhost:6379", decode_responses=True)

# With connection pool (recommended for agents making concurrent calls)
pool = redis.ConnectionPool.from_url("redis://localhost:6379", decode_responses=True, max_connections=20)
r = redis.Redis(connection_pool=pool)

# Always close on shutdown
await r.aclose()
```

---

## Task graph key schema

Use a consistent, readable namespace. Recommended schema for this project:

```
task-graph:{run_id}:node:{agent_name}         # hash — per-agent status
task-graph:{run_id}:meta                       # hash — run-level metadata
task-graph:{run_id}:events                     # list — ordered event log
task-graph:{run_id}:locks:{agent_name}         # string — distributed lock
intent:{run_id}                                # string (JSON) — intent spec
decision-log:{run_id}:{agent_name}:{timestamp} # string — decision entry
```

---

## Hash operations for agent nodes

```python
# Write agent status
await r.hset(f"task-graph:{run_id}:node:researcher", mapping={
    "status": "running",        # pending | running | done | failed
    "started_at": "2026-04-10T12:00:00Z",
    "retries": "0",
    "output_ref": "",           # path to artifact or summary
})

# Read full node
node = await r.hgetall(f"task-graph:{run_id}:node:researcher")
# {"status": "running", "started_at": "...", ...}

# Update single field
await r.hset(f"task-graph:{run_id}:node:researcher", "status", "done")

# Increment counter atomically
await r.hincrby(f"task-graph:{run_id}:node:researcher", "retries", 1)

# Check if field exists
exists = await r.hexists(f"task-graph:{run_id}:node:researcher", "output_ref")
```

---

## Atomic pipeline operations

Use pipelines when multiple operations must be sent together (reduces round-trips) or must be atomic (use `transaction=True`).

```python
# Batch (not atomic — but single round-trip)
pipe = r.pipeline()
pipe.hset(f"task-graph:{run_id}:node:coder", "status", "running")
pipe.hset(f"task-graph:{run_id}:node:tester", "status", "running")
pipe.hset(f"task-graph:{run_id}:node:deployer", "status", "running")
await pipe.execute()

# Atomic transaction (MULTI/EXEC — all or nothing)
async with r.pipeline(transaction=True) as pipe:
    pipe.hset(f"task-graph:{run_id}:node:coder", "status", "done")
    pipe.hset(f"task-graph:{run_id}:meta", "last_completed", "coder")
    await pipe.execute()
```

### WATCH for optimistic locking (compare-and-set pattern)

```python
async with r.pipeline(transaction=True, watches=[key]) as pipe:
    current = await pipe.hget(key, "status")
    if current != "pending":
        return  # someone else already claimed it
    pipe.multi()
    pipe.hset(key, "status", "running")
    await pipe.execute()   # raises WatchError if key changed since WATCH
```

---

## Pub/Sub — agent coordination

Use pub/sub to notify waiting agents when upstream work completes.

```python
# Publisher (e.g. researcher agent signals completion)
await r.publish(f"events:{run_id}", json.dumps({
    "event": "agent_done",
    "agent": "researcher",
    "run_id": run_id,
}))

# Subscriber (e.g. architect waits for researcher)
async def wait_for_researcher(run_id: str):
    pubsub = r.pubsub()
    await pubsub.subscribe(f"events:{run_id}")
    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        data = json.loads(message["data"])
        if data["event"] == "agent_done" and data["agent"] == "researcher":
            await pubsub.unsubscribe()
            return data
```

---

## TTL strategy

| Key type | TTL | Reason |
|----------|-----|--------|
| `task-graph:{run_id}:*` | 7 days | Retain for post-run audit |
| `intent:{run_id}` | 7 days | Needed by monitor/fix loop |
| `task-graph:{run_id}:locks:*` | 60s | Prevent deadlock if holder crashes |
| `decision-log:*` | 30 days | Compliance / audit trail |

```python
# Set TTL on a key
await r.expire(f"task-graph:{run_id}:locks:coder", 60)

# Set with TTL in one command
await r.set(f"task-graph:{run_id}:locks:coder", "agent-host-1", ex=60)

# Get remaining TTL
ttl = await r.ttl(f"task-graph:{run_id}:locks:coder")
```

---

## Distributed lock pattern (for fix agent — never two patches simultaneously)

```python
import uuid

lock_key = f"task-graph:{run_id}:locks:fix-agent"
lock_val = str(uuid.uuid4())

# Acquire
acquired = await r.set(lock_key, lock_val, nx=True, ex=120)  # nx=only if not exists
if not acquired:
    raise RuntimeError("Another fix agent is running for this run")

try:
    # do the fix work
    ...
finally:
    # Release only if we own the lock (Lua script for atomicity)
    script = """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("del", KEYS[1])
    else
        return 0
    end
    """
    await r.eval(script, 1, lock_key, lock_val)
```

---

## Reading the full task graph (signal collector)

```python
import asyncio

async def read_task_graph(run_id: str) -> dict:
    agent_names = [
        "prompt_parser", "ambiguity_scorer", "defaults_agent",
        "researcher", "architect", "coder", "tester", "deployer", "monitor_setup",
        "signal_collector", "scorer", "router",
        "log_watcher", "anomaly_classifier", "context_builder",
        "fix_agent", "validator", "skills_updater",
    ]
    pipe = r.pipeline()
    for name in agent_names:
        pipe.hgetall(f"task-graph:{run_id}:node:{name}")
    results = await pipe.execute()
    return dict(zip(agent_names, results))
```

---

## Environment variables

```
REDIS_URL=redis://localhost:6379        # local dev
REDIS_URL=redis://:password@host:6379  # production with auth
REDIS_URL=rediss://host:6380           # TLS
```

---

## Gotchas

- **`decode_responses=True`** — always set this. Without it, all values are bytes.
- **Pipelines are not transactions by default.** Use `pipeline(transaction=True)` for atomic multi-key operations.
- **Pub/Sub connection is dedicated.** Do not reuse the main `r` client for pub/sub — use a separate connection.
- **WATCH + MULTI/EXEC = optimistic lock.** If the watched key changes between WATCH and EXEC, `execute()` raises `WatchError`. Retry in a loop.
- **TTL on lock keys is not optional.** If an agent crashes while holding a lock with no TTL, the lock is held forever.
- **`eval` for atomic Lua scripts.** For the release-lock pattern above, plain GET + DEL is not atomic — always use the Lua script.
