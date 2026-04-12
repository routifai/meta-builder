"""
Shared state — Redis task graph + skills/ filesystem interface.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, TypedDict

import redis.asyncio as redis

AgentStatus = Literal["pending", "running", "done", "failed"]

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")

ALL_AGENTS = [
    "prompt_parser", "ambiguity_scorer", "defaults_agent",
    "researcher", "architect", "coder", "tester", "deployer", "monitor_setup",
    "signal_collector", "scorer", "router",
    "log_watcher", "anomaly_classifier", "context_builder",
    "fix_agent", "validator", "skills_updater",
]


class NodeState(TypedDict):
    status: AgentStatus
    started_at: str | None
    finished_at: str | None
    retries: int
    output_ref: str


class TaskGraph:
    """Redis-backed task graph. Each agent node is stored as a Redis hash."""

    def __init__(self, run_id: str, redis_url: str = REDIS_URL):
        self.run_id = run_id
        self.redis_url = redis_url
        self._client: redis.Redis | None = None

    def _node_key(self, agent: str) -> str:
        return f"task-graph:{self.run_id}:node:{agent}"

    def _events_channel(self) -> str:
        return f"events:{self.run_id}"

    async def connect(self) -> None:
        self._client = redis.from_url(self.redis_url, decode_responses=True)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    async def set_status(self, agent: str, status: AgentStatus, **extra) -> None:
        mapping: dict[str, str] = {"status": status}
        mapping.update({k: str(v) for k, v in extra.items()})
        await self._client.hset(self._node_key(agent), mapping=mapping)

    async def get_node(self, agent: str) -> NodeState:
        raw = await self._client.hgetall(self._node_key(agent))
        return NodeState(
            status=raw.get("status", "pending"),
            started_at=raw.get("started_at") or None,
            finished_at=raw.get("finished_at") or None,
            retries=int(raw.get("retries", 0)),
            output_ref=raw.get("output_ref", ""),
        )

    async def get_all(self) -> dict[str, NodeState]:
        pipe = self._client.pipeline()
        for agent in ALL_AGENTS:
            pipe.hgetall(self._node_key(agent))
        results = await pipe.execute()
        output: dict[str, NodeState] = {}
        for agent, raw in zip(ALL_AGENTS, results):
            output[agent] = NodeState(
                status=raw.get("status", "pending"),
                started_at=raw.get("started_at") or None,
                finished_at=raw.get("finished_at") or None,
                retries=int(raw.get("retries", 0)),
                output_ref=raw.get("output_ref", ""),
            )
        return output

    async def publish_event(self, event: dict) -> None:
        await self._client.publish(self._events_channel(), json.dumps(event))


class SkillsStore:
    """Append-only filesystem interface for skills/ directory."""

    def __init__(self, skills_dir: str = "skills"):
        self.skills_dir = Path(skills_dir)

    def _path(self, name: str) -> Path:
        return self.skills_dir / f"{name}.md"

    def read(self, skill_name: str) -> str:
        path = self._path(skill_name)
        if not path.exists():
            raise FileNotFoundError(f"Skill not found: {skill_name!r}")
        return path.read_text()

    def append(self, skill_name: str, content: str) -> None:
        """Append content to an existing skill doc. Never overwrites."""
        path = self._path(skill_name)
        if not path.exists():
            raise FileNotFoundError(f"Skill not found: {skill_name!r}")
        with path.open("a") as f:
            f.write(content)

    def write_new(self, skill_name: str, content: str) -> None:
        """Create a new skill doc. Raises FileExistsError if file already exists."""
        path = self._path(skill_name)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError(f"Skill already exists: {skill_name!r}")
        path.write_text(content)

    def list_skills(self) -> list[str]:
        if not self.skills_dir.exists():
            return []
        return [p.stem for p in sorted(self.skills_dir.glob("*.md"))]
