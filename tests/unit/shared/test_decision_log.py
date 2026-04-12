"""Unit tests for agent/shared/decision_log.py"""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from agent.shared.decision_log import write, read_all, DecisionEntry


class TestWrite:
    def test_happy_path_creates_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        path = write(
            run_id="r1",
            agent="prompt_parser",
            action="extract entities from goal",
            reasoning="goal string received",
            inputs_summary="raw_goal='build mcp server'",
            reversible=True,
        )
        assert path.exists()

    def test_file_contains_valid_json(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        path = write(
            run_id="r1",
            agent="prompt_parser",
            action="test action",
            reasoning="test reason",
            inputs_summary="summary",
        )
        entry = json.loads(path.read_text())
        assert entry["run_id"] == "r1"
        assert entry["agent"] == "prompt_parser"
        assert "timestamp" in entry

    def test_irreversible_write_failure_raises(self, tmp_path, monkeypatch):
        """If writing fails for an irreversible action, RuntimeError must be raised."""
        monkeypatch.chdir(tmp_path)
        # Make decision-log dir read-only to force write failure
        log_dir = tmp_path / "decision-log"
        log_dir.mkdir(parents=True)
        log_dir.chmod(0o444)
        with pytest.raises(RuntimeError):
            write(
                run_id="r1",
                agent="fix_agent",
                action="open PR",
                reasoning="patch ready",
                inputs_summary="files=['main.py']",
                reversible=False,
            )
        log_dir.chmod(0o755)

    def test_multiple_writes_create_separate_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        p1 = write("r1", "agent_a", "action1", "reason1", "s1")
        p2 = write("r1", "agent_a", "action2", "reason2", "s2")
        assert p1 != p2


class TestReadAll:
    def test_returns_sorted_by_timestamp(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        write("r1", "agent_a", "first", "reason", "s")
        write("r1", "agent_b", "second", "reason", "s")
        entries = read_all("r1")
        assert len(entries) >= 2
        timestamps = [e["timestamp"] for e in entries]
        assert timestamps == sorted(timestamps)

    def test_empty_run_returns_empty_list(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        entries = read_all("nonexistent-run")
        assert entries == []

    def test_entries_match_written_data(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        write("r1", "fix_agent", "open PR #42", "patch validated", "conf=91")
        entries = read_all("r1")
        assert any(e["action"] == "open PR #42" for e in entries)
