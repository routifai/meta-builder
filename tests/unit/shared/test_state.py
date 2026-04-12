"""Unit tests for agent/shared/state.py"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch
from agent.shared.state import TaskGraph, SkillsStore


class TestTaskGraph:
    @pytest.mark.asyncio
    async def test_set_and_get_status(self, mock_redis, run_id):
        mock_redis.hgetall.return_value = {
            "status": "running",
            "started_at": "2026-04-10T00:00:00Z",
            "finished_at": "",
            "retries": "0",
            "output_ref": "",
        }
        with patch("agent.shared.state.redis") as mock_redis_module:
            mock_redis_module.from_url.return_value = mock_redis
            tg = TaskGraph(run_id)
            await tg.connect()
            await tg.set_status("researcher", "running")
            node = await tg.get_node("researcher")
            assert node["status"] == "running"

    @pytest.mark.asyncio
    async def test_get_all_returns_all_agents(self, mock_redis, run_id):
        mock_redis.pipeline.return_value.__aenter__ = AsyncMock(return_value=mock_redis)
        mock_redis.pipeline.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_redis.execute = AsyncMock(return_value=[{} for _ in range(18)])
        with patch("agent.shared.state.redis") as mock_redis_module:
            mock_redis_module.from_url.return_value = mock_redis
            tg = TaskGraph(run_id)
            await tg.connect()
            result = await tg.get_all()
            assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_publish_event_calls_redis_publish(self, mock_redis, run_id):
        with patch("agent.shared.state.redis") as mock_redis_module:
            mock_redis_module.from_url.return_value = mock_redis
            tg = TaskGraph(run_id)
            await tg.connect()
            await tg.publish_event({"event": "agent_done", "agent": "researcher"})
            mock_redis.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_uses_redis_url(self, run_id):
        with patch("agent.shared.state.redis") as mock_redis_module:
            mock_redis_module.from_url.return_value = AsyncMock()
            tg = TaskGraph(run_id, redis_url="redis://testhost:6379")
            await tg.connect()
            mock_redis_module.from_url.assert_called_with(
                "redis://testhost:6379", decode_responses=True
            )


class TestSkillsStore:
    def test_write_new_creates_file(self, tmp_path):
        store = SkillsStore(skills_dir=str(tmp_path))
        store.write_new("test-skill", "# Test\nContent here")
        assert (tmp_path / "test-skill.md").exists()

    def test_write_new_raises_if_exists(self, tmp_path):
        store = SkillsStore(skills_dir=str(tmp_path))
        store.write_new("test-skill", "content")
        with pytest.raises(FileExistsError):
            store.write_new("test-skill", "other content")

    def test_read_returns_content(self, tmp_path):
        store = SkillsStore(skills_dir=str(tmp_path))
        store.write_new("test-skill", "# Skill\ncontent")
        content = store.read("test-skill")
        assert "content" in content

    def test_append_adds_to_existing(self, tmp_path):
        store = SkillsStore(skills_dir=str(tmp_path))
        store.write_new("test-skill", "original")
        store.append("test-skill", "\n## Gotchas\n- new gotcha")
        content = store.read("test-skill")
        assert "original" in content
        assert "new gotcha" in content

    def test_append_does_not_overwrite(self, tmp_path):
        store = SkillsStore(skills_dir=str(tmp_path))
        store.write_new("test-skill", "original content")
        store.append("test-skill", " appended")
        content = store.read("test-skill")
        assert content.startswith("original content")

    def test_list_skills_returns_names(self, tmp_path):
        store = SkillsStore(skills_dir=str(tmp_path))
        store.write_new("skill-a", "a")
        store.write_new("skill-b", "b")
        names = store.list_skills()
        assert "skill-a" in names
        assert "skill-b" in names

    def test_read_missing_skill_raises(self, tmp_path):
        store = SkillsStore(skills_dir=str(tmp_path))
        with pytest.raises(FileNotFoundError):
            store.read("nonexistent")
