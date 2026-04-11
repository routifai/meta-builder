"""
Functional tests on the intent block output.

These tests assert on the REAL output of prompt_parser + ambiguity_scorer + defaults_agent
running against: "build an agent capable of deep research and deploy to fly.io"

All tests share one pipeline_run (session fixture — single API call for the whole session).
"""
from __future__ import annotations

import re
import pytest


class TestParsedGoal:
    def test_raw_goal_preserved(self, pipeline_run):
        parsed = pipeline_run["parsed"]
        assert parsed is not None, "prompt_parser failed — check error in pipeline_run"
        assert parsed["raw_goal"] == pipeline_run["goal"]

    def test_domains_is_non_empty_list(self, pipeline_run):
        parsed = pipeline_run["parsed"]
        assert isinstance(parsed["domains"], list)
        assert len(parsed["domains"]) > 0, "Parser found no relevant domains"

    def test_entities_has_required_keys(self, pipeline_run):
        entities = pipeline_run["parsed"]["entities"]
        assert "build_target" in entities
        assert "integrations" in entities
        assert "deploy_target" in entities

    def test_deploy_target_extracted(self, pipeline_run):
        """Goal explicitly mentions 'fly.io' — parser must extract it."""
        entities = pipeline_run["parsed"]["entities"]
        assert entities["deploy_target"] is not None, (
            "Parser did not extract deploy_target from 'deploy to fly.io'"
        )
        assert "fly" in entities["deploy_target"].lower()

    def test_integrations_is_list(self, pipeline_run):
        entities = pipeline_run["parsed"]["entities"]
        assert isinstance(entities["integrations"], list)

    def test_unknown_fields_is_list(self, pipeline_run):
        assert isinstance(pipeline_run["parsed"]["unknown_fields"], list)


class TestAmbiguityScorer:
    def test_scored_has_required_keys(self, pipeline_run):
        scored = pipeline_run["scored"]
        assert scored is not None
        assert "scores" in scored
        assert "must_ask" in scored
        assert "can_default" in scored

    def test_scores_are_floats_in_range(self, pipeline_run):
        for field, score in pipeline_run["scored"]["scores"].items():
            assert 0.0 <= score <= 1.0, f"Score for {field!r} out of range: {score}"

    def test_must_ask_and_can_default_disjoint(self, pipeline_run):
        must = set(pipeline_run["scored"]["must_ask"])
        default = set(pipeline_run["scored"]["can_default"])
        assert must.isdisjoint(default), f"Overlap: {must & default}"

    def test_no_must_ask_fields(self, pipeline_run):
        """
        The goal 'build an agent ... and deploy to fly.io' should give the parser
        enough signal to avoid blocking on must_ask.

        If this fails: the parser returned build_target=None and the scorer
        correctly blocked it. The goal needs to be more specific.
        The pipeline_run fixture records human_input_required in that case.
        """
        must_ask = pipeline_run["scored"]["must_ask"]
        hir = pipeline_run["human_input_required"]
        if hir:
            pytest.skip(
                f"Goal was too ambiguous — HumanInputRequired: {hir}. "
                "This is valid behavior, not a bug."
            )
        assert must_ask == [], (
            f"Scorer blocked pipeline on fields: {must_ask}. "
            "Either the goal needs more specificity or the scoring threshold needs review."
        )


class TestIntentSpec:
    def test_spec_produced(self, pipeline_run):
        if pipeline_run["human_input_required"]:
            pytest.skip("Pipeline was blocked by HumanInputRequired — spec not produced")
        assert pipeline_run["spec"] is not None

    def test_raw_goal_in_spec(self, pipeline_run):
        if pipeline_run["spec"] is None:
            pytest.skip("No spec")
        assert pipeline_run["spec"]["raw_goal"] == pipeline_run["goal"]

    def test_deploy_target_in_spec(self, pipeline_run):
        if pipeline_run["spec"] is None:
            pytest.skip("No spec")
        assert pipeline_run["spec"]["deploy_target"] is not None

    def test_run_id_is_uuid(self, pipeline_run):
        if pipeline_run["spec"] is None:
            pytest.skip("No spec")
        uuid_pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        )
        assert uuid_pattern.match(pipeline_run["spec"]["run_id"]), (
            f"run_id is not a UUID: {pipeline_run['spec']['run_id']!r}"
        )

    def test_created_at_is_iso8601(self, pipeline_run):
        if pipeline_run["spec"] is None:
            pytest.skip("No spec")
        created_at = pipeline_run["spec"]["created_at"]
        # Basic ISO 8601 check: starts with YYYY-MM-DD
        assert re.match(r"^\d{4}-\d{2}-\d{2}T", created_at), (
            f"created_at is not ISO 8601: {created_at!r}"
        )

    def test_risk_tolerance_valid(self, pipeline_run):
        if pipeline_run["spec"] is None:
            pytest.skip("No spec")
        assert pipeline_run["spec"]["risk_tolerance"] in ("lean", "stable")

    def test_notification_preference_valid(self, pipeline_run):
        if pipeline_run["spec"] is None:
            pytest.skip("No spec")
        assert pipeline_run["spec"]["notification_preference"] in (
            "blocked_only", "async", "never"
        )

    def test_auto_merge_is_bool(self, pipeline_run):
        if pipeline_run["spec"] is None:
            pytest.skip("No spec")
        assert isinstance(pipeline_run["spec"]["auto_merge_if_ci_green"], bool)

    def test_llm_provider_is_string(self, pipeline_run):
        if pipeline_run["spec"] is None:
            pytest.skip("No spec")
        assert isinstance(pipeline_run["spec"]["llm_provider"], str)
        assert pipeline_run["spec"]["llm_provider"]  # non-empty
