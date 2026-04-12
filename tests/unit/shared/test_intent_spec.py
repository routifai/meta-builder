"""Unit tests for agent/shared/intent_spec.py"""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from agent.shared.intent_spec import validate, load, save, DEFAULTS, REQUIRED_FIELDS, IntentSpec


class TestValidate:
    def test_happy_path_full_spec(self, sample_intent_spec):
        result = validate(sample_intent_spec)
        assert result["run_id"] == "test-run-001"
        assert result["build_target"] == "mcp-server"

    def test_defaults_applied_for_missing_optional_fields(self, sample_intent_spec):
        del sample_intent_spec["llm_provider"]
        del sample_intent_spec["llm_model"]
        result = validate(sample_intent_spec)
        assert result["llm_provider"] == DEFAULTS["llm_provider"]
        assert result["llm_model"] == DEFAULTS["llm_model"]

    def test_missing_required_field_raises(self, sample_intent_spec):
        del sample_intent_spec["run_id"]
        with pytest.raises(ValueError, match="run_id"):
            validate(sample_intent_spec)

    def test_missing_raw_goal_raises(self, sample_intent_spec):
        del sample_intent_spec["raw_goal"]
        with pytest.raises(ValueError):
            validate(sample_intent_spec)

    def test_invalid_risk_tolerance_raises(self, sample_intent_spec):
        sample_intent_spec["risk_tolerance"] = "yolo"
        with pytest.raises(ValueError, match="risk_tolerance"):
            validate(sample_intent_spec)

    def test_invalid_notification_preference_raises(self, sample_intent_spec):
        sample_intent_spec["notification_preference"] = "always"
        with pytest.raises(ValueError, match="notification_preference"):
            validate(sample_intent_spec)

    def test_empty_dict_raises(self):
        with pytest.raises(ValueError):
            validate({})

    def test_output_contains_all_required_fields(self, sample_intent_spec):
        result = validate(sample_intent_spec)
        for field in REQUIRED_FIELDS:
            assert field in result, f"Missing field: {field}"

    def test_integrations_is_list(self, sample_intent_spec):
        result = validate(sample_intent_spec)
        assert isinstance(result["integrations"], list)

    def test_llm_base_url_defaults_to_none(self, sample_intent_spec):
        sample_intent_spec.pop("llm_base_url", None)
        result = validate(sample_intent_spec)
        assert result["llm_base_url"] is None


class TestLoadSave:
    def test_save_then_load_roundtrip(self, sample_intent_spec, tmp_path):
        path = tmp_path / "intent-spec.json"
        save(sample_intent_spec, path=path)
        loaded = load(path=path)
        assert loaded["run_id"] == sample_intent_spec["run_id"]

    def test_load_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load(path=tmp_path / "nonexistent.json")

    def test_save_writes_valid_json(self, sample_intent_spec, tmp_path):
        path = tmp_path / "spec.json"
        save(sample_intent_spec, path=path)
        raw = json.loads(path.read_text())
        assert raw["run_id"] == sample_intent_spec["run_id"]
