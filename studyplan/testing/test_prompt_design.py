"""Tests for studyplan.ai.prompt_design (prompt library and Slice 4 versioning)."""
from __future__ import annotations

import os

import pytest

from studyplan.ai import prompt_design as pd


def test_get_prompt_version_default_when_unset() -> None:
    """When env STUDYPLAN_PROMPT_VERSION_<task> is unset, get_prompt_version returns 'default'."""
    # Clear in case test run with env set
    key = "STUDYPLAN_PROMPT_VERSION_AUTOPILOT"
    old = os.environ.pop(key, None)
    try:
        assert pd.get_prompt_version("autopilot") == "default"
        assert pd.get_prompt_version("coach") == "default"
    finally:
        if old is not None:
            os.environ[key] = old


def test_get_prompt_version_from_env() -> None:
    """When env STUDYPLAN_PROMPT_VERSION_<task> is set, get_prompt_version returns it (lowercased)."""
    key = "STUDYPLAN_PROMPT_VERSION_AUTOPILOT"
    old = os.environ.get(key)
    try:
        os.environ[key] = "v2"
        assert pd.get_prompt_version("autopilot") == "v2"
        os.environ[key] = "V3"
        assert pd.get_prompt_version("autopilot") == "v3"
    finally:
        if old is not None:
            os.environ[key] = old
        else:
            os.environ.pop(key, None)


def test_get_task_prompt_spec_returns_default_spec() -> None:
    """get_task_prompt_spec(task_id) returns the default spec (backward compatible)."""
    spec = pd.get_task_prompt_spec("autopilot")
    assert isinstance(spec, dict)
    assert spec.get("role_base") == pd.AUTOPILOT_ROLE_BASE
    assert "rules" in spec
    assert spec.get("schema_one_line") == pd.AUTOPILOT_ACTION_SCHEMA_ONE_LINE


def test_get_task_prompt_spec_with_explicit_version_default() -> None:
    """get_task_prompt_spec(task_id, version='default') returns default spec."""
    spec = pd.get_task_prompt_spec("autopilot", version="default")
    assert spec.get("role_base") == pd.AUTOPILOT_ROLE_BASE


def test_get_task_prompt_spec_versioned_fallback_to_default() -> None:
    """When version is not 'default' but that version is not in _TASK_SPEC_VERSIONS, return default."""
    spec = pd.get_task_prompt_spec("autopilot", version="v99")
    assert spec.get("role_base") == pd.AUTOPILOT_ROLE_BASE


def test_get_task_prompt_spec_versioned_override() -> None:
    """When version is in _TASK_SPEC_VERSIONS for task_id, return that spec."""
    try:
        pd._TASK_SPEC_VERSIONS.setdefault("autopilot", {})["v2"] = {
            "role_base": "You are an ACCA AI tutor cockpit controller (v2).",
            "role_suffix": pd.AUTOPILOT_ROLE_SUFFIX,
            "rules": pd.AUTOPILOT_RULES,
            "schema_one_line": pd.AUTOPILOT_ACTION_SCHEMA_ONE_LINE,
        }
        spec = pd.get_task_prompt_spec("autopilot", version="v2")
        assert spec.get("role_base") == "You are an ACCA AI tutor cockpit controller (v2)."
    finally:
        pd._TASK_SPEC_VERSIONS.pop("autopilot", None)


def test_get_task_prompt_spec_unknown_task_raises() -> None:
    """get_task_prompt_spec(unknown_task_id) raises KeyError."""
    with pytest.raises(KeyError, match="Unknown task_id"):
        pd.get_task_prompt_spec("unknown_task")


def test_build_judge_prompt_3es_order() -> None:
    """build_judge_prompt_3es outputs Role → Schema → Rules → Payload → JSON (3Es order)."""
    out = pd.build_judge_prompt_3es(
        role_base="You are an examiner.",
        schema_one_line='{"outcome":"correct|partial|incorrect"}',
        rules=["Rule one.", "Rule two."],
        payload_blocks=[("Module", "FR"), ("Question", "What is IFRS?"), ("Learner answer", "Standard.")],
    )
    assert "You are an examiner." in out
    assert "Schema:" in out
    assert '{"outcome":"correct|partial|incorrect"}' in out
    assert "Rules:" in out
    assert "- Rule one." in out
    assert "- Rule two." in out
    assert "Payload:" in out
    assert "Module: FR" in out
    assert "Question: What is IFRS?" in out
    assert "Learner answer: Standard." in out
    assert "JSON:" in out
    # Order: role before Schema, Schema before Rules, Rules before Payload, Payload before JSON
    idx_role = out.index("You are an examiner.")
    idx_schema = out.index("Schema:")
    idx_rules = out.index("Rules:")
    idx_payload = out.index("Payload:")
    idx_json = out.index("JSON:")
    assert idx_role < idx_schema < idx_rules < idx_payload < idx_json
