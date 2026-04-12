"""Unit tests for mcp/filesystem_server.py"""
from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Not implemented yet")
class TestFilesystemServer:
    def test_write_and_read_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from mcp.filesystem_server import write_skill, read_skill
        (tmp_path / "skills").mkdir()
        write_skill("test-skill", "# Test\ncontent")
        result = read_skill("test-skill")
        assert "content" in result["content"]

    def test_write_existing_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from mcp.filesystem_server import write_skill
        (tmp_path / "skills").mkdir()
        write_skill("test-skill", "content")
        with pytest.raises(Exception):
            write_skill("test-skill", "other")

    def test_append_extends_content(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from mcp.filesystem_server import write_skill, append_skill, read_skill
        (tmp_path / "skills").mkdir()
        write_skill("test-skill", "original")
        append_skill("test-skill", "\nappended")
        result = read_skill("test-skill")
        assert "original" in result["content"]
        assert "appended" in result["content"]

    def test_list_skills_returns_names(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from mcp.filesystem_server import write_skill, list_skills
        (tmp_path / "skills").mkdir()
        write_skill("skill-a", "a")
        write_skill("skill-b", "b")
        names = list_skills()
        assert "skill-a" in names
        assert "skill-b" in names
