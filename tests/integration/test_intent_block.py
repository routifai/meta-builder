"""Integration test: all 3 intent agents wired together."""
from __future__ import annotations

import pytest


class TestIntentBlock:
    def test_raw_goal_to_intent_spec_pipeline(self):
        """prompt_parser -> ambiguity_scorer -> defaults_agent produces valid IntentSpec."""
        from agent.intent.prompt_parser import parse_prompt
        from agent.intent.ambiguity_scorer import score_unknowns
        from agent.intent.defaults_agent import fill_defaults
        from agent.shared.intent_spec import validate

        raw = "build an MCP server for Perplexity search and deploy to fly.io"
        parsed = parse_prompt(raw)
        scored = score_unknowns(parsed)
        spec = fill_defaults(scored, parsed)
        validated = validate(spec)

        assert validated["raw_goal"] == raw
        assert validated["deploy_target"] is not None

    def test_intent_block_output_saved_to_disk(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".agent").mkdir()

        from agent.intent.prompt_parser import parse_prompt
        from agent.intent.ambiguity_scorer import score_unknowns
        from agent.intent.defaults_agent import fill_defaults
        from agent.shared.intent_spec import save, INTENT_SPEC_PATH

        raw = "build a REST API with postgres and deploy to AWS"
        parsed = parse_prompt(raw)
        scored = score_unknowns(parsed)
        spec = fill_defaults(scored, parsed)
        save(spec)

        assert INTENT_SPEC_PATH.exists()
