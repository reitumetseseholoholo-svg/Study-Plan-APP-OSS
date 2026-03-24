# pyright: reportArgumentType=false

import datetime
import json
import os
import threading
import types
import urllib.error
import urllib.request

import pytest
from studyplan.cognitive_state import CognitiveState, CompetencyPosterior
from studyplan_ai_tutor import (
    AI_TUTOR_RAG_USAGE_HINT,
    assess_tutor_coverage,
    assemble_ai_tutor_turn_prompt,
    build_ai_tutor_context_prompt_details,
    build_tutor_coverage_checklist_note,
    build_targeted_rag_queries,
    build_rag_context_block,
    classify_ollama_error,
    chunk_text_for_rag,
    compute_tutor_control_state,
    extract_tutor_coverage_targets,
    lexical_rank_rag_chunks,
    normalize_tutor_timeout_seconds,
    should_force_stream_flush,
    should_keep_response_bottom,
)

try:
    from studyplan_app import (
        DEFAULT_OLLAMA_MODEL_COACH,
        DEFAULT_OLLAMA_MODEL_TUTOR,
        StudyPlanGUI,
    )
except Exception as exc:  # pragma: no cover - environment-dependent import gate
    pytest.skip(f"studyplan_app import unavailable: {exc}", allow_module_level=True)


def _make_dummy(host: str = "127.0.0.1:11434"):
    dummy = types.SimpleNamespace(
        local_llm_host=host,
        local_llm_timeout_seconds=30,
        local_llm_enabled=True,
    )
    dummy._allow_remote_ollama_hosts = types.MethodType(StudyPlanGUI._allow_remote_ollama_hosts, dummy)
    dummy._is_local_or_private_host = types.MethodType(StudyPlanGUI._is_local_or_private_host, dummy)
    dummy._normalize_ollama_host = types.MethodType(StudyPlanGUI._normalize_ollama_host, dummy)
    dummy._get_ollama_retry_limit = types.MethodType(StudyPlanGUI._get_ollama_retry_limit, dummy)
    dummy._get_ollama_retry_backoff_seconds = types.MethodType(StudyPlanGUI._get_ollama_retry_backoff_seconds, dummy)
    dummy._is_transient_ollama_error = types.MethodType(StudyPlanGUI._is_transient_ollama_error, dummy)
    dummy._ensure_llama_runtime = lambda: None
    dummy._runtime_tuning_for_model = types.MethodType(StudyPlanGUI._runtime_tuning_for_model, dummy)
    dummy._effective_ollama_num_threads = types.MethodType(StudyPlanGUI._effective_ollama_num_threads, dummy)
    dummy._gpt4all_auto_import_enabled = types.MethodType(StudyPlanGUI._gpt4all_auto_import_enabled, dummy)
    dummy._gpt4all_models_dir = types.MethodType(StudyPlanGUI._gpt4all_models_dir, dummy)
    dummy._normalize_gpt4all_filename_to_ollama_model = types.MethodType(
        StudyPlanGUI._normalize_gpt4all_filename_to_ollama_model, dummy
    )
    # Stub llama.cpp path so tests that mock Ollama hit the Ollama code path
    dummy._generate_via_llama_server = lambda _prompt, *args, **kwargs: ("", "llama_server_not_healthy")
    dummy._generate_via_llama_server_stream = lambda _prompt, on_chunk=None, cancel_check=None, **kwargs: (
        "",
        "llama_server_not_healthy",
    )
    return dummy


def _make_ai_coach_dummy():
    engine = types.SimpleNamespace(
        CHAPTERS=["Topic A", "Topic B", "Topic C"],
    )
    dummy = types.SimpleNamespace(
        engine=engine,
        current_topic="Topic A",
        _topic_has_questions=lambda topic: topic in {"Topic A", "Topic B"},
        _topic_has_due_review=lambda topic: topic == "Topic A",
    )
    dummy._coerce_ai_coach_duration = types.MethodType(StudyPlanGUI._coerce_ai_coach_duration, dummy)
    dummy._get_next_action_line = types.MethodType(StudyPlanGUI._get_next_action_line, dummy)
    return dummy


def _make_local_context_dummy():
    today = datetime.date.today()
    engine = types.SimpleNamespace(
        CHAPTERS=["Topic A", "Topic B", "Topic C"],
        exam_date=today + datetime.timedelta(days=40),
        competence={"Topic A": 42.0, "Topic B": 58.0, "Topic C": 77.0},
        srs_data={
            "Topic A": [{"last_review": None, "interval": 1}, {"last_review": today.isoformat(), "interval": 1}],
            "Topic B": [{"last_review": (today - datetime.timedelta(days=8)).isoformat(), "interval": 2}],
            "Topic C": [],
        },
        question_stats={
            "Topic A": {
                "0": {"attempts": 10, "correct": 6, "last_seen": today.isoformat()},
                "1": {"attempts": 4, "correct": 1, "last_seen": (today - datetime.timedelta(days=3)).isoformat()},
            },
            "Topic B": {
                "0": {"attempts": 3, "correct": 2, "last_seen": (today - datetime.timedelta(days=10)).isoformat()},
            },
        },
        get_chapter_recall_risk=lambda chapter: {"Topic A": 0.62, "Topic B": 0.41, "Topic C": 0.15}.get(chapter, 0.0),
        is_overdue=lambda item, _today: item.get("last_review") is not None and str(item.get("last_review")) <= (
            today - datetime.timedelta(days=2)
        ).isoformat(),
    )
    dummy = types.SimpleNamespace(
        engine=engine,
        module_title="FM",
        current_topic="Topic B",
        action_time_sessions=[
            {
                "kind": "quiz",
                "topic": "Topic A",
                "seconds": 600,
                "timestamp": datetime.datetime.combine(today, datetime.time(12, 0)).isoformat(timespec="seconds"),
            },
            {
                "kind": "pomodoro_focus",
                "topic": "Topic B",
                "seconds": 1500,
                "timestamp": datetime.datetime.combine(today - datetime.timedelta(days=1), datetime.time(13, 0)).isoformat(
                    timespec="seconds"
                ),
            },
            {
                "kind": "review",
                "topic": "Topic A",
                "seconds": 480,
                "timestamp": datetime.datetime.combine(today - datetime.timedelta(days=2), datetime.time(14, 0)).isoformat(
                    timespec="seconds"
                ),
            },
        ],
        focus_integrity_log=[
            {"date": (today - datetime.timedelta(days=1)).isoformat(), "raw": 30.0, "verified": 24.0},
            {"date": (today - datetime.timedelta(days=4)).isoformat(), "raw": 25.0, "verified": 20.0},
        ],
        _get_coach_pick_snapshot=lambda force=True: ("Topic A", "plan"),
        _get_must_review_due_count=lambda _today: 2,
        _get_topic_due_count=lambda topic, _today=None: {"Topic A": 3, "Topic B": 1, "Topic C": 0}.get(topic, 0),
        _get_chapter_miss_risk=lambda chapter: {"Topic A": 0.55, "Topic B": 0.2, "Topic C": 0.1}.get(chapter, 0.0),
    )
    dummy._estimate_ai_tutor_token_count = types.MethodType(StudyPlanGUI._estimate_ai_tutor_token_count, dummy)
    dummy._estimate_context_tokens = types.MethodType(StudyPlanGUI._estimate_context_tokens, dummy)
    dummy._context_budget_limits = types.MethodType(StudyPlanGUI._context_budget_limits, dummy)
    dummy._build_local_ai_context_packet = types.MethodType(StudyPlanGUI._build_local_ai_context_packet, dummy)
    dummy._format_local_ai_context_block = types.MethodType(StudyPlanGUI._format_local_ai_context_block, dummy)
    dummy._effective_tutor_topic = types.MethodType(StudyPlanGUI._effective_tutor_topic, dummy)
    dummy._tutor_topic_for_context = types.MethodType(StudyPlanGUI._tutor_topic_for_context, dummy)
    dummy._is_cognitive_runtime_enabled = lambda: False
    return dummy


def test_coerce_ui_density_mode_defaults_to_progressive():
    dummy = types.SimpleNamespace()
    assert StudyPlanGUI._coerce_ui_density_mode(dummy, "progressive") == "progressive"
    assert StudyPlanGUI._coerce_ui_density_mode(dummy, "unknown") == "progressive"
    assert StudyPlanGUI._coerce_ui_density_mode(dummy, "") == "progressive"


def test_coerce_ui_toggle_accepts_common_truthy_and_falsy():
    dummy = types.SimpleNamespace()
    assert StudyPlanGUI._coerce_ui_toggle(dummy, "1", False) is True
    assert StudyPlanGUI._coerce_ui_toggle(dummy, "true", False) is True
    assert StudyPlanGUI._coerce_ui_toggle(dummy, "yes", False) is True
    assert StudyPlanGUI._coerce_ui_toggle(dummy, "on", False) is True
    assert StudyPlanGUI._coerce_ui_toggle(dummy, "0", True) is False
    assert StudyPlanGUI._coerce_ui_toggle(dummy, "", True) is True


def test_detect_tiling_wm_hint_from_env(monkeypatch):
    dummy = types.SimpleNamespace()
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "abc123")
    assert StudyPlanGUI._detect_tiling_wm_hint(dummy) is True
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "sway")
    assert StudyPlanGUI._detect_tiling_wm_hint(dummy) is True


def test_is_sidebar_effectively_visible_respects_auto_hidden():
    dummy = types.SimpleNamespace(ui_sidebar_visible=True, _sidebar_auto_hidden=True)
    assert StudyPlanGUI._is_sidebar_effectively_visible(dummy) is False
    dummy._sidebar_auto_hidden = False
    assert StudyPlanGUI._is_sidebar_effectively_visible(dummy) is True


def test_should_auto_hide_sidebar_on_stack_or_tight_window():
    dummy = types.SimpleNamespace()
    assert (
        StudyPlanGUI._should_auto_hide_sidebar(dummy, 1400, 900, stack_layout=True, tile_mode=False)
        is True
    )
    assert (
        StudyPlanGUI._should_auto_hide_sidebar(dummy, 1320, 860, stack_layout=False, tile_mode=True)
        is True
    )
    assert (
        StudyPlanGUI._should_auto_hide_sidebar(dummy, 1500, 940, stack_layout=False, tile_mode=False)
        is False
    )


def test_compute_layout_mode_extends_thresholds_for_tiling_hint():
    dummy = types.SimpleNamespace(_tiling_wm_hint=True)
    compact, stack_layout, tile_mode = StudyPlanGUI._compute_layout_mode(dummy, 1240, 900)
    assert compact is True
    assert stack_layout is True
    assert tile_mode is True


def test_normalize_ollama_host_adds_scheme_and_trims_slash():
    dummy = _make_dummy("127.0.0.1:11434/")
    got = StudyPlanGUI._normalize_ollama_host(dummy)
    assert got == "http://127.0.0.1:11434"


def test_normalize_ollama_host_rejects_non_http_scheme():
    dummy = _make_dummy("file:///tmp/ollama.sock")
    got = StudyPlanGUI._normalize_ollama_host(dummy)
    assert got == "http://127.0.0.1:11434"


def test_normalize_ollama_host_blocks_remote_by_default(monkeypatch):
    monkeypatch.delenv("STUDYPLAN_ALLOW_REMOTE_OLLAMA", raising=False)
    dummy = _make_dummy("https://example.com:443")
    got = StudyPlanGUI._normalize_ollama_host(dummy)
    assert got == "http://127.0.0.1:11434"


def test_normalize_ollama_host_allows_remote_when_env_enabled(monkeypatch):
    monkeypatch.setenv("STUDYPLAN_ALLOW_REMOTE_OLLAMA", "1")
    dummy = _make_dummy("https://example.com:443")
    got = StudyPlanGUI._normalize_ollama_host(dummy)
    assert got == "https://example.com:443"


def test_gpt4all_auto_import_enabled_toggle(monkeypatch):
    dummy = _make_dummy()
    monkeypatch.setenv("STUDYPLAN_AUTO_IMPORT_GPT4ALL_MODELS", "0")
    assert StudyPlanGUI._gpt4all_auto_import_enabled(dummy) is False
    monkeypatch.setenv("STUDYPLAN_AUTO_IMPORT_GPT4ALL_MODELS", "1")
    assert StudyPlanGUI._gpt4all_auto_import_enabled(dummy) is True


def test_normalize_gpt4all_filename_to_ollama_model():
    dummy = _make_dummy()
    name = StudyPlanGUI._normalize_gpt4all_filename_to_ollama_model(
        dummy, "Llama-3.2-3B-Instruct-Q4_0.gguf"
    )
    assert name == "gpt4all-llama-3-2-3b-instruct-q4-0:latest"


def test_select_local_llm_model_auto_picks_best_quality_performance():
    dummy = types.SimpleNamespace(
        local_llm_model="",
        local_llm_auto_select=True,
        _ai_tutor_telemetry_events=[
            {
                "model": "small-3b:latest",
                "outcome": "success",
                "latency_ms": 5200,
                "response_tokens_est": 120,
                "coverage_target_count": 4,
                "coverage_hit_count": 2,
            },
            {
                "model": "small-3b:latest",
                "outcome": "success",
                "latency_ms": 5000,
                "response_tokens_est": 110,
                "coverage_target_count": 4,
                "coverage_hit_count": 2,
            },
            {
                "model": "mid-7b-instruct-q4:latest",
                "outcome": "success",
                "latency_ms": 1900,
                "response_tokens_est": 170,
                "coverage_target_count": 4,
                "coverage_hit_count": 4,
            },
            {
                "model": "mid-7b-instruct-q4:latest",
                "outcome": "success",
                "latency_ms": 1700,
                "response_tokens_est": 165,
                "coverage_target_count": 4,
                "coverage_hit_count": 4,
            },
        ],
        save_preferences=lambda: None,
    )
    dummy._coerce_local_llm_auto_select = types.MethodType(StudyPlanGUI._coerce_local_llm_auto_select, dummy)
    dummy._is_local_llm_auto_select_enabled = types.MethodType(StudyPlanGUI._is_local_llm_auto_select_enabled, dummy)
    dummy._estimate_local_llm_model_size_b = types.MethodType(StudyPlanGUI._estimate_local_llm_model_size_b, dummy)
    dummy._heuristic_local_llm_model_prior = types.MethodType(StudyPlanGUI._heuristic_local_llm_model_prior, dummy)
    dummy._score_local_llm_model = types.MethodType(StudyPlanGUI._score_local_llm_model, dummy)
    dummy._rank_local_llm_models = types.MethodType(StudyPlanGUI._rank_local_llm_models, dummy)
    picked, err = StudyPlanGUI._select_local_llm_model(
        dummy,
        model_override=None,
        purpose="tutor",
        available_models=["small-3b:latest", "mid-7b-instruct-q4:latest"],
        persist=False,
    )
    assert err is None
    assert picked == "mid-7b-instruct-q4:latest"


def test_select_local_llm_model_manual_mode_uses_configured_model():
    dummy = types.SimpleNamespace(
        local_llm_model="manual-model:latest",
        local_llm_auto_select=False,
        _ai_tutor_telemetry_events=[],
        save_preferences=lambda: None,
    )
    dummy._coerce_local_llm_auto_select = types.MethodType(StudyPlanGUI._coerce_local_llm_auto_select, dummy)
    dummy._is_local_llm_auto_select_enabled = types.MethodType(StudyPlanGUI._is_local_llm_auto_select_enabled, dummy)
    dummy._estimate_local_llm_model_size_b = types.MethodType(StudyPlanGUI._estimate_local_llm_model_size_b, dummy)
    dummy._heuristic_local_llm_model_prior = types.MethodType(StudyPlanGUI._heuristic_local_llm_model_prior, dummy)
    dummy._score_local_llm_model = types.MethodType(StudyPlanGUI._score_local_llm_model, dummy)
    dummy._rank_local_llm_models = types.MethodType(StudyPlanGUI._rank_local_llm_models, dummy)
    picked, err = StudyPlanGUI._select_local_llm_model(
        dummy,
        model_override=None,
        purpose="coach",
        available_models=["manual-model:latest", "other-model:latest"],
        persist=False,
    )
    assert err is None
    assert picked == "manual-model:latest"


def test_select_local_llm_model_auto_mode_avoids_switch_for_small_score_gap():
    dummy = types.SimpleNamespace(
        local_llm_model="steady-7b:latest",
        local_llm_auto_select=True,
        _ai_tutor_telemetry_events=[],
        _local_llm_last_switch_at=0.0,
        save_preferences=lambda: None,
    )
    dummy._coerce_local_llm_auto_select = types.MethodType(StudyPlanGUI._coerce_local_llm_auto_select, dummy)
    dummy._is_local_llm_auto_select_enabled = types.MethodType(StudyPlanGUI._is_local_llm_auto_select_enabled, dummy)
    dummy._estimate_local_llm_model_size_b = types.MethodType(StudyPlanGUI._estimate_local_llm_model_size_b, dummy)
    dummy._heuristic_local_llm_model_prior = types.MethodType(StudyPlanGUI._heuristic_local_llm_model_prior, dummy)
    dummy._score_local_llm_model = types.MethodType(StudyPlanGUI._score_local_llm_model, dummy)
    dummy._rank_local_llm_models = lambda models, purpose="general": [
        {"model": "best-7b:latest", "score": 0.81, "perf_score": 0.82, "quality_score": 0.80},
        {"model": "steady-7b:latest", "score": 0.79, "perf_score": 0.79, "quality_score": 0.79},
    ]
    dummy._get_ai_tutor_latency_profile = lambda window=24: {"load_level": "normal"}
    dummy._get_ai_tutor_latency_slo_status = lambda window=24: {"status": "pass"}
    picked, err = StudyPlanGUI._select_local_llm_model(
        dummy,
        model_override=None,
        purpose="tutor",
        available_models=["best-7b:latest", "steady-7b:latest"],
        persist=False,
    )
    assert err is None
    assert picked == "steady-7b:latest"


def test_select_local_llm_model_auto_skips_cooling_model():
    dummy = types.SimpleNamespace(
        local_llm_model="",
        local_llm_auto_select=True,
        _ai_tutor_telemetry_events=[],
        _local_llm_last_switch_at=0.0,
        save_preferences=lambda: None,
    )
    dummy._coerce_local_llm_auto_select = types.MethodType(StudyPlanGUI._coerce_local_llm_auto_select, dummy)
    dummy._is_local_llm_auto_select_enabled = types.MethodType(StudyPlanGUI._is_local_llm_auto_select_enabled, dummy)
    dummy._estimate_local_llm_model_size_b = types.MethodType(StudyPlanGUI._estimate_local_llm_model_size_b, dummy)
    dummy._heuristic_local_llm_model_prior = types.MethodType(StudyPlanGUI._heuristic_local_llm_model_prior, dummy)
    dummy._score_local_llm_model = types.MethodType(StudyPlanGUI._score_local_llm_model, dummy)
    dummy._rank_local_llm_models = types.MethodType(StudyPlanGUI._rank_local_llm_models, dummy)
    dummy._is_local_llm_model_on_cooldown = lambda model_name: (
        str(model_name or "").startswith("best-"),
        45,
        "recent failures",
    )
    dummy._get_ai_tutor_latency_profile = lambda window=24: {"load_level": "normal"}
    dummy._get_ai_tutor_latency_slo_status = lambda window=24: {"status": "pass"}
    picked, err = StudyPlanGUI._select_local_llm_model(
        dummy,
        model_override=None,
        purpose="tutor",
        available_models=["best-8b:latest", "steady-7b:latest"],
        persist=False,
    )
    assert err is None
    assert picked == "steady-7b:latest"


def test_select_local_llm_model_cold_start_prefers_tutor_default_when_available():
    dummy = types.SimpleNamespace(
        local_llm_model="",
        local_llm_auto_select=True,
        _ai_tutor_telemetry_events=[],
        _local_llm_last_switch_at=0.0,
        save_preferences=lambda: None,
    )
    dummy._coerce_local_llm_auto_select = types.MethodType(StudyPlanGUI._coerce_local_llm_auto_select, dummy)
    dummy._is_local_llm_auto_select_enabled = types.MethodType(StudyPlanGUI._is_local_llm_auto_select_enabled, dummy)
    dummy._estimate_local_llm_model_size_b = types.MethodType(StudyPlanGUI._estimate_local_llm_model_size_b, dummy)
    dummy._resolve_local_llm_default_for_purpose = types.MethodType(
        StudyPlanGUI._resolve_local_llm_default_for_purpose, dummy
    )
    dummy._heuristic_local_llm_model_prior = types.MethodType(StudyPlanGUI._heuristic_local_llm_model_prior, dummy)
    dummy._score_local_llm_model = types.MethodType(StudyPlanGUI._score_local_llm_model, dummy)
    dummy._rank_local_llm_models = types.MethodType(StudyPlanGUI._rank_local_llm_models, dummy)
    picked, err = StudyPlanGUI._select_local_llm_model(
        dummy,
        model_override=None,
        purpose="tutor",
        available_models=[DEFAULT_OLLAMA_MODEL_TUTOR, "other-7b:latest"],
        persist=False,
    )
    assert err is None
    assert picked == str(DEFAULT_OLLAMA_MODEL_TUTOR)


def test_select_local_llm_model_cold_start_prefers_coach_default_when_available():
    dummy = types.SimpleNamespace(
        local_llm_model="",
        local_llm_auto_select=True,
        _ai_tutor_telemetry_events=[],
        _local_llm_last_switch_at=0.0,
        save_preferences=lambda: None,
    )
    dummy._coerce_local_llm_auto_select = types.MethodType(StudyPlanGUI._coerce_local_llm_auto_select, dummy)
    dummy._is_local_llm_auto_select_enabled = types.MethodType(StudyPlanGUI._is_local_llm_auto_select_enabled, dummy)
    dummy._estimate_local_llm_model_size_b = types.MethodType(StudyPlanGUI._estimate_local_llm_model_size_b, dummy)
    dummy._resolve_local_llm_default_for_purpose = types.MethodType(
        StudyPlanGUI._resolve_local_llm_default_for_purpose, dummy
    )
    dummy._heuristic_local_llm_model_prior = types.MethodType(StudyPlanGUI._heuristic_local_llm_model_prior, dummy)
    dummy._score_local_llm_model = types.MethodType(StudyPlanGUI._score_local_llm_model, dummy)
    dummy._rank_local_llm_models = types.MethodType(StudyPlanGUI._rank_local_llm_models, dummy)
    picked, err = StudyPlanGUI._select_local_llm_model(
        dummy,
        model_override=None,
        purpose="coach",
        available_models=[DEFAULT_OLLAMA_MODEL_COACH, "other-7b:latest", DEFAULT_OLLAMA_MODEL_TUTOR],
        persist=False,
    )
    assert err is None
    assert picked == str(DEFAULT_OLLAMA_MODEL_COACH)


def test_resolve_local_llm_default_prefers_qwen35_4b_for_tutor_when_available():
    dummy = types.SimpleNamespace()
    picked = StudyPlanGUI._resolve_local_llm_default_for_purpose(
        dummy,
        "tutor",
        ["other-7b:latest", "gpt4all-qwen3-5-4b-q4-0:latest", "small-3b:latest"],
    )
    assert picked == "gpt4all-qwen3-5-4b-q4-0:latest"


def test_resolve_local_llm_default_skips_incomplete_qwen35_4b_tags():
    dummy = types.SimpleNamespace()
    coach_fallback = str(DEFAULT_OLLAMA_MODEL_COACH or "").strip() or "coach-fallback:latest"
    picked = StudyPlanGUI._resolve_local_llm_default_for_purpose(
        dummy,
        "coach",
        [
            "gpt4all-incomplete-qwen3-5-4b-q4-0:latest",
            coach_fallback,
        ],
    )
    assert picked == coach_fallback


def test_build_local_llm_model_failover_sequence_orders_selected_then_alternatives(monkeypatch):
    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_MODEL_FAILOVER_MAX", "2")
    dummy = types.SimpleNamespace(
        local_llm_model="steady-7b:latest",
        local_llm_auto_select=True,
        _ai_tutor_telemetry_events=[],
        _local_llm_last_switch_at=0.0,
        save_preferences=lambda: None,
    )
    dummy._coerce_local_llm_auto_select = types.MethodType(StudyPlanGUI._coerce_local_llm_auto_select, dummy)
    dummy._is_local_llm_auto_select_enabled = types.MethodType(StudyPlanGUI._is_local_llm_auto_select_enabled, dummy)
    dummy._estimate_local_llm_model_size_b = types.MethodType(StudyPlanGUI._estimate_local_llm_model_size_b, dummy)
    dummy._heuristic_local_llm_model_prior = types.MethodType(StudyPlanGUI._heuristic_local_llm_model_prior, dummy)
    dummy._score_local_llm_model = types.MethodType(StudyPlanGUI._score_local_llm_model, dummy)
    dummy._rank_local_llm_models = lambda models, purpose="general": [
        {"model": "best-8b:latest", "score": 0.93, "perf_score": 0.91, "quality_score": 0.95},
        {"model": "steady-7b:latest", "score": 0.76, "perf_score": 0.78, "quality_score": 0.74},
        {"model": "small-3b:latest", "score": 0.62, "perf_score": 0.88, "quality_score": 0.52},
    ]
    dummy._get_ai_tutor_latency_profile = lambda window=24: {"load_level": "normal"}
    dummy._get_ai_tutor_latency_slo_status = lambda window=24: {"status": "pass"}
    dummy._select_local_llm_model = types.MethodType(StudyPlanGUI._select_local_llm_model, dummy)
    dummy._coerce_local_llm_model_failover_max = types.MethodType(
        StudyPlanGUI._coerce_local_llm_model_failover_max, dummy
    )
    dummy._build_local_llm_model_failover_sequence = types.MethodType(
        StudyPlanGUI._build_local_llm_model_failover_sequence, dummy
    )
    seq, err = StudyPlanGUI._build_local_llm_model_failover_sequence(
        dummy,
        purpose="tutor",
        available_models=["best-8b:latest", "steady-7b:latest", "small-3b:latest"],
        persist=False,
    )
    assert err is None
    assert seq[0] == "best-8b:latest"
    assert len(seq) == 2


def test_select_local_llm_model_records_routing_event():
    dummy = types.SimpleNamespace(
        local_llm_model="",
        local_llm_auto_select=False,
        _ai_tutor_telemetry_events=[],
        _llm_routing_events=[],
        _llm_routing_events_max=16,
        save_preferences=lambda: None,
    )
    dummy._record_llm_routing_event = types.MethodType(StudyPlanGUI._record_llm_routing_event, dummy)
    dummy._coerce_local_llm_auto_select = types.MethodType(StudyPlanGUI._coerce_local_llm_auto_select, dummy)
    dummy._is_local_llm_auto_select_enabled = types.MethodType(StudyPlanGUI._is_local_llm_auto_select_enabled, dummy)
    dummy._estimate_local_llm_model_size_b = types.MethodType(StudyPlanGUI._estimate_local_llm_model_size_b, dummy)
    dummy._heuristic_local_llm_model_prior = types.MethodType(StudyPlanGUI._heuristic_local_llm_model_prior, dummy)
    dummy._score_local_llm_model = types.MethodType(StudyPlanGUI._score_local_llm_model, dummy)
    dummy._rank_local_llm_models = types.MethodType(StudyPlanGUI._rank_local_llm_models, dummy)

    picked, err = StudyPlanGUI._select_local_llm_model(
        dummy,
        purpose="deep_reason",
        available_models=["model-a:latest"],
        persist=False,
        routing_request_id="rid-123",
        prompt_chars=432,
    )
    assert err is None
    assert picked == "model-a:latest"
    assert len(dummy._llm_routing_events) == 1
    event = dummy._llm_routing_events[0]
    assert event["request_id"] == "rid-123"
    assert event["stage"] == "select"
    assert event["purpose"] == "deep_reason"
    assert "purpose_deep_reason" in event["reason_codes"]
    assert event["prompt_chars"] == 432


def test_failover_sequence_records_event_and_keeps_request_id():
    dummy = types.SimpleNamespace(
        local_llm_model="",
        local_llm_auto_select=False,
        _ai_tutor_telemetry_events=[],
        _llm_routing_events=[],
        _llm_routing_events_max=16,
        save_preferences=lambda: None,
    )
    dummy._record_llm_routing_event = types.MethodType(StudyPlanGUI._record_llm_routing_event, dummy)
    dummy._coerce_local_llm_auto_select = types.MethodType(StudyPlanGUI._coerce_local_llm_auto_select, dummy)
    dummy._is_local_llm_auto_select_enabled = types.MethodType(StudyPlanGUI._is_local_llm_auto_select_enabled, dummy)
    dummy._estimate_local_llm_model_size_b = types.MethodType(StudyPlanGUI._estimate_local_llm_model_size_b, dummy)
    dummy._heuristic_local_llm_model_prior = types.MethodType(StudyPlanGUI._heuristic_local_llm_model_prior, dummy)
    dummy._score_local_llm_model = types.MethodType(StudyPlanGUI._score_local_llm_model, dummy)
    dummy._rank_local_llm_models = types.MethodType(StudyPlanGUI._rank_local_llm_models, dummy)
    dummy._select_local_llm_model = types.MethodType(StudyPlanGUI._select_local_llm_model, dummy)
    dummy._coerce_local_llm_model_failover_max = types.MethodType(
        StudyPlanGUI._coerce_local_llm_model_failover_max, dummy
    )

    seq, err = StudyPlanGUI._build_local_llm_model_failover_sequence(
        dummy,
        purpose="tutor",
        available_models=["model-a:latest", "model-b:latest"],
        persist=False,
        routing_request_id="rid-xyz",
    )
    assert err is None
    assert seq
    assert len(dummy._llm_routing_events) >= 2
    assert all(row.get("request_id") == "rid-xyz" for row in dummy._llm_routing_events[-2:])
    assert dummy._llm_routing_events[-1]["stage"] == "failover"


def test_record_local_llm_model_outcome_sets_cooldown_after_threshold(monkeypatch):
    monkeypatch.setenv("STUDYPLAN_AI_MODEL_FAILURE_THRESHOLD", "2")
    monkeypatch.setenv("STUDYPLAN_AI_MODEL_FAILURE_WINDOW_SECONDS", "600")
    monkeypatch.setenv("STUDYPLAN_AI_MODEL_COOLDOWN_SECONDS", "60")
    dummy = types.SimpleNamespace(
        _llm_model_health={},
    )
    dummy._coerce_ai_model_failure_threshold = types.MethodType(StudyPlanGUI._coerce_ai_model_failure_threshold, dummy)
    dummy._coerce_ai_model_failure_window_seconds = types.MethodType(
        StudyPlanGUI._coerce_ai_model_failure_window_seconds, dummy
    )
    dummy._coerce_ai_model_cooldown_seconds = types.MethodType(StudyPlanGUI._coerce_ai_model_cooldown_seconds, dummy)
    dummy._record_local_llm_model_outcome = types.MethodType(StudyPlanGUI._record_local_llm_model_outcome, dummy)
    dummy._is_local_llm_model_on_cooldown = types.MethodType(StudyPlanGUI._is_local_llm_model_on_cooldown, dummy)

    StudyPlanGUI._record_local_llm_model_outcome(dummy, "demo:latest", success=False, err="HTTP 503")
    StudyPlanGUI._record_local_llm_model_outcome(dummy, "demo:latest", success=False, err="HTTP 503")
    cooling, remaining, reason = StudyPlanGUI._is_local_llm_model_on_cooldown(dummy, "demo:latest")
    assert cooling is True
    assert remaining > 0
    assert "HTTP 503" in reason


def test_sync_gpt4all_models_to_ollama_once_imports_missing_files(tmp_path, monkeypatch):
    dummy = _make_dummy()
    monkeypatch.setenv("STUDYPLAN_GPT4ALL_MODELS_DIR", str(tmp_path))
    (tmp_path / "Existing.gguf").write_bytes(b"ok")
    (tmp_path / "New Model.Q4_0.gguf").write_bytes(b"ok")
    (tmp_path / "incomplete.gguf").write_bytes(b"")

    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/ollama" if cmd == "ollama" else None)
    monkeypatch.setattr(dummy, "_ollama_list_models", lambda: (["gpt4all-existing:latest"], None), raising=False)

    calls: list[list[str]] = []

    class _Result:
        def __init__(self):
            self.returncode = 0
            self.stdout = "ok"
            self.stderr = ""

    def _fake_run(cmd, capture_output=False, text=False, timeout=None):
        calls.append(list(cmd))
        return _Result()

    monkeypatch.setattr("subprocess.run", _fake_run)

    summary = StudyPlanGUI._sync_gpt4all_models_to_ollama_once(dummy, max_models=8)
    assert summary["imported"] == 1
    assert summary["skipped_existing"] == 1
    assert summary["skipped_invalid"] == 1
    assert summary["failed"] == 0
    assert len(calls) == 1
    assert calls[0][2] == "gpt4all-new-model-q4-0:latest"


def test_build_ai_tutor_context_prompt_contains_history_and_current_request():
    dummy = _make_dummy()
    history = [
        {"role": "user", "content": "Explain NPV."},
        {"role": "assistant", "content": "NPV discounts cash flows."},
    ]
    prompt = StudyPlanGUI._build_ai_tutor_context_prompt(
        dummy,
        history=history,
        user_prompt="Give me a 3-question drill.",
        module_title="FM",
        chapter="Investment Decisions",
    )
    assert "Module: FM" in prompt
    assert "Current chapter: Investment Decisions" in prompt
    assert "first-class local ACCA tutor" in prompt
    assert "maximize exam readiness per minute" in prompt
    assert "USER: Explain NPV." in prompt
    assert "ASSISTANT: NPV discounts cash flows." in prompt
    assert "USER: Give me a 3-question drill." in prompt
    assert prompt.endswith("ASSISTANT:")


def test_request_ai_tutor_action_plan_fails_over_to_next_model():
    dummy = types.SimpleNamespace(
        local_llm_enabled=True,
    )
    dummy._build_local_llm_model_failover_sequence = lambda **_kwargs: (
        ["broken-3b:latest", "good-7b:latest"],
        None,
    )
    dummy._build_ai_tutor_autopilot_prompt = lambda _snapshot: "prompt"

    calls = {"count": 0}

    def _fake_generate(model, _prompt, **_kwargs):
        calls["count"] += 1
        if model == "broken-3b:latest":
            return "", "HTTP 503: service unavailable"
        return '{"action":"focus_start","topic":"Topic A","duration_minutes":25,"reason":"ok","confidence":0.91,"requires_confirmation":false}', None

    dummy._ollama_generate_text = _fake_generate
    dummy._extract_first_json_object = lambda text: text
    dummy._normalize_ai_tutor_action_plan = lambda parsed, _snapshot: (
        {
            "action": str(parsed.get("action", "focus_start")),
            "topic": str(parsed.get("topic", "Topic A")),
            "duration_minutes": int(parsed.get("duration_minutes", 25)),
            "reason": str(parsed.get("reason", "ok")),
            "confidence": float(parsed.get("confidence", 0.8)),
            "requires_confirmation": bool(parsed.get("requires_confirmation", False)),
        },
        None,
    )
    dummy._build_ai_tutor_fallback_action = types.MethodType(
        StudyPlanGUI._build_ai_tutor_fallback_action, dummy
    )
    dummy._normalize_ollama_host = lambda: "http://127.0.0.1:11434"

    plan, err = StudyPlanGUI._request_ai_tutor_action_plan(
        dummy,
        snapshot={"current_topic": "Topic A", "must_review_due": 0},
    )
    assert err is None
    assert calls["count"] == 2
    assert plan["model"] == "good-7b:latest"
    assert plan["source"] == "ai"
    assert int(plan.get("failover_attempt", 0)) == 1


def test_compose_ollama_recovery_status_includes_actions():
    dummy = _make_dummy()
    dummy._classify_ollama_failure_kind = types.MethodType(StudyPlanGUI._classify_ollama_failure_kind, dummy)
    dummy._compose_ollama_recovery_status = types.MethodType(StudyPlanGUI._compose_ollama_recovery_status, dummy)
    msg = StudyPlanGUI._compose_ollama_recovery_status(
        dummy,
        "Connection refused",
        model="small-3b:latest",
        attempted_models=["small-3b:latest", "mid-7b:latest"],
    )
    assert "Cannot reach Ollama" in msg
    assert "Recovery (" in msg
    assert "Attempted:" in msg


def test_compose_ollama_recovery_status_handles_model_cooldown():
    dummy = _make_dummy()
    dummy._classify_ollama_failure_kind = types.MethodType(StudyPlanGUI._classify_ollama_failure_kind, dummy)
    dummy._compose_ollama_recovery_status = types.MethodType(StudyPlanGUI._compose_ollama_recovery_status, dummy)
    msg = StudyPlanGUI._compose_ollama_recovery_status(
        dummy,
        "model cooldown active (45s)",
        model="cooling-7b:latest",
    )
    assert "cooling down" in msg.lower()
    assert "Recovery (" in msg


def test_request_ai_coach_recommendation_fails_over_to_next_model():
    dummy = types.SimpleNamespace(
        local_llm_enabled=True,
    )
    dummy._build_ai_coach_payload = lambda: {"recommended_topic": "Topic A"}
    dummy._build_local_llm_model_failover_sequence = lambda **_kwargs: (
        ["broken-3b:latest", "good-7b:latest"],
        None,
    )
    dummy._build_ai_coach_prompt = lambda _payload: "coach-prompt"

    def _fake_generate(model, _prompt, **_kwargs):
        if model == "broken-3b:latest":
            return "", "HTTP 503: service unavailable"
        return '{"action":"focus","topic":"Topic A","duration_minutes":25,"reason":"ok","confidence":0.8}', None

    dummy._ollama_generate_text = _fake_generate
    dummy._should_compact_recovery_retry = lambda _err: False
    dummy._coerce_ollama_reduced_num_ctx = lambda _v=None: 1536
    dummy._reduce_prompt_for_recovery = lambda prompt: prompt
    dummy._ollama_generate_text_with_options = lambda model, prompt, **_kwargs: _fake_generate(model, prompt)
    dummy._extract_first_json_object = lambda text: text
    dummy._normalize_ai_coach_recommendation = lambda parsed, _payload: (
        {
            "action": str(parsed.get("action", "focus")),
            "topic": str(parsed.get("topic", "Topic A")),
            "duration_minutes": int(parsed.get("duration_minutes", 25)),
            "reason": str(parsed.get("reason", "ok")),
            "confidence": float(parsed.get("confidence", 0.8)),
        },
        None,
    )
    dummy._build_ai_coach_fallback_recommendation = types.MethodType(
        StudyPlanGUI._build_ai_coach_fallback_recommendation, dummy
    )
    dummy._compose_ollama_recovery_status = lambda err, **_kwargs: err
    rec, err = StudyPlanGUI._request_ai_coach_recommendation(dummy)
    assert err is None
    assert rec["model"] == "good-7b:latest"
    assert int(rec.get("failover_attempt", 0)) == 1
    assert rec.get("attempted_models") == ["broken-3b:latest", "good-7b:latest"]


def test_request_ai_tutor_action_plan_invalid_output_returns_guided_recovery():
    dummy = types.SimpleNamespace(
        local_llm_enabled=True,
    )
    dummy._build_local_llm_model_failover_sequence = lambda **_kwargs: (["good-7b:latest"], None)
    dummy._build_ai_tutor_autopilot_prompt = lambda _snapshot: "prompt"
    dummy._ollama_generate_text = lambda _model, _prompt, **_kwargs: ("no-json-here", None)
    dummy._extract_first_json_object = lambda _text: ""
    dummy._build_ai_tutor_fallback_action = types.MethodType(StudyPlanGUI._build_ai_tutor_fallback_action, dummy)
    dummy._compose_ollama_guardrail_status = types.MethodType(StudyPlanGUI._compose_ollama_guardrail_status, dummy)

    plan, err = StudyPlanGUI._request_ai_tutor_action_plan(
        dummy,
        snapshot={"current_topic": "Topic A", "must_review_due": 0},
    )
    assert plan["source"] == "deterministic_fallback"
    assert isinstance(err, str)
    assert "deterministic fallback" in str(err).lower()
    assert "Recovery (invalid_output" in str(err)


def test_request_ai_coach_recommendation_invalid_output_returns_guided_recovery():
    dummy = types.SimpleNamespace(
        local_llm_enabled=True,
    )
    dummy._build_ai_coach_payload = lambda: {"recommended_topic": "Topic A"}
    dummy._build_local_llm_model_failover_sequence = lambda **_kwargs: (["good-7b:latest"], None)
    dummy._build_ai_coach_prompt = lambda _payload: "coach-prompt"
    dummy._ollama_generate_text = lambda _model, _prompt, **_kwargs: ("no-json-here", None)
    dummy._extract_first_json_object = lambda _text: ""
    dummy._build_ai_coach_fallback_recommendation = lambda _payload, issue: {
        "action": "focus",
        "topic": "Topic A",
        "duration_minutes": 25,
        "reason": str(issue),
        "source": "deterministic_fallback",
    }
    dummy._compose_ollama_guardrail_status = types.MethodType(StudyPlanGUI._compose_ollama_guardrail_status, dummy)

    rec, err = StudyPlanGUI._request_ai_coach_recommendation(dummy)
    assert rec["source"] == "deterministic_fallback"
    assert isinstance(err, str)
    assert "deterministic fallback" in str(err).lower()
    assert "Recovery (invalid_output" in str(err)


def test_build_ai_tutor_context_prompt_clamps_to_last_10_messages():
    dummy = _make_dummy()
    history = []
    for i in range(12):
        history.append({"role": "user", "content": f"u{i}"})
    prompt = StudyPlanGUI._build_ai_tutor_context_prompt(
        dummy,
        history=history,
        user_prompt="latest",
        module_title="FM",
        chapter="Cost of Capital",
    )
    lines = set(prompt.splitlines())
    assert "USER: u0" not in lines
    assert "USER: u1" not in lines
    assert "USER: u2" in lines
    assert "USER: u11" in lines


def test_build_ai_tutor_context_prompt_summarizes_older_messages():
    dummy = _make_dummy()
    history = []
    for i in range(14):
        history.append({"role": "user", "content": f"user-{i}"})
    prompt = StudyPlanGUI._build_ai_tutor_context_prompt(
        dummy,
        history=history,
        user_prompt="latest",
        module_title="FM",
        chapter="Cost of Capital",
    )
    assert "Earlier context summary (older turns condensed):" in prompt
    assert "- You:" in prompt
    assert "USER: user-4" in prompt
    assert "USER: user-13" in prompt
    assert "USER: latest" in prompt


def test_chunk_text_for_rag_splits_long_text():
    text = " ".join(["wacc", "discount", "rate", "capital"] * 180)
    chunks = chunk_text_for_rag(text, chunk_chars=220, overlap_chars=40, max_chunks=12)
    assert len(chunks) >= 2
    assert all(isinstance(chunk, str) and chunk.strip() for chunk in chunks)


def test_lexical_rank_rag_chunks_prioritizes_relevant_chunk():
    chunks = [
        "NPV discounts future cash flows using the discount rate.",
        "This paragraph is about audit procedures and ethics.",
        "Working capital policy can impact liquidity and risk.",
    ]
    ranked = lexical_rank_rag_chunks("How do I calculate NPV using discount rate?", chunks, top_n=3)
    assert ranked
    assert ranked[0][0] == 0


def test_lexical_rank_rag_chunks_fr_presentation_boost_raises_presentation_chunk_score():
    chunks = [
        "uniquemarkerfoo bar baz filler text.",
        "ias 7 statement of cash flows operating activities investing activities financing activities disclosure.",
    ]
    q = "uniquemarkerfoo bar baz"
    off = lexical_rank_rag_chunks(q, chunks, top_n=2, fr_presentation_rag_boost=False)
    on = lexical_rank_rag_chunks(q, chunks, top_n=2, fr_presentation_rag_boost=True)
    assert off and on
    off_by = {idx: sc for idx, sc in off}
    on_by = {idx: sc for idx, sc in on}
    assert on_by.get(1, 0.0) > off_by.get(1, 0.0)


def test_build_rag_context_block_formats_snippet_ids():
    block = build_rag_context_block(
        [
            {"id": "S1", "source": "fm_textbook.pdf", "text": "WACC = (E/V)*Ke + (D/V)*Kd*(1-T)"},
            {"id": "S2", "source": "fm_textbook.pdf", "text": "NPV uses discounting of future cash flows."},
        ]
    )
    assert "Reference snippets" in block
    assert "[S1]" in block
    assert "fm_textbook.pdf" in block


def test_build_ai_tutor_rag_prompt_context_returns_snippets_for_relevant_query():
    dummy = types.SimpleNamespace(
        module_title="FM",
        current_topic="Cost of Capital",
        semantic_enabled=False,
        engine=types.SimpleNamespace(),
    )
    dummy._effective_tutor_topic = types.MethodType(StudyPlanGUI._effective_tutor_topic, dummy)
    dummy._tutor_topic_for_context = types.MethodType(StudyPlanGUI._tutor_topic_for_context, dummy)
    dummy._is_cognitive_runtime_enabled = lambda: False
    dummy._get_ai_tutor_rag_source_pdfs = lambda: ["/tmp/fm_source.pdf"]
    dummy._load_ai_tutor_rag_doc = lambda _path: (
        {
            "path": "/tmp/fm_source.pdf",
            "source": "fm_source.pdf",
            "chunks": [
                {"chunk_index": 0, "text": "WACC combines equity and debt costs after tax."},
                {"chunk_index": 1, "text": "NPV discounts future cash flows by cost of capital."},
                {"chunk_index": 2, "text": "Irrelevant sentence about an unrelated subject."},
            ],
        },
        None,
    )
    context, meta = StudyPlanGUI._build_ai_tutor_rag_prompt_context(
        dummy,
        user_prompt="Explain how WACC affects NPV decisions",
        history=[{"role": "user", "content": "Need discount rate guidance"}],
        top_k=2,
    )
    assert meta.get("snippet_count", 0) >= 1
    assert meta.get("source_count") == 1
    assert "[S1]" in context
    assert "WACC" in context or "NPV" in context


def _make_rag_dummy(docs_by_path: dict[str, dict[str, object]]) -> types.SimpleNamespace:
    dummy = types.SimpleNamespace(
        module_title="FM",
        current_topic="Cost of Capital",
        semantic_enabled=False,
        engine=types.SimpleNamespace(),
    )
    dummy._effective_tutor_topic = types.MethodType(StudyPlanGUI._effective_tutor_topic, dummy)
    dummy._tutor_topic_for_context = types.MethodType(StudyPlanGUI._tutor_topic_for_context, dummy)
    dummy._is_cognitive_runtime_enabled = lambda: False
    dummy._get_ai_tutor_rag_source_pdfs = lambda: list(docs_by_path.keys())
    dummy._load_ai_tutor_rag_doc = lambda path: (docs_by_path.get(path), None)
    return dummy


def test_get_ai_tutor_rag_source_pdfs_respects_preferences_and_limit(tmp_path):
    pdf_a = tmp_path / "a.pdf"
    pdf_b = tmp_path / "b.pdf"
    pdf_c = tmp_path / "c.pdf"
    txt = tmp_path / "note.txt"
    for path in (pdf_a, pdf_b, pdf_c):
        path.write_bytes(b"%PDF-1.4")
    txt.write_text("not a pdf", encoding="utf-8")

    dummy = types.SimpleNamespace(
        ai_tutor_rag_pdfs=f"{pdf_a}\n{pdf_b}\n{txt}",
        ai_tutor_rag_max_sources=2,
        engine=types.SimpleNamespace(syllabus_meta={"source_pdf": str(pdf_c)}),
    )
    dummy._get_ai_tutor_rag_max_pdf_bytes = types.MethodType(StudyPlanGUI._get_ai_tutor_rag_max_pdf_bytes, dummy)
    sources = StudyPlanGUI._get_ai_tutor_rag_source_pdfs(dummy)
    assert len(sources) == 2
    assert sources[0] == os.path.realpath(str(pdf_a))
    assert sources[1] == os.path.realpath(str(pdf_b))


def test_get_ai_tutor_rag_source_pdfs_env_max_overrides_preference(tmp_path, monkeypatch):
    pdf_a = tmp_path / "a.pdf"
    pdf_b = tmp_path / "b.pdf"
    pdf_c = tmp_path / "c.pdf"
    for path in (pdf_a, pdf_b, pdf_c):
        path.write_bytes(b"%PDF-1.4")

    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_RAG_MAX_SOURCES", "3")
    dummy = types.SimpleNamespace(
        ai_tutor_rag_pdfs=f"{pdf_a}\n{pdf_b}\n{pdf_c}",
        ai_tutor_rag_max_sources=1,
        engine=types.SimpleNamespace(syllabus_meta={}),
    )
    dummy._get_ai_tutor_rag_max_pdf_bytes = types.MethodType(StudyPlanGUI._get_ai_tutor_rag_max_pdf_bytes, dummy)
    sources = StudyPlanGUI._get_ai_tutor_rag_source_pdfs(dummy)
    assert len(sources) == 3


def test_get_ai_tutor_rag_source_pdfs_respects_pdf_size_limit_env(tmp_path, monkeypatch):
    small_pdf = tmp_path / "small.pdf"
    large_pdf = tmp_path / "large.pdf"
    small_pdf.write_bytes(b"%PDF-1.4\nsmall")
    with open(large_pdf, "wb") as f:
        f.truncate(2 * 1024 * 1024)

    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_RAG_MAX_PDF_MB", "1")
    dummy = types.SimpleNamespace(
        ai_tutor_rag_pdfs=f"{small_pdf}\n{large_pdf}",
        ai_tutor_rag_max_sources=4,
        engine=types.SimpleNamespace(syllabus_meta={}),
    )
    dummy._get_ai_tutor_rag_max_pdf_bytes = types.MethodType(StudyPlanGUI._get_ai_tutor_rag_max_pdf_bytes, dummy)
    sources = StudyPlanGUI._get_ai_tutor_rag_source_pdfs(dummy)
    assert os.path.realpath(str(small_pdf)) in sources
    assert os.path.realpath(str(large_pdf)) not in sources


def test_load_ai_tutor_rag_doc_handles_bytes_from_extraction(tmp_path, monkeypatch):
    """When _extract_pdf_text_for_syllabus returns bytes, _load_ai_tutor_rag_doc decodes and produces chunks."""
    pdf_path = tmp_path / "syllabus.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 minimal")
    # Path validation requires the file under home or CONFIG_HOME; treat tmp_path as home for this test.
    _orig_expanduser = os.path.expanduser
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path) if (p == "~" or p == "~/" or not p) else _orig_expanduser(p))
    dummy = types.SimpleNamespace(
        _perf_cache=None,
        _ai_cache_get_rag_doc=lambda k: None,
        _ai_cache_put_rag_doc=None,
        _ai_tutor_rag_doc_cache_key=lambda p, **_kwargs: f"key_{os.path.basename(p)}",
    )
    dummy._classify_ai_tutor_rag_source_tier = lambda _path, _name: "syllabus"
    dummy._extract_pdf_text_for_syllabus = lambda p: (
        b"Chapter 1: Introduction. Learning outcome 1.1 explain the framework. Some content.",
        {},
    )
    doc, err = StudyPlanGUI._load_ai_tutor_rag_doc(dummy, str(pdf_path))
    assert err is None
    assert isinstance(doc, dict)
    chunks = doc.get("chunks") or []
    assert isinstance(chunks, list)
    assert len(chunks) >= 1
    assert all(isinstance(c, dict) and c.get("text") for c in chunks)


def test_rag_prompt_context_dynamic_target_and_budget(monkeypatch):
    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_RAG_TOP_K_MAX", "12")
    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_RAG_CHAR_BUDGET", "1800")
    docs = {
        "/tmp/fm_source.pdf": {
            "path": "/tmp/fm_source.pdf",
            "source": "fm_source.pdf",
            "chunks": [
                {"chunk_index": idx, "text": f"WACC and NPV concept {idx} with discount rate details {idx}."}
                for idx in range(16)
            ],
        }
    }
    dummy = _make_rag_dummy(docs)
    prompt = " ".join(["Explain interactions between WACC and NPV across scenarios."] * 40)
    context, meta = StudyPlanGUI._build_ai_tutor_rag_prompt_context(
        dummy,
        user_prompt=prompt,
        history=[{"role": "user", "content": "Need integrated guidance on WACC and NPV"}],
        top_k=4,
    )
    assert context
    assert int(meta.get("top_k_target", 0) or 0) >= 6
    assert int(meta.get("char_used", 0) or 0) <= int(meta.get("char_budget", 0) or 0)
    assert int(meta.get("candidate_count", 0) or 0) >= 1


def test_rag_prompt_context_neighbor_expansion_adds_adjacent_chunks(monkeypatch):
    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_RAG_NEIGHBOR_WINDOW", "1")
    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_RAG_TOP_K_MAX", "4")
    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_RAG_CHAR_BUDGET", "2200")
    docs = {
        "/tmp/fm_source.pdf": {
            "path": "/tmp/fm_source.pdf",
            "source": "fm_source.pdf",
            "chunks": [
                {"chunk_index": 0, "text": "General intro paragraph unrelated."},
                {"chunk_index": 1, "text": "Neighbor left context for the target explanation."},
                {"chunk_index": 2, "text": "Core targetterm discussion on WACC and capital structure."},
                {"chunk_index": 3, "text": "Neighbor right context extending the target explanation."},
                {"chunk_index": 4, "text": "General outro paragraph unrelated."},
            ],
        }
    }
    dummy = _make_rag_dummy(docs)
    context, meta = StudyPlanGUI._build_ai_tutor_rag_prompt_context(
        dummy,
        user_prompt="Explain targetterm impact",
        history=[],
        top_k=4,
    )
    assert "Neighbor left context" in context or "Neighbor right context" in context
    assert int(meta.get("selected_total_count", 0) or 0) >= int(meta.get("selected_primary_count", 0) or 0)
    assert int(meta.get("neighbor_window", 0) or 0) == 1


def test_rag_prompt_context_source_diversification_prefers_cross_source(monkeypatch):
    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_RAG_TOP_K_MAX", "6")
    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_RAG_CHAR_BUDGET", "1800")
    docs = {
        "/tmp/src_a.pdf": {
            "path": "/tmp/src_a.pdf",
            "source": "src_a.pdf",
            "chunks": [
                {"chunk_index": 0, "text": "WACC discount rate and NPV relationship details from source A."},
                {"chunk_index": 1, "text": "Another WACC discount paragraph from source A."},
            ],
        },
        "/tmp/src_b.pdf": {
            "path": "/tmp/src_b.pdf",
            "source": "src_b.pdf",
            "chunks": [
                {"chunk_index": 0, "text": "NPV decision thresholds with WACC support from source B."},
            ],
        },
    }
    dummy = _make_rag_dummy(docs)
    _context, meta = StudyPlanGUI._build_ai_tutor_rag_prompt_context(
        dummy,
        user_prompt="How do WACC and NPV interact in decisions?",
        history=[],
        top_k=4,
    )
    sources = list(meta.get("sources", []) or [])
    assert "src_a.pdf" in sources
    assert "src_b.pdf" in sources


def test_rag_query_cache_key_includes_preset(monkeypatch, tmp_path):
    ref = tmp_path / "only.pdf"
    ref.write_bytes(b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")
    docs = {
        str(ref): {
            "path": str(ref),
            "source": "only.pdf",
            "chunks": [{"chunk_index": 0, "text": "WACC discount rate and NPV relationship."}],
        }
    }
    dummy = _make_rag_dummy(docs)
    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_RAG_PRESET", "tutor_drill")
    _a, meta_a = StudyPlanGUI._build_ai_tutor_rag_prompt_context(
        dummy,
        user_prompt="WACC and NPV",
        history=[],
        top_k=4,
    )
    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_RAG_PRESET", "tutor_explain")
    _b, meta_b = StudyPlanGUI._build_ai_tutor_rag_prompt_context(
        dummy,
        user_prompt="WACC and NPV",
        history=[],
        top_k=4,
    )
    assert str(meta_a.get("query_cache_key", "")) != str(meta_b.get("query_cache_key", ""))
    assert str(meta_a.get("rag_preset", "")) == "tutor_drill"
    assert str(meta_b.get("rag_preset", "")) == "tutor_explain"


def test_rag_strict_module_pdfs_drop_paths_not_in_reference_pdfs(tmp_path, monkeypatch):
    ref = tmp_path / "syllabus_ref.pdf"
    extra = tmp_path / "not_on_syllabus.pdf"
    ref.write_bytes(b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")
    extra.write_bytes(b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")
    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_RAG_STRICT_MODULE_PDFS", "1")
    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_RAG_PDFS", f"{ref},{extra}")
    dummy = types.SimpleNamespace(
        module_title="FM",
        ai_tutor_rag_pdfs="",
        ai_tutor_rag_max_sources=24,
        engine=types.SimpleNamespace(syllabus_meta={"reference_pdfs": [str(ref)]}),
    )
    dummy._get_ai_tutor_rag_max_pdf_bytes = lambda: 10_000_000
    out = StudyPlanGUI._get_ai_tutor_rag_source_pdfs(dummy)
    real_out = {os.path.realpath(p) for p in out}
    assert os.path.realpath(str(ref)) in real_out
    assert os.path.realpath(str(extra)) not in real_out


def test_rag_prompt_context_dedup_suppresses_duplicate_chunks(monkeypatch):
    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_RAG_CHAR_BUDGET", "1800")
    docs = {
        "/tmp/fm_source.pdf": {
            "path": "/tmp/fm_source.pdf",
            "source": "fm_source.pdf",
            "chunks": [
                {"chunk_index": 0, "text": "WACC formula and NPV are linked in investment appraisal."},
                {"chunk_index": 1, "text": "WACC formula and NPV are linked in investment appraisal."},
            ],
        }
    }
    dummy = _make_rag_dummy(docs)
    context, meta = StudyPlanGUI._build_ai_tutor_rag_prompt_context(
        dummy,
        user_prompt="Show WACC formula link to NPV",
        history=[],
        top_k=4,
    )
    assert int(meta.get("snippet_count", 0) or 0) == 1
    snippet_lines = [line for line in context.splitlines() if line.startswith("[S")]
    assert len(snippet_lines) == 1


def test_rag_prompt_context_invalid_env_falls_back_safely(monkeypatch):
    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_RAG_TOP_K_MAX", "invalid")
    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_RAG_CHAR_BUDGET", "bad")
    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_RAG_NEIGHBOR_WINDOW", "bad")
    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_RAG_LEXICAL_TOP_N", "oops")
    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_RAG_CANDIDATE_CAP", "nope")
    docs = {
        "/tmp/fm_source.pdf": {
            "path": "/tmp/fm_source.pdf",
            "source": "fm_source.pdf",
            "chunks": [{"chunk_index": 0, "text": "WACC details."}],
        }
    }
    dummy = _make_rag_dummy(docs)
    _context, meta = StudyPlanGUI._build_ai_tutor_rag_prompt_context(
        dummy,
        user_prompt="WACC",
        history=[],
        top_k=4,
    )
    assert 4 <= int(meta.get("top_k_target", 0) or 0) <= 16
    assert 800 <= int(meta.get("char_budget", 0) or 0) <= 3600
    assert 0 <= int(meta.get("neighbor_window", 0) or 0) <= 2


def test_rag_prompt_context_budget_keeps_primary_hits_before_neighbors(monkeypatch):
    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_RAG_TOP_K_MAX", "8")
    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_RAG_NEIGHBOR_WINDOW", "1")
    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_RAG_CHAR_BUDGET", "220")
    docs = {
        "/tmp/src_a.pdf": {
            "path": "/tmp/src_a.pdf",
            "source": "src_a.pdf",
            "chunks": [
                {"chunk_index": 0, "text": "Neighbor context from source A with extra words and explanation."},
                {"chunk_index": 1, "text": "Core signal termalpha from source A."},
                {"chunk_index": 2, "text": "Another neighbor from source A to test ordering under budget."},
            ],
        },
        "/tmp/src_b.pdf": {
            "path": "/tmp/src_b.pdf",
            "source": "src_b.pdf",
            "chunks": [
                {"chunk_index": 0, "text": "Neighbor context from source B with extra words and explanation."},
                {"chunk_index": 1, "text": "Core signal termalpha from source B."},
                {"chunk_index": 2, "text": "Another neighbor from source B to test ordering under budget."},
            ],
        },
    }
    dummy = _make_rag_dummy(docs)
    context, meta = StudyPlanGUI._build_ai_tutor_rag_prompt_context(
        dummy,
        user_prompt="Explain termalpha impact",
        history=[],
        top_k=4,
    )
    assert int(meta.get("char_used", 0) or 0) <= int(meta.get("char_budget", 0) or 0)
    assert "Core signal termalpha from source A." in context
    assert "Core signal termalpha from source B." in context


def test_rag_prompt_context_relevance_floor_with_fallback(monkeypatch):
    monkeypatch.setenv("STUDYPLAN_AI_TUTOR_RAG_MIN_SCORE", "0.95")
    docs = {
        "/tmp/fm_source.pdf": {
            "path": "/tmp/fm_source.pdf",
            "source": "fm_source.pdf",
            "chunks": [
                {"chunk_index": 0, "text": "This text is weakly related to finance in general."},
                {"chunk_index": 1, "text": "Another broad sentence with little lexical overlap."},
            ],
        }
    }
    dummy = _make_rag_dummy(docs)
    context, meta = StudyPlanGUI._build_ai_tutor_rag_prompt_context(
        dummy,
        user_prompt="finance risk token",
        history=[],
        top_k=4,
    )
    # Even with an aggressive relevance floor, fallback should keep at least one candidate.
    assert int(meta.get("candidate_count", 0) or 0) >= 1
    assert int(meta.get("snippet_count", 0) or 0) >= 1
    assert "Reference snippets" in context


def test_build_local_ai_context_packet_returns_required_fields():
    dummy = _make_local_context_dummy()
    packet = StudyPlanGUI._build_local_ai_context_packet(dummy, kind="tutor", horizon_days=14)
    assert packet["module"] == "FM"
    assert packet["current_topic"] == "Topic B"
    assert packet["coach_pick"] == "Topic A"


def test_effective_tutor_topic_prefers_action_timer_over_ui_topic():
    engine = types.SimpleNamespace(CHAPTERS=["Topic A", "Topic B", "Topic C"])
    dummy = types.SimpleNamespace(
        engine=engine,
        current_topic="Topic B",
        _action_timer_kind="pomodoro_focus",
        _action_timer_topic="Topic A",
        quiz_session=None,
    )
    dummy._is_cognitive_runtime_enabled = lambda: False
    assert StudyPlanGUI._effective_tutor_topic(dummy) == "Topic A"


def test_on_topic_changed_invalidates_coach_pick_snapshot():
    engine = types.SimpleNamespace(CHAPTERS=["Topic A", "Topic B", "Topic C"])
    invalidated = {"called": False}
    updated = {"called": False}

    def _invalidate():
        invalidated["called"] = True

    def _update():
        updated["called"] = True

    class DummyItem:
        def __init__(self, text: str):
            self._text = text

        def get_string(self):
            return self._text

    class DummyCombo:
        def __init__(self, idx: int, item):
            self._idx = idx
            self._item = item

        def get_selected(self):
            return self._idx

        def get_selected_item(self):
            return self._item

    dummy = types.SimpleNamespace(
        engine=engine,
        current_topic="Topic A",
        _invalidate_coach_pick_snapshot=_invalidate,
        update_study_room_card=_update,
    )
    combo = DummyCombo(2, DummyItem("Topic C"))
    StudyPlanGUI.on_topic_changed(dummy, combo)
    assert dummy.current_topic == "Topic C"
    assert invalidated["called"] is True
    assert updated["called"] is True


def test_effective_tutor_topic_falls_back_to_coach_pick_when_current_invalid():
    engine = types.SimpleNamespace(CHAPTERS=["Topic A", "Topic B", "Topic C"])
    dummy = types.SimpleNamespace(
        engine=engine,
        current_topic="Unknown Topic",
        _action_timer_kind="",
        _action_timer_topic="",
        quiz_session=None,
        _get_coach_pick_snapshot=lambda force=True: ("Topic B", "plan"),
    )
    dummy._is_cognitive_runtime_enabled = lambda: False
    assert StudyPlanGUI._effective_tutor_topic(dummy) == "Topic B"


def test_build_tutor_loop_cognitive_runtime_meta_ignores_active_chapter_when_quiz_inactive():
    state = CognitiveState()
    state.working_memory.active_chapter = "Topic A"
    state.quiz_active = False
    dummy = types.SimpleNamespace(current_topic="")
    dummy._is_cognitive_runtime_enabled = lambda: True
    dummy._cognitive_state = lambda: state
    dummy._build_tutor_loop_cognitive_runtime_meta = types.MethodType(
        StudyPlanGUI._build_tutor_loop_cognitive_runtime_meta, dummy
    )
    meta = dummy._build_tutor_loop_cognitive_runtime_meta(chapter="")
    assert meta["topic"] == ""


def test_build_tutor_loop_cognitive_runtime_meta_uses_active_chapter_when_quiz_active():
    state = CognitiveState()
    state.working_memory.active_chapter = "Topic A"
    state.quiz_active = True
    dummy = types.SimpleNamespace(current_topic="")
    dummy._is_cognitive_runtime_enabled = lambda: True
    dummy._cognitive_state = lambda: state
    dummy._build_tutor_loop_cognitive_runtime_meta = types.MethodType(
        StudyPlanGUI._build_tutor_loop_cognitive_runtime_meta, dummy
    )
    meta = dummy._build_tutor_loop_cognitive_runtime_meta(chapter="")
    assert meta["topic"] == "Topic A"


def test_apply_coach_pick_to_tutor_topic_updates_coach_pick_without_forcing_current():
    engine = types.SimpleNamespace(CHAPTERS=["Topic A", "Topic B"], CHAPTER_ALIASES={})
    tracker = {"set_called": None}

    def _set_current(topic: str, invalidate_snapshot: bool = True):
        tracker["set_called"] = (topic, invalidate_snapshot)

    dummy = types.SimpleNamespace(
        engine=engine,
        current_topic="Topic B",
        coach_only_view=False,
        _get_coach_pick_snapshot=lambda force=True: ("Topic A", "plan"),
        _set_current_topic=_set_current,
    )
    StudyPlanGUI._apply_coach_pick_to_tutor_topic(dummy)
    assert getattr(dummy, "_coach_pick_topic", "") == "Topic A"
    assert dummy.current_topic == "Topic B"
    assert tracker["set_called"] is None


def test_apply_coach_pick_to_tutor_topic_sets_current_when_empty():
    engine = types.SimpleNamespace(CHAPTERS=["Topic A", "Topic B"], CHAPTER_ALIASES={})
    tracker = {"set_called": None}

    def _set_current(topic: str, invalidate_snapshot: bool = True):
        tracker["set_called"] = (topic, invalidate_snapshot)
        dummy.current_topic = topic

    dummy = types.SimpleNamespace(
        engine=engine,
        current_topic="",
        coach_only_view=False,
        _get_coach_pick_snapshot=lambda force=True: ("Topic A", "plan"),
        _set_current_topic=_set_current,
    )
    StudyPlanGUI._apply_coach_pick_to_tutor_topic(dummy)
    assert getattr(dummy, "_coach_pick_topic", "") == "Topic A"
    assert dummy.current_topic == "Topic A"
    assert tracker["set_called"] == ("Topic A", False)


def test_build_local_ai_context_packet_uses_effective_tutor_topic():
    dummy = _make_local_context_dummy()
    dummy._action_timer_kind = "pomodoro_focus"
    dummy._action_timer_topic = "Topic A"
    dummy.quiz_session = None
    dummy._is_cognitive_runtime_enabled = lambda: False
    dummy._effective_tutor_topic = types.MethodType(StudyPlanGUI._effective_tutor_topic, dummy)
    packet = StudyPlanGUI._build_local_ai_context_packet(dummy, kind="tutor", horizon_days=14)
    assert packet["current_topic"] == "Topic A"
    assert "weak_topics_top3" in packet
    assert "quiz_trend_14d" in packet
    assert "focus_trend_14d" in packet
    assert "risk_snapshot_top3" in packet
    assert "due_snapshot_top3" in packet
    assert "recent_action_mix" in packet
    assert "working_memory" in packet


def test_format_local_ai_context_block_enforces_budget_and_degrade_order():
    dummy = _make_local_context_dummy()
    packet = StudyPlanGUI._build_local_ai_context_packet(dummy, kind="tutor", horizon_days=14)
    text = StudyPlanGUI._format_local_ai_context_block(dummy, packet, max_chars=220)
    assert len(text) <= 220
    assert "Topic:" in text
    assert "Must-review:" in text
    assert "Weak topics:" in text
    format_meta = packet.get("_format_meta", {})
    dropped = list(format_meta.get("dropped_sections", []) or [])
    assert dropped[:3] == ["recent_action_mix", "focus_trend_14d", "quiz_trend_14d"]


def test_context_budget_limits_and_horizon_env_fallback(monkeypatch):
    dummy = _make_local_context_dummy()
    monkeypatch.setenv("STUDYPLAN_AI_CONTEXT_MAX_CHARS_TUTOR", "oops")
    monkeypatch.setenv("STUDYPLAN_AI_CONTEXT_MAX_TOKENS_TUTOR", "bad")
    monkeypatch.setenv("STUDYPLAN_AI_CONTEXT_HORIZON_DAYS", "invalid")
    max_chars, max_tokens = StudyPlanGUI._context_budget_limits(dummy, "tutor")
    assert 400 <= max_chars <= 1600
    assert 120 <= max_tokens <= 480
    packet = StudyPlanGUI._build_local_ai_context_packet(dummy, kind="tutor", horizon_days=14)
    assert 7 <= int(packet.get("horizon_days", 0) or 0) <= 30


def test_ai_tutor_rag_usage_hint_is_non_rigid():
    hint = str(AI_TUTOR_RAG_USAGE_HINT or "").strip().lower()
    assert "rag snippets" in hint
    assert "[s" in hint  # [S1] style citation guidance
    assert "insufficient" in hint or "unsupported" in hint


def test_assemble_ai_tutor_turn_prompt_includes_learning_context_and_rag():
    prompt = assemble_ai_tutor_turn_prompt(
        "BASE PROMPT",
        learning_context="Topic: Topic A\nMust-review: 2",
        rag_context="Reference snippets (use only when relevant):\n[S1] Source: text",
    )
    assert "Learning context (aggregated app state):" in prompt
    assert "Reference snippets" in prompt
    assert "rag snippets" in prompt.lower()


def test_assemble_ai_tutor_turn_prompt_includes_planner_brief():
    prompt = assemble_ai_tutor_turn_prompt(
        "BASE PROMPT",
        learning_context="Topic: Topic A",
        rag_context="",
        planner_brief="- Coverage order: Topic A -> Topic B",
    )
    assert "Planner brief (deterministic guidance):" in prompt
    assert "Coverage order: Topic A -> Topic B" in prompt


def test_build_ai_tutor_context_prompt_details_includes_practice_first_contract():
    prompt, meta = build_ai_tutor_context_prompt_details(
        history=[],
        user_prompt="Explain working capital policy and give me something to practice.",
        module_title="FM",
        chapter="Working Capital Management",
    )
    assert "Pedagogical mode: explain" in prompt
    assert str(meta.get("pedagogical_mode", "")) == "explain"
    assert "Default learning-loop response contract" in prompt
    assert "Micro-check (1-3 practical checks or prompts)" in prompt
    assert bool(meta.get("practice_first_contract", False)) is True


def test_build_ai_tutor_context_prompt_details_adds_retrieval_mode_hint():
    prompt, meta = build_ai_tutor_context_prompt_details(
        history=[],
        user_prompt="Quiz me on WACC and CAPM with rapid fire retrieval practice.",
        module_title="FM",
        chapter="Cost of Capital",
    )
    assert "Pedagogical mode: practice" in prompt
    assert str(meta.get("pedagogical_mode", "")) == "practice"
    assert "Mode hint (adapt response style): retrieval_drill" in prompt
    assert "Use retrieval mode" in prompt
    assert str(meta.get("mode_hint", "")) == "retrieval_drill"


def test_build_ai_tutor_context_prompt_details_concise_and_exam_technique_only():
    prompt, meta = build_ai_tutor_context_prompt_details(
        history=[],
        user_prompt="How do I approach Section C time allocation?",
        module_title="FM",
        chapter="Section C",
        concise_mode=True,
        exam_technique_only=True,
    )
    assert "Concise mode" in prompt
    assert "under 6" in prompt or "6–8" in prompt
    assert "Exam technique only" in prompt
    assert "do not add micro-checks" in prompt or "no practice" in prompt.lower()
    assert "Response contract (exam technique only" in prompt
    assert bool(meta.get("exam_technique_only", False)) is True
    assert bool(meta.get("concise_mode", False)) is True
    assert bool(meta.get("practice_first_contract", True)) is False
    assert str(meta.get("pedagogical_mode", "")) == "exam_technique"


def test_record_ai_tutor_telemetry_sanitizes_values_and_caps_history():
    save_calls = {"count": 0}
    dummy = types.SimpleNamespace(
        _ai_tutor_telemetry_events=[],
        _ai_tutor_telemetry_max=3,
        save_preferences=lambda: save_calls.__setitem__("count", save_calls["count"] + 1),
    )
    dummy._sanitize_ai_tutor_telemetry_event = types.MethodType(
        StudyPlanGUI._sanitize_ai_tutor_telemetry_event, dummy
    )
    dummy._record_ai_tutor_telemetry = types.MethodType(StudyPlanGUI._record_ai_tutor_telemetry, dummy)

    cleaned = StudyPlanGUI._record_ai_tutor_telemetry(
        dummy,
        {
            "outcome": "BAD-VALUE",
            "purpose": "tutor_embedded",
            "effective_topic": "Topic X",
            "module_id": "m1",
            "prompt_contract_version": 5,
            "learning_context_fp": "ab" * 40,
            "learning_context_omitted": 2,
            "error_class": "Busy",
            "latency_ms": -5,
            "prompt_chars": "120",
            "response_chars": 240,
            "timeout_seconds": 9999,
            "ctx_chars": 99999,
            "ctx_budget_chars": -1,
            "ctx_tokens_est": "222",
            "ctx_dropped_sections_count": 999,
            "ctx_horizon_days": 999,
            "rag_target_count": 5000,
            "rag_target_hit_count": -2,
            "rag_insufficient_flag": 99,
            "rag_source_mix": "SYLLABUS:1|NOTES:2|SUPPLEMENTAL:1" * 10,
        },
        persist=False,
    )
    assert cleaned is not None
    assert cleaned["outcome"] == "error"
    assert cleaned["error_class"] == "busy"
    assert cleaned["latency_ms"] == 0
    assert cleaned["prompt_chars"] == 120
    assert cleaned["response_chars"] == 240
    assert cleaned["timeout_seconds"] == 600
    assert cleaned["ctx_chars"] == 10000
    assert cleaned["ctx_budget_chars"] == 0
    assert cleaned["ctx_tokens_est"] == 222
    assert cleaned["ctx_dropped_sections_count"] == 50
    assert cleaned["ctx_horizon_days"] == 90
    assert cleaned["rag_target_count"] == 1000
    assert cleaned["rag_target_hit_count"] == 0
    assert cleaned["rag_insufficient_flag"] == 1
    assert cleaned["rag_source_mix"].startswith("syllabus:1|notes:2|supplemental:1")
    assert len(cleaned["rag_source_mix"]) <= 120
    assert cleaned["ts_utc"]
    assert cleaned["purpose"] == "tutor_embedded"
    assert cleaned["effective_topic"] == "Topic X"
    assert cleaned["module_id"] == "m1"
    assert cleaned["prompt_contract_version"] == 5
    assert len(cleaned["learning_context_fp"]) == 64
    assert cleaned["learning_context_omitted"] == 1

    pr = StudyPlanGUI._sanitize_ai_tutor_telemetry_event(dummy, {"outcome": "parse_retry", "purpose": "tutor_popup"})
    assert isinstance(pr, dict)
    assert pr["outcome"] == "parse_retry"
    assert pr["purpose"] == "tutor_popup"

    for idx in range(4):
        StudyPlanGUI._record_ai_tutor_telemetry(
            dummy,
            {
                "outcome": "success",
                "latency_ms": 100 + idx,
                "prompt_chars": 20 + idx,
                "response_chars": 40 + idx,
                "prompt_tokens_est": 5 + idx,
                "response_tokens_est": 10 + idx,
                "timeout_seconds": 90,
            },
            persist=True,
        )
    assert save_calls["count"] == 4
    assert len(dummy._ai_tutor_telemetry_events) == 3
    assert [row["latency_ms"] for row in dummy._ai_tutor_telemetry_events] == [101, 102, 103]


def test_summarize_ai_tutor_telemetry_computes_rates_and_error_breakdown():
    dummy = types.SimpleNamespace(
        _ai_tutor_telemetry_events=[
            {
                "outcome": "success",
                "error_class": "",
                "latency_ms": 900,
                "prompt_chars": 120,
                "response_chars": 300,
                "prompt_tokens_est": 30,
                "response_tokens_est": 75,
                "rag_target_count": 2,
                "rag_target_hit_count": 1,
                "rag_insufficient_flag": 0,
                "rag_source_mix": "syllabus:1",
            },
            {
                "outcome": "cancelled",
                "error_class": "timeout",
                "latency_ms": 1200,
                "prompt_chars": 100,
                "response_chars": 150,
                "prompt_tokens_est": 25,
                "response_tokens_est": 38,
                "rag_target_count": 2,
                "rag_target_hit_count": 0,
                "rag_insufficient_flag": 1,
                "rag_source_mix": "notes:1",
            },
            {
                "outcome": "error",
                "error_class": "busy",
                "latency_ms": 600,
                "prompt_chars": 80,
                "response_chars": 0,
                "prompt_tokens_est": 20,
                "response_tokens_est": 0,
            },
            {
                "outcome": "error",
                "error_class": "busy",
                "latency_ms": 400,
                "prompt_chars": 60,
                "response_chars": 0,
                "prompt_tokens_est": 15,
                "response_tokens_est": 0,
            },
        ],
    )
    summary = StudyPlanGUI._summarize_ai_tutor_telemetry(dummy, window=4)
    assert summary["total_turns"] == 4
    assert summary["success_count"] == 1
    assert summary["cancelled_count"] == 1
    assert summary["error_count"] == 2
    assert summary["cancellation_rate"] == pytest.approx(0.25)
    assert summary["avg_latency_ms"] == pytest.approx((900 + 1200 + 600 + 400) / 4.0)
    assert summary["p50_latency_ms"] == pytest.approx(600.0)
    assert summary["p90_latency_ms"] == pytest.approx(1200.0)
    assert summary["latency_spread_ratio"] == pytest.approx(2.0)
    assert summary["p95_latency_ms"] == pytest.approx(1200.0)
    assert summary["avg_prompt_chars"] == pytest.approx((120 + 100 + 80 + 60) / 4.0)
    assert summary["error_classes"] == {"busy": 2, "timeout": 1}
    assert summary["rag_target_count"] == 2
    assert summary["rag_target_hit_count"] == 1
    assert summary["rag_insufficient_flag"] == 1
    assert summary["rag_source_mix"] == "notes:1"


def test_get_ai_tutor_latency_profile_and_adaptive_limits_under_load():
    dummy = types.SimpleNamespace(
        _ai_tutor_telemetry_events=[
            {"latency_ms": 26000},
            {"latency_ms": 32000},
            {"latency_ms": 35000},
            {"latency_ms": 91000},
            {"latency_ms": 98000},
        ]
    )
    dummy._get_ai_tutor_latency_profile = types.MethodType(StudyPlanGUI._get_ai_tutor_latency_profile, dummy)
    dummy._compute_ai_tutor_adaptive_limits = types.MethodType(StudyPlanGUI._compute_ai_tutor_adaptive_limits, dummy)
    profile = StudyPlanGUI._get_ai_tutor_latency_profile(dummy, window=5)
    assert profile["samples"] == 5
    assert profile["p90_latency_ms"] >= 91000.0
    assert profile["load_level"] == "critical"
    limits = StudyPlanGUI._compute_ai_tutor_adaptive_limits(
        dummy,
        coverage_target_count=5,
        context_max_chars=900,
        context_max_tokens=280,
        rag_top_k=12,
        rag_char_budget=1800,
    )
    assert limits["load_level"] == "critical"
    assert int(limits["context_max_chars"]) < 900
    assert int(limits["context_max_tokens"]) < 280
    assert int(limits["rag_top_k"]) <= 6
    assert int(limits["rag_char_budget"]) < 1800


def test_get_ai_tutor_latency_slo_status_reports_fail_for_high_tail_latency():
    dummy = types.SimpleNamespace(
        _ai_tutor_telemetry_events=[
            {"latency_ms": 28000},
            {"latency_ms": 30000},
            {"latency_ms": 34000},
            {"latency_ms": 90000},
            {"latency_ms": 98000},
            {"latency_ms": 102000},
            {"latency_ms": 110000},
            {"latency_ms": 120000},
        ]
    )
    dummy._get_ai_tutor_latency_profile = types.MethodType(StudyPlanGUI._get_ai_tutor_latency_profile, dummy)
    dummy._get_ai_tutor_latency_slo_status = types.MethodType(StudyPlanGUI._get_ai_tutor_latency_slo_status, dummy)
    status = StudyPlanGUI._get_ai_tutor_latency_slo_status(dummy, window=8)
    assert status["samples"] == 8
    assert status["status"] in {"warn", "fail"}
    assert float(status["p90_latency_ms"]) >= 90000.0


def test_build_debug_info_message_includes_ai_tutor_summary_lines():
    dummy = types.SimpleNamespace(
        exam_date="2026-06-01",
        engine=types.SimpleNamespace(CHAPTERS=["A", "B"], competence={"A": 70.0}),
    )
    msg = StudyPlanGUI._build_debug_info_message(
        dummy,
        hub={"quiz_scores": {"a": 1}, "practice_scores": {}, "detail_scores": {}, "category_totals": {}},
        graph_status={"concept_nodes": 12, "cluster_count": 3, "cluster_method": "kmeans"},
        drift={"status": "ok", "chapters_flagged": 1},
        perf={
            "route_meta_calls": 20,
            "route_cache_hits": 7,
            "tfidf_asset_hits": 5,
            "tfidf_asset_misses": 2,
            "max_route_ms": 44.0,
            "avg_route_ms": 12.5,
        },
        tutor_summary={
            "window": 40,
            "total_turns": 9,
            "success_count": 6,
            "cancelled_count": 2,
            "error_count": 1,
            "cancellation_rate": 2 / 9,
            "avg_latency_ms": 830.0,
            "p50_latency_ms": 700.0,
            "p90_latency_ms": 1500.0,
            "p95_latency_ms": 1700.0,
            "latency_spread_ratio": 2.14,
            "avg_queue_ms": 0.0,
            "avg_prompt_build_ms": 12.0,
            "avg_rag_ms": 48.0,
            "avg_generation_ms": 770.0,
            "avg_stream_ms": 620.0,
            "avg_first_token_ms": 140.0,
            "latency_slo_status": "warn",
            "avg_prompt_chars": 150.0,
            "avg_response_chars": 390.0,
            "avg_prompt_tokens_est": 38.0,
            "avg_response_tokens_est": 97.0,
            "error_classes": {"busy": 1},
        },
    )
    assert "AI Tutor turns (last 40): 9" in msg
    assert "AI Tutor success/cancel/error: 6/2/1" in msg
    assert "AI Tutor cancellation rate: 22.2%" in msg
    assert "AI Tutor latency avg/p50/p90/p95 (ms): 830.0/700.0/1500.0/1700.0" in msg
    assert "AI Tutor latency spread p90/p50: 2.14x" in msg
    assert "AI Tutor latency SLO status: warn" in msg
    assert "AI Tutor top error classes: busy:1" in msg


def test_build_debug_info_message_handles_missing_tutor_summary():
    dummy = types.SimpleNamespace(
        exam_date=None,
        engine=types.SimpleNamespace(CHAPTERS=[], competence={}),
    )
    msg = StudyPlanGUI._build_debug_info_message(
        dummy,
        hub={},
        graph_status={},
        drift={},
        perf={},
        tutor_summary=None,
    )
    assert "AI Tutor turns (last 40): 0" in msg
    assert "AI Tutor top error classes: none" in msg


def test_build_debug_info_message_includes_tutor_loop_thresholds_lines():
    dummy = types.SimpleNamespace(
        exam_date="2026-06-01",
        engine=types.SimpleNamespace(CHAPTERS=["A"], competence={}),
        _get_tutor_learning_loop_observability_summary=lambda: {
            "available": True,
            "checks": 9,
            "effective_accuracy_pct": 66.7,
            "score_ema_pct": 58.0,
            "recurrence": 2,
            "streak_correct": 0,
            "streak_incorrect": 1,
            "confidence_bias_abs_ema": 1.3,
            "calibration_bias": 0.4,
            "transfer_score": 0.1,
            "fragility_score": 48.0,
            "mode": "error_clinic",
            "phase": "reinforce",
            "topic": "Risk Management",
            "misconceptions_top": ("risk_application",),
            "policy_thresholds": {
                "min_assessments_for_metrics": 4,
                "error_incorrect_rate_threshold": 0.44,
                "retrieval_correct_rate_threshold": 0.78,
                "retrieval_min_streak": 3,
                "retrieval_score_ema_min": 0.61,
                "calibration_bias_guard": 1.25,
            },
            "policy_tuning": {"status": "tuned", "reason": "error_pressure"},
        },
    )
    msg = StudyPlanGUI._build_debug_info_message(dummy, hub={}, graph_status={}, drift={}, perf={}, tutor_summary={})
    assert "Tutor loop thresholds (active):" in msg
    assert "err>=0.44" in msg
    assert "ret>=0.78" in msg
    assert "Tutor loop tuning status/reason: tuned/error_pressure" in msg


def test_build_debug_info_message_includes_rag_embedding_insights_lines():
    dummy = types.SimpleNamespace(
        exam_date="2026-06-01",
        engine=types.SimpleNamespace(CHAPTERS=["A", "B"], competence={"A": 70.0}, SEMANTIC_MODEL_NAME="all-minilm"),
        _get_rag_embedding_insights=lambda: {
            "active_pdf_count": 2,
            "configured_max_sources": 6,
            "active_pdf_total_mb": 143.8,
            "max_pdf_mb": 512.0,
            "active_pdf_names": ["fm_notes.pdf", "question_kit.pdf"],
            "active_pdf_tier_counts": {"syllabus": 1, "notes": 1, "supplemental": 0},
            "active_pdf_details": [
                {
                    "name": "syllabus.pdf",
                    "tier": "syllabus",
                    "size_mb": 3.2,
                    "memory_loaded": True,
                    "disk_doc": True,
                    "embedding_coverage_pct": 100.0,
                },
                {
                    "name": "fm_notes.pdf",
                    "tier": "notes",
                    "size_mb": 143.8,
                    "memory_loaded": False,
                    "disk_doc": True,
                    "embedding_coverage_pct": 73.8,
                },
            ],
            "cache_enabled": True,
            "cache_db_path": "/tmp/ai_runtime_cache_v1.sqlite3",
            "memory_rag_docs": 2,
            "memory_rag_chunks": 244,
            "disk_rag_docs": 2,
            "disk_rag_chunks": 244,
            "disk_postings": 5000,
            "disk_query_cache_rows": 12,
            "disk_embedding_rows": 320,
            "semantic_model_name": "all-minilm",
            "embedding_rows_for_model": 240,
            "embedding_covered_chunk_hashes": 180,
            "embedding_total_chunk_hashes": 244,
            "embedding_coverage_pct": 73.8,
            "cache_debug_rag_doc_hit": 4,
            "cache_debug_rag_query_hit": 2,
            "cache_debug_embedding_hits": 31,
            "cache_debug_embedding_misses": 5,
        },
    )
    msg = StudyPlanGUI._build_debug_info_message(
        dummy,
        hub={},
        graph_status={},
        drift={},
        perf={},
        tutor_summary={"rag_target_count": 2, "rag_target_hit_count": 1, "rag_insufficient_flag": 0, "rag_source_mix": "syllabus:1|notes:1"},
    )
    assert "RAG PDFs active/configured: 2/6" in msg
    assert "RAG PDF tiers: syllabus:1 | notes:1" in msg
    assert "RAG PDF details:" in msg
    assert "RAG cache enabled/db: True (ai_runtime_cache_v1.sqlite3)" in msg
    assert "Embeddings rows total/model: 320/240 (all-minilm)" in msg
    assert "Embeddings coverage active chunks: 180/244 (73.8%)" in msg
    assert "Cache debug doc/query/emb-hit/emb-miss: 4/2/31/5" in msg
    assert "Tutor RAG teaching hits/targets/insufficient: 1/2/0" in msg
    assert "Tutor RAG source mix (latest): syllabus:1|notes:1" in msg


def test_build_debug_info_message_includes_cognitive_observability_lines():
    cog = CognitiveState()
    cog.quiz_active = True
    cog.struggle_mode = True
    cog.last_persist_ok = False
    cog.last_persist_error = "disk write failed due to permissions"
    cog.working_memory.socratic_state = "PRODUCTIVE_STRUGGLE"
    cog.working_memory.active_chapter = "Risk Management"
    cog.working_memory.active_question_id = "q-17"
    cog.working_memory.context_chunks = ["x", "y", "z"]
    cog.working_memory.struggle_flags["latency_spike"] = True
    cog.working_memory.struggle_flags["error_streak"] = True
    cog.working_memory.struggle_flags["hint_dependency"] = False
    cog.posteriors["Risk Management"] = CompetencyPosterior(alpha=3.0, beta=5.0)
    cog.claim_confidence = {"a": 0.2, "b": 0.8, "c": 0.4}

    dummy = types.SimpleNamespace(
        exam_date="2026-06-01",
        engine=types.SimpleNamespace(CHAPTERS=["Risk Management"], competence={}),
        current_topic="Risk Management",
        _cognitive_state=lambda: cog,
    )
    msg = StudyPlanGUI._build_debug_info_message(dummy, hub={}, graph_status={}, drift={}, perf={}, tutor_summary={})
    assert "Cognitive observability: fsm=PRODUCTIVE_STRUGGLE topic=Risk Management" in msg
    assert "Cognitive struggle flags latency/error_streak/hint_dep: 1/1/0" in msg
    assert "Cognitive claim confidence count/avg/low: 3/" in msg
    assert "Cognitive snapshot persist health/error: error/disk write failed due to permissions" in msg


def test_build_tutor_loop_cognitive_runtime_meta_reports_posterior_and_flags(monkeypatch):
    cog = CognitiveState()
    cog.quiz_active = True
    cog.struggle_mode = True
    cog.working_memory.socratic_state = "SCAFFOLD"
    cog.working_memory.active_chapter = "WACC"
    cog.working_memory.context_chunks = ["a", "b"]
    cog.posteriors["WACC"] = CompetencyPosterior(alpha=8.0, beta=2.0)
    dummy = types.SimpleNamespace()
    dummy._is_cognitive_runtime_enabled = lambda: True
    dummy._cognitive_state = lambda: cog
    dummy.current_topic = "WACC"
    meta = StudyPlanGUI._build_tutor_loop_cognitive_runtime_meta(dummy, chapter="WACC")
    assert bool(meta.get("enabled", False)) is True
    assert str(meta.get("topic", "")) == "WACC"
    assert str(meta.get("fsm_state", "")) == "SCAFFOLD"
    assert bool(meta.get("quiz_active", False)) is True
    assert bool(meta.get("struggle_mode", False)) is True
    assert int(meta.get("wm_chunks", 0) or 0) == 2
    assert float(meta.get("posterior_mean", 0.0) or 0.0) > 0.75
    assert float(meta.get("posterior_variance", 1.0) or 1.0) >= 0.0


def test_get_rag_embedding_insights_includes_per_pdf_details_and_tiers(tmp_path):
    pdf1 = tmp_path / "syllabus.pdf"
    pdf2 = tmp_path / "course_notes.pdf"
    pdf1.write_bytes(b"x" * 1024)
    pdf2.write_bytes(b"y" * 2048)
    from studyplan.components.performance.caching import PerformanceCacheService
    dummy = types.SimpleNamespace(
        engine=types.SimpleNamespace(SEMANTIC_MODEL_NAME="all-minilm"),
        _perf_cache=PerformanceCacheService({"cache_max_size": 100, "default_ttl_seconds": 300, "cache_ttl": {}}),
        _ai_cache_debug_last={},
        ai_tutor_rag_max_sources=6,
    )
    dummy._get_ai_tutor_rag_source_pdfs = lambda: [str(pdf1), str(pdf2)]
    dummy._get_ai_tutor_rag_max_pdf_bytes = lambda: 10 * 1024 * 1024
    dummy._ai_cache_enabled = lambda: False
    dummy._ai_tutor_rag_doc_cache_key = types.MethodType(StudyPlanGUI._ai_tutor_rag_doc_cache_key, dummy)
    dummy._classify_ai_tutor_rag_source_tier = types.MethodType(StudyPlanGUI._classify_ai_tutor_rag_source_tier, dummy)
    insights = StudyPlanGUI._get_rag_embedding_insights(dummy)
    details = list(insights.get("active_pdf_details", []) or [])
    assert insights["active_pdf_count"] == 2
    assert insights["active_pdf_tier_counts"]["syllabus"] == 1
    assert insights["active_pdf_tier_counts"]["notes"] == 1
    assert len(details) == 2
    assert {row["tier"] for row in details} == {"syllabus", "notes"}
    assert all("memory_loaded" in row for row in details)


def test_compute_tutor_control_state_enables_send_and_copy_last_when_ready():
    state = compute_tutor_control_state(
        running=False,
        model_ready=True,
        llm_ready=True,
        prompt_ready=True,
        has_history=True,
        has_latest_answer=True,
        has_active_or_history=True,
    )
    assert state["send_enabled"] is True
    assert state["stop_enabled"] is False
    assert state["copy_last_enabled"] is True
    assert state["copy_transcript_enabled"] is True
    assert state["jump_latest_enabled"] is True


def test_format_ui_info_block_lines_splits_long_status_rows_for_readability():
    dummy = types.SimpleNamespace()
    text = StudyPlanGUI._format_ui_info_block_lines(
        dummy,
        ["Intervention: extra topic + shorter breaks until on pace."],
        split_threshold=40,
    )
    assert "Intervention:" in text
    assert "\n" in text
    assert "  extra topic + shorter breaks until on pace." in text


def test_refresh_workbench_header_compact_layout_compacts_without_stacking_in_very_narrow_mode():
    class _FakeButton:
        def __init__(self):
            self.label = ""

        def set_label(self, value):
            self.label = str(value)

    class _FakeRow:
        def __init__(self):
            self.orientation = None
            self.spacing = None

        def set_orientation(self, value):
            self.orientation = value

        def set_spacing(self, value):
            self.spacing = int(value)

    class _FakeScroll:
        def __init__(self):
            self.min_h = None
            self.policy = None

        def set_min_content_height(self, value):
            self.min_h = int(value)

        def set_policy(self, h, v):
            self.policy = (h, v)

    btn = _FakeButton()
    row = _FakeRow()
    scroll = _FakeScroll()
    dummy = types.SimpleNamespace(
        _tile_mode=False,
        _stack_layout_active=False,
        _workbench_quick_actions_row=row,
        _workbench_quick_actions_scroll=scroll,
        _workbench_quick_action_button_labels={btn: ("Focus 25m", "Focus", "F25")},
        get_width=lambda: 1000,
    )
    StudyPlanGUI._refresh_workbench_header_compact_layout(dummy)
    assert btn.label == "F25"
    assert row.orientation is not None
    assert row.spacing == 4
    assert scroll.min_h == 40
    assert scroll.policy is not None


def test_label_readability_helpers_preserve_critical_and_wrapping_behavior():
    class _FakeLabel:
        def __init__(self):
            self._css: set[str] = set()
            self.wrap = None
            self.ellipsize = None
            self.wrap_mode = None
            self.xalign = None
            self.max_width_chars = None

        def add_css_class(self, name):
            self._css.add(str(name))

        def remove_css_class(self, name):
            self._css.discard(str(name))

        def has_css_class(self, name):
            return str(name) in self._css

        def set_wrap(self, value):
            self.wrap = bool(value)

        def set_ellipsize(self, value):
            self.ellipsize = value

        def set_wrap_mode(self, value):
            self.wrap_mode = value

        def set_xalign(self, value):
            self.xalign = float(value)

        def set_max_width_chars(self, value):
            self.max_width_chars = int(value)

        def get_parent(self):
            return None

    dummy = types.SimpleNamespace()
    critical = _FakeLabel()
    wrapped = _FakeLabel()

    StudyPlanGUI._mark_critical_label(dummy, critical, no_wrap=True)
    StudyPlanGUI._mark_wrapping_label(dummy, wrapped, max_width_chars=77)

    assert critical.has_css_class("no-global-ellipsize") is True
    assert critical.wrap is False
    assert StudyPlanGUI._label_should_stay_single_line(dummy, critical) is False

    assert wrapped.has_css_class("allow-wrap") is True
    assert wrapped.wrap is True
    assert wrapped.max_width_chars == 77
    assert StudyPlanGUI._label_should_stay_single_line(dummy, wrapped) is False


def test_set_workbench_refresh_fallback_updates_status_and_panel_text():
    class _FakeLabel:
        def __init__(self):
            self.text = ""

        def get_text(self):
            return self.text

        def set_text(self, value):
            self.text = str(value)

    class _FakeBuffer:
        def __init__(self):
            self.text = ""

        def set_text(self, value):
            self.text = str(value)

    class _FakeTextView:
        def __init__(self):
            self._buf = _FakeBuffer()

        def get_buffer(self):
            return self._buf

    dummy = types.SimpleNamespace(
        _coach_workspace_status_label=_FakeLabel(),
        _coach_workspace_view=_FakeTextView(),
        _insights_workspace_status_label=_FakeLabel(),
        _insights_workspace_view=_FakeTextView(),
        _set_label_text_if_changed=lambda label, text: label.set_text(text),
    )
    report = types.SimpleNamespace(error="RuntimeError", details="boom")

    StudyPlanGUI._set_workbench_refresh_fallback(dummy, "coach", report)
    assert "UI refresh failed" in dummy._coach_workspace_status_label.text
    assert "RuntimeError" in dummy._coach_workspace_view.get_buffer().text

    StudyPlanGUI._set_workbench_refresh_fallback(dummy, "insights", report)
    assert "UI refresh failed" in dummy._insights_workspace_status_label.text
    assert "Diagnostics refresh failed" in dummy._insights_workspace_view.get_buffer().text


def test_refresh_workbench_page_routes_through_safe_render_section():
    calls: list[tuple[str, str]] = []

    def _safe(section_id, render_fn, fallback_fn=None):
        calls.append(("safe", str(section_id)))
        render_fn()
        return True

    dummy = types.SimpleNamespace(
        _safe_render_section=_safe,
        _refresh_tutor_workspace_page=lambda: calls.append(("refresh", "tutor")),
        _refresh_coach_workspace_page=lambda: calls.append(("refresh", "coach")),
        _refresh_insights_workspace_page=lambda: calls.append(("refresh", "insights")),
        _refresh_settings_workspace_page=lambda: calls.append(("refresh", "settings")),
        _refresh_workbench_shell_status=lambda: calls.append(("refresh", "shell")),
        _set_workbench_refresh_fallback=lambda _page, _report: calls.append(("fallback", "workbench")),
    )

    StudyPlanGUI._refresh_workbench_page(dummy, "coach")

    assert calls == [("safe", "coach_workspace"), ("refresh", "coach"), ("refresh", "shell")]


def test_render_study_room_card_guarded_uses_safe_render_section_and_clears_source():
    calls: list[str] = []

    def _safe(section_id, render_fn, fallback_fn=None):
        calls.append(str(section_id))
        render_fn()
        return True

    dummy = types.SimpleNamespace(
        _study_room_update_source=123,
        _safe_render_section=_safe,
        _update_study_room_card_impl=lambda: calls.append("render"),
        _set_study_room_render_fallback=lambda _report: calls.append("fallback"),
    )

    result = StudyPlanGUI._render_study_room_card_guarded(dummy)

    assert result is False
    assert dummy._study_room_update_source is None
    assert calls == ["study_room", "render"]


def test_render_dashboard_guarded_uses_safe_render_section():
    calls: list[str] = []

    def _safe(section_id, render_fn, fallback_fn=None):
        calls.append(str(section_id))
        render_fn()
        return True

    dummy = types.SimpleNamespace(
        _safe_render_section=_safe,
        _render_dashboard=lambda: calls.append("render"),
        _set_dashboard_render_fallback=lambda _report: calls.append("fallback"),
    )

    result = StudyPlanGUI._render_dashboard_guarded(dummy)

    assert result is False
    assert calls == ["dashboard", "render"]


def test_compute_tutor_control_state_running_disables_send_and_copy_last():
    state = compute_tutor_control_state(
        running=True,
        model_ready=True,
        llm_ready=True,
        prompt_ready=True,
        has_history=True,
        has_latest_answer=True,
        has_active_or_history=True,
    )
    assert state["send_enabled"] is False
    assert state["stop_enabled"] is True
    assert state["copy_last_enabled"] is False
    assert state["prompt_editable"] is False
    assert state["quick_prompts_enabled"] is False


def test_compute_tutor_control_state_blocks_send_without_prompt_or_model():
    no_prompt = compute_tutor_control_state(
        running=False,
        model_ready=True,
        llm_ready=True,
        prompt_ready=False,
        has_history=False,
        has_latest_answer=False,
        has_active_or_history=False,
    )
    no_model = compute_tutor_control_state(
        running=False,
        model_ready=False,
        llm_ready=True,
        prompt_ready=True,
        has_history=False,
        has_latest_answer=False,
        has_active_or_history=False,
    )
    assert no_prompt["send_enabled"] is False
    assert no_model["send_enabled"] is False
    assert no_prompt["stop_enabled"] is False
    assert no_model["stop_enabled"] is False


def test_should_keep_response_bottom_respects_auto_scroll_toggle():
    assert should_keep_response_bottom(auto_scroll_enabled=False, force_scroll=True, near_bottom=True) is False
    assert should_keep_response_bottom(auto_scroll_enabled=False, force_scroll=False, near_bottom=False) is False
    assert should_keep_response_bottom(auto_scroll_enabled=True, force_scroll=False, near_bottom=False) is False
    assert should_keep_response_bottom(auto_scroll_enabled=True, force_scroll=True, near_bottom=False) is True
    assert should_keep_response_bottom(auto_scroll_enabled=True, force_scroll=False, near_bottom=True) is True


def test_should_force_stream_flush_when_render_lags_latest_chunk():
    assert (
        should_force_stream_flush(
            last_chunk_monotonic=10.0,
            last_render_monotonic=9.5,
            now_monotonic=11.2,
            stall_ms=900,
        )
        is True
    )


def test_should_force_stream_flush_false_when_render_is_caught_up():
    assert (
        should_force_stream_flush(
            last_chunk_monotonic=10.0,
            last_render_monotonic=10.0,
            now_monotonic=12.0,
            stall_ms=900,
        )
        is False
    )
    assert (
        should_force_stream_flush(
            last_chunk_monotonic=10.0,
            last_render_monotonic=9.9,
            now_monotonic=10.5,
            stall_ms=900,
        )
        is False
    )


def test_normalize_tutor_timeout_seconds_clamps_bounds():
    assert normalize_tutor_timeout_seconds("bad", default=90, minimum=20, maximum=240) == 90
    assert normalize_tutor_timeout_seconds(5, default=90, minimum=20, maximum=240) == 20
    assert normalize_tutor_timeout_seconds(999, default=90, minimum=20, maximum=240) == 240
    assert normalize_tutor_timeout_seconds(75, default=90, minimum=20, maximum=240) == 75


def test_classify_ollama_error_model_missing():
    code, message = classify_ollama_error("model 'foo' not found")
    assert code == "model_missing"
    assert "ollama pull" in message.lower()


def test_classify_ollama_error_host_unreachable():
    code, message = classify_ollama_error("Connection refused", host="http://127.0.0.1:11434")
    assert code == "host_unreachable"
    assert "cannot reach ollama" in message.lower()


def test_classify_ollama_error_busy():
    code, message = classify_ollama_error("server busy, try again")
    assert code == "busy"
    assert "busy" in message.lower()


def test_extract_tutor_coverage_targets_and_queries_for_multi_concept_prompt():
    prompt = "Compare CAPM and WACC, then explain NPV sensitivity and working capital risk."
    targets = extract_tutor_coverage_targets(prompt, max_targets=6)
    queries = build_targeted_rag_queries(prompt, max_targets=4)
    assert len(targets) >= 3
    assert len(queries) >= 2
    assert any("capm" in t.lower() for t in targets)
    assert any("wacc" in t.lower() for t in targets)


def test_extract_tutor_coverage_targets_uses_acronyms_for_long_single_clause_prompt():
    prompt = "In one integrated explanation discuss CAPM WACC NPV and how they interact in project decisions under risk."
    targets = extract_tutor_coverage_targets(prompt, max_targets=6)
    joined = " | ".join(targets).lower()
    assert "capm" in joined
    assert "wacc" in joined
    assert "npv" in joined


def test_build_targeted_rag_queries_adds_relationship_blends():
    prompt = "Compare CAPM and WACC and explain NPV sensitivity."
    queries = build_targeted_rag_queries(prompt, max_targets=4)
    assert any("relationship" in q.lower() for q in queries)


def test_assess_tutor_coverage_reports_hits_and_misses():
    targets = ["CAPM assumptions", "WACC formula", "NPV sensitivity"]
    text = "CAPM assumptions matter. WACC formula uses weighted costs."
    summary = assess_tutor_coverage(text, targets)
    assert summary["target_count"] == 3
    assert summary["hit_count"] == 2
    assert "NPV sensitivity" in summary["missed_targets"]


def test_build_tutor_coverage_checklist_note_when_targets_are_missed():
    note = build_tutor_coverage_checklist_note(
        "CAPM assumptions are important and WACC formula is used for discounting.",
        ["CAPM assumptions", "WACC formula", "NPV sensitivity"],
    )
    assert "Coverage checklist:" in note
    assert "T3: NPV sensitivity (follow-up needed)" in note


def test_can_auto_execute_ai_tutor_action_respects_mode_and_confirmation():
    dummy = types.SimpleNamespace()
    dummy._coerce_ai_tutor_autonomy_mode = types.MethodType(StudyPlanGUI._coerce_ai_tutor_autonomy_mode, dummy)
    assert StudyPlanGUI._can_auto_execute_ai_tutor_action(dummy, "focus_start", "suggest", False) is False
    assert StudyPlanGUI._can_auto_execute_ai_tutor_action(dummy, "focus_start", "assist", False) is True
    assert StudyPlanGUI._can_auto_execute_ai_tutor_action(dummy, "review_start", "assist", True) is False
    assert StudyPlanGUI._can_auto_execute_ai_tutor_action(dummy, "review_start", "assist", False) is True
    assert StudyPlanGUI._can_auto_execute_ai_tutor_action(dummy, "drill_start", "assist", False) is True
    assert StudyPlanGUI._can_auto_execute_ai_tutor_action(dummy, "review_start", "cockpit", True) is True


def test_effective_ai_tutor_autonomy_mode_follows_preference():
    """Autopilot on/off does not override autonomy mode; mode controls how boldly actions run."""
    dummy = types.SimpleNamespace(
        ai_tutor_autopilot_enabled=True,
        ai_tutor_autonomy_mode="suggest",
    )
    dummy._coerce_ai_tutor_autonomy_mode = types.MethodType(StudyPlanGUI._coerce_ai_tutor_autonomy_mode, dummy)
    assert StudyPlanGUI._effective_ai_tutor_autonomy_mode(dummy) == "suggest"
    dummy.ai_tutor_autonomy_mode = "cockpit"
    assert StudyPlanGUI._effective_ai_tutor_autonomy_mode(dummy) == "cockpit"
    dummy.ai_tutor_autopilot_enabled = False
    assert StudyPlanGUI._effective_ai_tutor_autonomy_mode(dummy) == "cockpit"


def test_should_request_global_ai_tutor_decision_only_on_change_or_refresh():
    dummy = types.SimpleNamespace(
        _ai_tutor_global_last_event_sig="",
        _ai_tutor_global_last_decision_at=0.0,
        _ai_tutor_global_quiet_until=0.0,
    )
    dummy._ai_cache_sha1 = types.MethodType(StudyPlanGUI._ai_cache_sha1, dummy)
    dummy._build_ai_tutor_autopilot_event_signature = types.MethodType(
        StudyPlanGUI._build_ai_tutor_autopilot_event_signature, dummy
    )
    dummy._should_request_global_ai_tutor_decision = types.MethodType(
        StudyPlanGUI._should_request_global_ai_tutor_decision, dummy
    )
    snapshot = {
        "current_topic": "Topic A",
        "coach_pick": "Topic A",
        "must_review_due": 2,
        "overdue_srs_count": 1,
        "new_srs_count": 0,
        "pomodoro_active": False,
        "pomodoro_paused": False,
        "pomodoro_remaining_sec": 0,
        "focus_trend_14d": {"integrity_pct": 72.0},
        "weak_topics_top3": ["Topic A"],
        "risk_snapshot_top3": [],
        "due_snapshot_top3": [],
        "runtime_scope": "app_wide",
    }
    should1, reason1, sig1 = StudyPlanGUI._should_request_global_ai_tutor_decision(
        dummy, snapshot, now_ts=100.0
    )
    assert should1 is True
    assert reason1 == "first_run"
    assert sig1
    dummy._ai_tutor_global_last_event_sig = sig1
    dummy._ai_tutor_global_last_decision_at = 100.0

    should2, reason2, _sig2 = StudyPlanGUI._should_request_global_ai_tutor_decision(
        dummy, snapshot, now_ts=160.0
    )
    assert should2 is False
    assert reason2 == "no_material_change"

    changed = dict(snapshot)
    changed["must_review_due"] = 5
    should3, reason3, _sig3 = StudyPlanGUI._should_request_global_ai_tutor_decision(
        dummy, changed, now_ts=170.0
    )
    assert should3 is True
    assert reason3 == "state_changed"


def test_should_request_global_ai_tutor_decision_respects_quiet_window():
    dummy = types.SimpleNamespace(
        _ai_tutor_global_last_event_sig="",
        _ai_tutor_global_last_decision_at=100.0,
        _ai_tutor_global_quiet_until=260.0,
    )
    dummy._ai_cache_sha1 = types.MethodType(StudyPlanGUI._ai_cache_sha1, dummy)
    dummy._build_ai_tutor_autopilot_event_signature = types.MethodType(
        StudyPlanGUI._build_ai_tutor_autopilot_event_signature, dummy
    )
    dummy._should_request_global_ai_tutor_decision = types.MethodType(
        StudyPlanGUI._should_request_global_ai_tutor_decision, dummy
    )
    snapshot = {
        "current_topic": "Topic A",
        "coach_pick": "Topic A",
        "must_review_due": 2,
        "overdue_srs_count": 1,
        "new_srs_count": 0,
        "pomodoro_active": False,
        "pomodoro_paused": False,
        "pomodoro_remaining_sec": 0,
        "focus_trend_14d": {"integrity_pct": 72.0},
        "weak_topics_top3": ["Topic A"],
        "risk_snapshot_top3": [],
        "due_snapshot_top3": [],
        "runtime_scope": "app_wide",
    }
    _first, _reason_first, sig = StudyPlanGUI._should_request_global_ai_tutor_decision(
        dummy, snapshot, now_ts=100.0
    )
    dummy._ai_tutor_global_last_event_sig = sig
    should2, reason2, _sig2 = StudyPlanGUI._should_request_global_ai_tutor_decision(
        dummy, snapshot, now_ts=200.0
    )
    assert should2 is False
    assert reason2 == "quiet_window"


def test_build_ai_tutor_autopilot_prompt_includes_runtime_contract():
    dummy = _make_dummy()
    prompt = StudyPlanGUI._build_ai_tutor_autopilot_prompt(
        dummy,
        {
            "current_topic": "Topic A",
            "coach_pick": "Topic A",
            "days_to_exam": 18,
            "must_review_due": 5,
            "weak_topics_top3": ["Topic A"],
            "learning_context": "Topic A weak",
            "allowed_actions": ["focus_start", "review_start"],
        },
    )
    assert "Runtime contract (autopilot):" in prompt
    assert "first-class local model inside StudyPlan" in prompt
    assert "Exam phase: final_push" in prompt


def test_normalize_ai_tutor_action_plan_validates_action_and_topic():
    engine = types.SimpleNamespace(CHAPTERS=["Topic A", "Topic B"])
    dummy = types.SimpleNamespace(engine=engine)
    dummy._coerce_ai_coach_duration = types.MethodType(StudyPlanGUI._coerce_ai_coach_duration, dummy)
    snapshot = {"current_topic": "Topic A", "coach_pick": "Topic A"}
    plan, err = StudyPlanGUI._normalize_ai_tutor_action_plan(
        dummy,
        {"action": "quiz_start", "topic": "Unknown", "duration_minutes": 120, "reason": "run"},
        snapshot,
    )
    assert err is None
    assert plan is not None
    assert plan["action"] == "quiz_start"
    assert plan["topic"] == "Topic A"
    assert plan["duration_minutes"] == 60

    bad_plan, bad_err = StudyPlanGUI._normalize_ai_tutor_action_plan(
        dummy,
        {"action": "unknown_action", "topic": "Topic A"},
        snapshot,
    )
    assert bad_plan is None
    assert bad_err is not None


def test_normalize_ai_tutor_action_plan_accepts_tutor_open_action():
    engine = types.SimpleNamespace(CHAPTERS=["Topic A", "Topic B"])
    dummy = types.SimpleNamespace(engine=engine)
    dummy._coerce_ai_coach_duration = types.MethodType(StudyPlanGUI._coerce_ai_coach_duration, dummy)
    snapshot = {"current_topic": "Topic B", "coach_pick": "Topic A"}
    plan, err = StudyPlanGUI._normalize_ai_tutor_action_plan(
        dummy,
        {"action": "tutor_open", "topic": "", "duration_minutes": 20, "reason": "show cockpit"},
        snapshot,
    )
    assert err is None
    assert plan is not None
    assert plan["action"] == "tutor_open"


def test_normalize_ai_tutor_action_plan_adds_evidence_when_missing():
    engine = types.SimpleNamespace(CHAPTERS=["Topic A", "Topic B"])
    dummy = types.SimpleNamespace(engine=engine)
    dummy._coerce_ai_coach_duration = types.MethodType(StudyPlanGUI._coerce_ai_coach_duration, dummy)
    dummy._derive_ai_tutor_action_evidence = types.MethodType(
        StudyPlanGUI._derive_ai_tutor_action_evidence, dummy
    )
    snapshot = {
        "current_topic": "Topic A",
        "coach_pick": "Topic A",
        "must_review_due": 4,
        "focus_trend_14d": {"integrity_pct": 68},
        "weak_topics_top3": [{"chapter": "Topic A"}],
        "due_snapshot_top3": [{"chapter": "Topic A", "due": 4}],
    }
    plan, err = StudyPlanGUI._normalize_ai_tutor_action_plan(
        dummy,
        {"action": "review_start", "topic": "Topic A", "duration_minutes": 20, "reason": "due pressure"},
        snapshot,
    )
    assert err is None
    assert plan is not None
    assert isinstance(plan.get("evidence"), list)
    assert any(str(item).startswith("must_review_due=") for item in list(plan["evidence"]))


def test_normalize_ai_tutor_action_plan_accepts_coach_open_action():
    engine = types.SimpleNamespace(CHAPTERS=["Topic A", "Topic B"])
    dummy = types.SimpleNamespace(engine=engine)
    dummy._coerce_ai_coach_duration = types.MethodType(StudyPlanGUI._coerce_ai_coach_duration, dummy)
    snapshot = {"current_topic": "Topic B", "coach_pick": "Topic A"}
    plan, err = StudyPlanGUI._normalize_ai_tutor_action_plan(
        dummy,
        {"action": "coach_open", "topic": "", "duration_minutes": 20, "reason": "show coach"},
        snapshot,
    )
    assert err is None
    assert plan is not None
    assert plan["action"] == "coach_open"


def test_validate_generated_gap_questions_strict_gate():
    engine = types.SimpleNamespace(
        CHAPTERS=["Topic A"],
        QUESTIONS={
            "Topic A": [
                {
                    "question": "Existing Q",
                    "options": ["A", "B", "C", "D"],
                    "correct": "A",
                    "explanation": "Existing",
                }
            ]
        },
        _question_dedupe_key=lambda row: (
            str(row.get("question", "")).strip().lower(),
            tuple(str(v).strip().lower() for v in list(row.get("options", []) or [])),
            str(row.get("correct", "")).strip().lower(),
        ),
    )
    dummy = types.SimpleNamespace(engine=engine)
    valid, reasons = StudyPlanGUI._validate_generated_gap_questions(
        dummy,
        "Topic A",
        [
            {
                "question": "What is CAPM used for?",
                "options": ["Return estimate", "Stock split", "Tax filing", "Inventory count"],
                "correct": "Return estimate",
                "explanation": "CAPM estimates required return.",
            },
            {
                "question": "Bad duplicate options",
                "options": ["A", "A", "C", "D"],
                "correct": "A",
                "explanation": "Duplicate options should fail.",
            },
        ],
    )
    assert len(valid) == 1
    assert "duplicate_options" in reasons


def test_validate_generated_gap_questions_non_strict_allows_shorter_rows():
    engine = types.SimpleNamespace(
        CHAPTERS=["Topic A"],
        QUESTIONS={"Topic A": []},
        _question_dedupe_key=lambda row: (
            str(row.get("question", "")).strip().lower(),
            tuple(str(v).strip().lower() for v in list(row.get("options", []) or [])),
            str(row.get("correct", "")).strip().lower(),
        ),
    )
    dummy = types.SimpleNamespace(engine=engine, ai_tutor_gap_autosave_strict_gate=False)
    sample = [
        {
            "question": "CAPM?",
            "options": ["Return", "Tax", "Audit", "Sales"],
            "correct": "Return",
            "explanation": "",
        }
    ]
    strict_valid, strict_reasons = StudyPlanGUI._validate_generated_gap_questions(
        dummy,
        "Topic A",
        sample,
        strict_gate=True,
    )
    basic_valid, basic_reasons = StudyPlanGUI._validate_generated_gap_questions(
        dummy,
        "Topic A",
        sample,
        strict_gate=False,
    )
    assert len(strict_valid) == 0
    assert "question_too_short" in strict_reasons
    assert len(basic_valid) == 1
    assert "question_too_short" not in basic_reasons


def test_validate_generated_gap_questions_uses_engine_sanitizer_for_placeholder_options():
    def _sanitize(chapter, row, source="runtime", quarantine_on_fail=False):
        if list(row.get("options", []) or []) == ["A", "B", "C", "D"]:
            return None, ["placeholder_options_only"], {"repaired": False}
        return row, [], {"repaired": False}

    engine = types.SimpleNamespace(
        CHAPTERS=["Topic A"],
        QUESTIONS={"Topic A": []},
        _sanitize_question_bank_row=_sanitize,
        _question_dedupe_key=lambda row: (
            str(row.get("question", "")).strip().lower(),
            tuple(str(v).strip().lower() for v in list(row.get("options", []) or [])),
            str(row.get("correct", "")).strip().lower(),
        ),
    )
    dummy = types.SimpleNamespace(engine=engine)
    valid, reasons = StudyPlanGUI._validate_generated_gap_questions(
        dummy,
        "Topic A",
        [
            {
                "question": "Which statement is correct?",
                "options": ["A", "B", "C", "D"],
                "correct": "A",
                "explanation": "Placeholder-only options should be rejected.",
            }
        ],
    )
    assert valid == []
    assert "placeholder_options_only" in reasons


def test_parse_generated_gap_questions_normalizes_common_schema_variants():
    dummy = types.SimpleNamespace()
    dummy._extract_first_json_object = types.MethodType(StudyPlanGUI._extract_first_json_object, dummy)
    payload = {
        "topic": "Topic A",
        "items": [
            {
                "prompt": "CAPM is mainly used to estimate what?",
                "choices": {"A": "Tax payable", "B": "Required return", "C": "Inventory EOQ", "D": "Dividend cover"},
                "answer": "B",
                "rationale": "CAPM estimates required return.",
            },
            {
                "stem": "Which ratio is used in Miller-Orr inputs here?",
                "answers": [
                    {"label": "A", "text": "Variance of daily cash flows"},
                    {"label": "B", "text": "PE ratio"},
                    {"label": "C", "text": "Dividend yield"},
                    {"label": "D", "text": "Gross margin"},
                ],
                "correct_option": 0,
                "why": "Miller-Orr uses variance of cash flows.",
            },
        ],
    }
    chapter, rows, err = StudyPlanGUI._parse_generated_gap_questions(dummy, json.dumps(payload, ensure_ascii=True))
    assert chapter == "Topic A"
    assert err is None
    assert len(rows) == 2
    assert rows[0]["question"].startswith("CAPM is mainly used")
    assert rows[0]["correct"] == "Required return"
    assert rows[1]["correct"] == "Variance of daily cash flows"
    assert len(rows[0]["options"]) == 4
    assert len(rows[1]["options"]) == 4


def test_parse_generated_gap_questions_recovers_labeled_option_strings_and_warns_on_dropped_rows():
    dummy = types.SimpleNamespace()
    dummy._extract_first_json_object = types.MethodType(StudyPlanGUI._extract_first_json_object, dummy)
    text = json.dumps(
        {
            "chapter": "Topic A",
            "questions": [
                {
                    "question_text": "What does EOQ primarily optimize?",
                    "options": ["A) total inventory cost", "B) tax burden", "C) interest cover", "D) gearing ratio"],
                    "correct_answer": "A",
                    "explanation": "EOQ minimizes total ordering + holding costs.",
                },
                "not-a-row",
            ],
        },
        ensure_ascii=True,
    )
    chapter, rows, err = StudyPlanGUI._parse_generated_gap_questions(dummy, text)
    assert chapter == "Topic A"
    assert len(rows) == 1
    assert rows[0]["correct"] == "total inventory cost"
    assert "Recovered 1 rows; dropped 1 malformed row" in str(err or "")


def test_generate_gap_drill_questions_uses_recovery_status_on_ollama_error():
    engine = types.SimpleNamespace(CHAPTERS=["Topic A"])
    dummy = types.SimpleNamespace(
        engine=engine,
        ai_tutor_gap_generation_enabled=True,
        local_llm_enabled=True,
        _build_local_llm_model_failover_sequence=lambda **_kw: (["model-a"], None),
        _select_local_llm_model=lambda **_kw: ("model-a", None),
        _build_gap_generation_prompt=lambda chapter, count, snapshot: "prompt",
        _ollama_generate_text=lambda model, prompt: ("", "connection refused"),
        _append_gap_question_quarantine=lambda *_args, **_kw: None,
        _record_ai_tutor_autopilot_metrics=lambda *_args, **_kw: None,
        _ai_tutor_autopilot_stats={},
        _compose_ollama_recovery_status=lambda err, **_kw: "RECOVERY STATUS",
    )

    ok, msg = StudyPlanGUI._generate_gap_drill_questions(dummy, "Topic A", snapshot={})

    assert ok is False
    assert msg == "RECOVERY STATUS"


def test_generate_gap_drill_questions_uses_guardrail_status_for_parse_reject():
    engine = types.SimpleNamespace(CHAPTERS=["Topic A"])
    dummy = types.SimpleNamespace(
        engine=engine,
        ai_tutor_gap_generation_enabled=True,
        local_llm_enabled=True,
        _build_local_llm_model_failover_sequence=lambda **_kw: (["model-a"], None),
        _select_local_llm_model=lambda **_kw: ("model-a", None),
        _build_gap_generation_prompt=lambda chapter, count, snapshot: "prompt",
        _ollama_generate_text=lambda model, prompt: ("{}", None),
        _parse_generated_gap_questions=lambda text: ("Topic A", [], "No JSON object found."),
        _append_gap_question_quarantine=lambda *_args, **_kw: None,
        _record_ai_tutor_autopilot_metrics=lambda *_args, **_kw: None,
        _compose_ollama_guardrail_status=lambda detail, **_kw: "GUARDRAIL STATUS",
        _ai_tutor_autopilot_stats={},
    )

    ok, msg = StudyPlanGUI._generate_gap_drill_questions(dummy, "Topic A", snapshot={})

    assert ok is False
    assert msg == "GUARDRAIL STATUS"


def test_generate_gap_drill_questions_failover_uses_second_model():
    """When first model returns LLM error, second model is tried and success uses its response."""
    engine = types.SimpleNamespace(CHAPTERS=["Topic A"])
    valid_json = json.dumps({
        "chapter": "Topic A",
        "questions": [
            {
                "question": "What is the primary objective of financial reporting?",
                "options": ["A", "B", "C", "D"],
                "correct": "A",
                "explanation": "Because.",
            },
        ],
    })
    calls = []

    def _ollama(model, prompt):
        calls.append(model)
        if model == "model-1":
            return ("", "connection refused")
        return (valid_json, None)

    def _parse(text):
        if not text or "connection refused" in str(text):
            return ("Topic A", [], "No JSON")
        data = json.loads(text)
        ch = data.get("chapter", "")
        qs = data.get("questions", [])
        return (ch, qs, None)

    valid_row = {
        "question": "What is the primary objective of financial reporting?",
        "options": ["A", "B", "C", "D"],
        "correct": "A",
        "explanation": "Because.",
    }

    dummy = types.SimpleNamespace(
        engine=engine,
        ai_tutor_gap_generation_enabled=True,
        local_llm_enabled=True,
        ai_tutor_gap_autosave_strict_gate=True,
        ai_tutor_gap_autosave_enabled=True,
        _build_local_llm_model_failover_sequence=lambda **_kw: (["model-1", "model-2"], None),
        _build_gap_generation_prompt=lambda chapter, count, snapshot: "prompt",
        _ollama_generate_text=_ollama,
        _parse_generated_gap_questions=lambda text: _parse(text),
        _validate_generated_gap_questions=lambda ch, q, **kw: ([valid_row] if q else [], []),
        _save_generated_gap_questions=lambda ch, rows: (len(rows), False),
        _record_ai_tutor_autopilot_metrics=lambda *_args, **_kw: None,
        _ai_tutor_autopilot_stats={},
    )

    ok, msg = StudyPlanGUI._generate_gap_drill_questions(dummy, "Topic A", snapshot={})

    assert ok is True
    assert "1" in msg or "saved" in msg.lower()
    assert "model-1" in calls and "model-2" in calls


def test_generate_gap_drill_questions_shows_storage_error_when_save_fails():
    """When _save_generated_gap_questions returns (0, True), user sees storage error message."""
    engine = types.SimpleNamespace(CHAPTERS=["Topic A"])
    valid_json = json.dumps({
        "chapter": "Topic A",
        "questions": [
            {"question": "Q?", "options": ["A", "B", "C", "D"], "correct": "A", "explanation": "Ok."},
        ],
    })
    valid_row = {"question": "Q?", "options": ["A", "B", "C", "D"], "correct": "A", "explanation": "Ok."}
    dummy = types.SimpleNamespace(
        engine=engine,
        ai_tutor_gap_generation_enabled=True,
        local_llm_enabled=True,
        ai_tutor_gap_autosave_strict_gate=True,
        ai_tutor_gap_autosave_enabled=True,
        _build_local_llm_model_failover_sequence=lambda **_kw: (["model-a"], None),
        _build_gap_generation_prompt=lambda chapter, count, snapshot: "prompt",
        _ollama_generate_text=lambda model, prompt: (valid_json, None),
        _parse_generated_gap_questions=lambda text: ("Topic A", [valid_row], None),
        _validate_generated_gap_questions=lambda ch, q, **kw: ([valid_row], []),
        _save_generated_gap_questions=lambda ch, rows: (0, True),
        _record_ai_tutor_autopilot_metrics=lambda *_args, **_kw: None,
        _append_gap_question_quarantine=lambda *_args, **_kw: None,
        _ai_tutor_autopilot_stats={},
    )
    ok, msg = StudyPlanGUI._generate_gap_drill_questions(dummy, "Topic A", snapshot={})
    assert ok is False
    assert "could not be saved" in msg or "storage error" in msg.lower()


def test_run_daily_auto_question_generation_if_due_does_not_advance_date_on_failure():
    """When _generate_gap_drill_questions returns False, last_auto_question_generation_date is not updated."""
    today = datetime.date.today().isoformat()
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    engine = types.SimpleNamespace(CHAPTERS=["Chapter 1"])
    dummy = types.SimpleNamespace(
        engine=engine,
        _core_runtime_shutdown=False,
        last_auto_question_generation_date=yesterday,
        ai_tutor_gap_generation_enabled=True,
        local_llm_enabled=True,
        current_topic="Chapter 1",
        coach_pick="Chapter 1",
        _get_total_question_count=lambda: 100,
        _build_ai_tutor_autopilot_snapshot=lambda: {},
        _generate_gap_drill_questions=lambda topic, snapshot, requested_count=5: (False, "mock failure"),
        save_preferences=lambda: None,
    )
    StudyPlanGUI._run_daily_auto_question_generation_if_due(dummy)
    assert getattr(dummy, "last_auto_question_generation_date", "") == yesterday


def test_normalize_ai_tutor_action_plan_section_c_requires_confirmation():
    engine = types.SimpleNamespace(CHAPTERS=["Topic A", "Topic B"])
    dummy = types.SimpleNamespace(engine=engine)
    dummy._coerce_ai_coach_duration = types.MethodType(StudyPlanGUI._coerce_ai_coach_duration, dummy)
    snapshot = {"current_topic": "Topic A", "coach_pick": "Topic A"}
    plan, err = StudyPlanGUI._normalize_ai_tutor_action_plan(
        dummy,
        {"action": "section_c_start", "topic": "Topic B", "duration_minutes": 30, "reason": "long-form practice"},
        snapshot,
    )
    assert err is None
    assert isinstance(plan, dict)
    assert plan["action"] == "section_c_start"
    assert plan["topic"] == "Topic B"
    assert plan["requires_confirmation"] is True


def test_parse_generated_section_c_question_accepts_valid_json():
    engine = types.SimpleNamespace(CHAPTERS=["Topic A"])
    dummy = types.SimpleNamespace(engine=engine)
    dummy._extract_first_json_object = types.MethodType(StudyPlanGUI._extract_first_json_object, dummy)
    dummy._section_c_question_id = types.MethodType(StudyPlanGUI._section_c_question_id, dummy)
    dummy._normalize_section_c_question = types.MethodType(StudyPlanGUI._normalize_section_c_question, dummy)
    parsed, err = StudyPlanGUI._parse_generated_section_c_question(
        dummy,
        json.dumps(
            {
                "chapter": "Topic A",
                "prompt": "Advise on working capital funding policy under changing rates.",
                "exhibits": ["Given cash-flow forecast and financing options."],
                "required_tasks": ["Evaluate alternatives.", "Recommend with justification."],
                "marking_rubric": [
                    {"criterion": "Technical accuracy", "max_marks": 8},
                    {"criterion": "Recommendation quality", "max_marks": 6},
                ],
                "model_answer_outline": ["Framework", "Workings", "Conclusion"],
                "time_budget_minutes": 45,
            },
            ensure_ascii=True,
        ),
        "Topic A",
    )
    assert err is None
    assert isinstance(parsed, dict)
    assert parsed["chapter"] == "Topic A"
    assert parsed["time_budget_minutes"] == 45


def test_section_c_bank_upsert_and_reload_roundtrip(tmp_path, monkeypatch):
    bank_path = tmp_path / "section_c_questions.json"
    monkeypatch.setenv("STUDYPLAN_SECTION_C_BANK_PATH", str(bank_path))
    engine = types.SimpleNamespace(CHAPTERS=["Topic A"])
    dummy = types.SimpleNamespace(
        engine=engine,
        _section_c_question_bank={},
        _section_c_question_bank_loaded=False,
    )
    dummy._section_c_question_bank_path = types.MethodType(StudyPlanGUI._section_c_question_bank_path, dummy)
    dummy._section_c_question_id = types.MethodType(StudyPlanGUI._section_c_question_id, dummy)
    dummy._normalize_section_c_question = types.MethodType(StudyPlanGUI._normalize_section_c_question, dummy)
    dummy._load_section_c_question_bank = types.MethodType(StudyPlanGUI._load_section_c_question_bank, dummy)
    dummy._save_section_c_question_bank = types.MethodType(StudyPlanGUI._save_section_c_question_bank, dummy)
    dummy._upsert_section_c_question = types.MethodType(StudyPlanGUI._upsert_section_c_question, dummy)
    dummy._get_section_c_questions = types.MethodType(StudyPlanGUI._get_section_c_questions, dummy)

    def _atomic_write(path, text, mode=0o600):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(text or ""))
        try:
            os.chmod(path, int(mode))
        except Exception:
            pass

    dummy._atomic_write_text_file = _atomic_write
    dummy._secure_user_path = lambda *_args, **_kwargs: None

    saved = StudyPlanGUI._upsert_section_c_question(
        dummy,
        "Topic A",
        {
            "chapter": "Topic A",
            "prompt": "Evaluate whether changing credit terms improves NPV.",
            "required_tasks": ["Compute impact.", "Recommend policy."],
            "marking_rubric": [
                {"criterion": "Method", "max_marks": 8},
                {"criterion": "Conclusion", "max_marks": 6},
            ],
            "model_answer_outline": ["Set up assumptions", "Compute", "Conclude"],
            "time_budget_minutes": 40,
        },
        persist=True,
    )
    assert isinstance(saved, dict)
    assert bank_path.exists()

    dummy._section_c_question_bank = {}
    dummy._section_c_question_bank_loaded = False
    rows = StudyPlanGUI._get_section_c_questions(dummy, "Topic A")
    assert len(rows) == 1
    assert rows[0]["prompt"].startswith("Evaluate whether changing credit terms")


def test_parse_section_c_evaluation_payload_clamps_scores():
    dummy = types.SimpleNamespace()
    dummy._extract_first_json_object = types.MethodType(StudyPlanGUI._extract_first_json_object, dummy)
    question = {
        "marking_rubric": [
            {"criterion": "Technical accuracy", "max_marks": 8},
            {"criterion": "Recommendation", "max_marks": 6},
        ]
    }
    payload = json.dumps(
        {
            "total_mark": 99,
            "max_mark": 99,
            "criterion_scores": [
                {"criterion": "Technical accuracy", "score": 12, "max_mark": 8, "feedback": "Good."},
                {"criterion": "Recommendation", "score": -2, "max_mark": 6, "feedback": "Weak."},
            ],
            "strengths": ["Clear method"],
            "improvements": ["Stronger recommendation linkage"],
            "next_drill": "Rework recommendation paragraph.",
        },
        ensure_ascii=True,
    )
    parsed, err = StudyPlanGUI._parse_section_c_evaluation_payload(dummy, payload, question)
    assert err is None
    assert isinstance(parsed, dict)
    assert parsed["max_mark"] == 14
    assert parsed["total_mark"] <= 14
    rows = list(parsed.get("criterion_scores", []) or [])
    assert rows[0]["score"] == 8
    assert rows[1]["score"] == 0


def test_parse_section_c_evaluation_payload_backfills_missing_rubric_rows():
    dummy = types.SimpleNamespace()
    dummy._extract_first_json_object = types.MethodType(StudyPlanGUI._extract_first_json_object, dummy)
    question = {
        "marking_rubric": [
            {"criterion": "Technical application to case facts", "max_marks": 8},
            {"criterion": "Method and workings", "max_marks": 6},
            {"criterion": "Recommendation", "max_marks": 6},
        ]
    }
    payload = json.dumps(
        {
            "total_mark": 7,
            "criterion_scores": [
                {"criterion": "Technical application to case facts", "score": 7, "max_mark": 8, "feedback": "Good case linkage."}
            ],
            "strengths": ["Applied to case"],
            "improvements": ["Add recommendation"],
            "next_drill": "Add a conclusion paragraph.",
        },
        ensure_ascii=True,
    )
    parsed, err = StudyPlanGUI._parse_section_c_evaluation_payload(dummy, payload, question)
    assert err is None
    assert isinstance(parsed, dict)
    rows = list(parsed.get("criterion_scores", []) or [])
    assert len(rows) == 3
    assert rows[0]["criterion"] == "Technical application to case facts"
    assert rows[0]["score"] == 7
    assert rows[1]["score"] == 0
    assert rows[2]["score"] == 0


def test_section_c_deterministic_examiner_style_rewards_applied_answer():
    dummy = types.SimpleNamespace()
    dummy._evaluate_section_c_response_deterministic = types.MethodType(
        StudyPlanGUI._evaluate_section_c_response_deterministic,
        dummy,
    )
    question = {
        "prompt": "Advise on receivables policy where sales are 2.4m and discount terms are under review.",
        "exhibits": ["Cost of funding 11%. Bad debts expected to move by 0.7%."],
        "required_tasks": [
            "Calculate the net benefit of the proposed discount.",
            "State assumptions and discuss risks.",
            "Recommend a policy with justification.",
        ],
        "marking_rubric": [
            {"criterion": "Technical application to case facts", "max_marks": 8},
            {"criterion": "Method, workings, and assumptions", "max_marks": 6},
            {"criterion": "Evaluation and recommendation", "max_marks": 4},
            {"criterion": "Structure and exam communication", "max_marks": 2},
        ],
        "time_budget_minutes": 45,
    }
    strong_response = (
        "Objective: decide whether the early-settlement discount improves value.\n\n"
        "Workings: incremental discount cost is 2.4m x 2% x uptake. Funding release is days reduced/365 x 2.4m x 11%. "
        "Assume uptake rises to 60% and collection days drop from 52 to 39.\n\n"
        "Evaluation: base case gives a positive net benefit, but sensitivity to uptake and bad debt change is material. "
        "Risk: if uptake is below 45%, value turns negative.\n\n"
        "Recommendation: adopt with a monitored threshold and review after one quarter."
    )
    weak_response = "Discount policy can be useful. Companies should manage receivables and be careful."
    strong_eval = StudyPlanGUI._evaluate_section_c_response_deterministic(dummy, question, strong_response)
    weak_eval = StudyPlanGUI._evaluate_section_c_response_deterministic(dummy, question, weak_response)
    strong_total = int(strong_eval.get("total_mark", 0) or 0)
    weak_total = int(weak_eval.get("total_mark", 0) or 0)
    assert strong_total > weak_total
    assert (strong_total - weak_total) >= 4
    strong_rows = list(strong_eval.get("criterion_scores", []) or [])
    assert any(int(row.get("score", 0) or 0) >= 2 for row in strong_rows)


def test_evaluate_section_c_response_falls_back_when_llm_disabled():
    dummy = types.SimpleNamespace(local_llm_enabled=False)
    dummy._evaluate_section_c_response_deterministic = types.MethodType(
        StudyPlanGUI._evaluate_section_c_response_deterministic,
        dummy,
    )
    evaluation, warn = StudyPlanGUI._evaluate_section_c_response(
        dummy,
        {
            "required_tasks": ["Compute", "Recommend"],
            "marking_rubric": [
                {"criterion": "Technical accuracy", "max_marks": 8},
                {"criterion": "Recommendation", "max_marks": 6},
            ],
        },
        "Compute NPV with assumptions and provide recommendation.",
    )
    assert isinstance(evaluation, dict)
    assert evaluation.get("method") == "deterministic"
    assert "Local AI disabled" in str(warn or "")


def test_section_c_rewrite_planner_picks_weakest_by_ratio_then_mark_weight():
    dummy = types.SimpleNamespace()
    question = {
        "prompt": "Advise on receivables policy using case facts.",
        "exhibits": ["Sales 2.4m; funding cost 11%; bad debts may increase."],
        "required_tasks": [
            "Apply technical model to the case facts.",
            "Show workings and assumptions.",
            "Give a justified recommendation.",
        ],
    }
    # Two weak rows share ratio 0.5; planner should choose the one with higher max marks.
    evaluation = {
        "criterion_scores": [
            {"criterion": "Technical application to case facts", "score": 4, "max_mark": 8, "feedback": "Partial."},
            {"criterion": "Method, workings, and assumptions", "score": 3, "max_mark": 6, "feedback": "Partial."},
            {"criterion": "Evaluation and recommendation", "score": 3, "max_mark": 4, "feedback": "Okay."},
        ]
    }
    plan = StudyPlanGUI._plan_section_c_weakest_criterion_rewrite(dummy, question, evaluation)
    assert isinstance(plan, dict)
    assert plan["criterion"] == "Technical application to case facts"
    assert plan["criterion_kind"] == "technical"
    assert "Rewrite only the weakest section" in str(plan.get("instruction", ""))


def test_section_c_evaluation_delta_computes_total_and_row_deltas():
    dummy = types.SimpleNamespace()
    before_eval = {
        "total_mark": 9,
        "max_mark": 20,
        "criterion_scores": [
            {"criterion": "Technical application to case facts", "score": 4, "max_mark": 8},
            {"criterion": "Method, workings, and assumptions", "score": 3, "max_mark": 6},
            {"criterion": "Evaluation and recommendation", "score": 2, "max_mark": 4},
            {"criterion": "Structure and exam communication", "score": 0, "max_mark": 2},
        ],
    }
    after_eval = {
        "total_mark": 13,
        "max_mark": 20,
        "criterion_scores": [
            {"criterion": "Technical application to case facts", "score": 6, "max_mark": 8},
            {"criterion": "Method, workings, and assumptions", "score": 4, "max_mark": 6},
            {"criterion": "Evaluation and recommendation", "score": 2, "max_mark": 4},
            {"criterion": "Structure and exam communication", "score": 1, "max_mark": 2},
        ],
    }
    delta = StudyPlanGUI._compute_section_c_evaluation_delta(dummy, before_eval, after_eval)
    assert isinstance(delta, dict)
    assert delta["before_total"] == 9
    assert delta["after_total"] == 13
    assert delta["total_delta"] == 4
    rows = list(delta.get("criterion_deltas", []) or [])
    assert any(row.get("criterion") == "Technical application to case facts" and row.get("delta") == 2 for row in rows)
    text = StudyPlanGUI._format_section_c_delta_text(dummy, delta)
    assert "Rewrite delta: +4" in text


def test_build_section_c_intelligence_snapshot_uses_existing_intelligence_signals():
    dummy = types.SimpleNamespace()
    dummy._build_local_ai_context_packet = lambda kind="tutor", horizon_days=14: {"must_review_due": 5}
    dummy._get_tutor_learning_loop_observability_summary = lambda: {
        "checks": 12,
        "fragility_score": 64.0,
        "effective_accuracy_pct": 58.0,
        "calibration_bias": 1.0,
        "misconceptions_top": ("method_gap",),
    }
    dummy._build_tutor_loop_cognitive_runtime_meta = lambda chapter="": {
        "posterior_mean": 0.38,
        "posterior_variance": 0.04,
        "struggle_mode": True,
        "quiz_active": False,
        "fsm_state": "PRODUCTIVE_STRUGGLE",
    }
    dummy._read_recent_section_c_attempts_summary = lambda chapter, **_: {
        "attempts": 4,
        "avg_score_pct": 47.0,
        "last_score_pct": 51.0,
        "weakest_criterion_top": "Method, workings, and assumptions",
        "weakest_criterion_recurrence": 3,
    }
    dummy._build_section_c_intelligence_snapshot = types.MethodType(StudyPlanGUI._build_section_c_intelligence_snapshot, dummy)

    intel = StudyPlanGUI._build_section_c_intelligence_snapshot(dummy, "Topic A", snapshot={"must_review_due": 2})
    assert intel["target_difficulty"] == "supportive"
    assert intel["struggle_mode"] is True
    assert intel["rubric_emphasis"] == "Method, workings, and assumptions"
    assert intel["recent_section_c_weakest_recurrence"] == 3
    assert any("confidence calibration" in str(item).lower() for item in list(intel.get("coaching_cues", []) or []))


def test_build_section_c_generation_prompt_includes_intelligence_payload():
    dummy = types.SimpleNamespace(module_title="FM", current_topic="Topic A")
    dummy._build_section_c_intelligence_snapshot = lambda chapter, snapshot=None: {
        "target_difficulty": "stretch",
        "rubric_emphasis": "Evaluation and recommendation",
        "coaching_cues": ["confidence calibration check"],
        "fragility_score": 22.0,
        "recent_section_c_avg_pct": 71.0,
        "recent_section_c_weakest_criterion": "Evaluation and recommendation",
    }
    prompt = StudyPlanGUI._build_section_c_generation_prompt(
        dummy,
        "Topic A",
        snapshot={"weak_topics_top3": [{"chapter": "Topic A"}], "must_review_due": 2},
    )
    assert "section_c_intelligence" in prompt
    assert "\"target_difficulty\":\"stretch\"" in prompt
    assert "\"rubric_emphasis\":\"Evaluation and recommendation\"" in prompt
    assert "Use payload.section_c_intelligence.target_difficulty" in prompt


def test_section_c_rewrite_planner_adapts_instruction_from_intelligence():
    dummy = types.SimpleNamespace()
    question = {
        "prompt": "Advise on receivables policy using case facts.",
        "exhibits": ["Sales 2.4m; funding cost 11%; bad debts may increase."],
        "required_tasks": [
            "Apply technical model to the case facts.",
            "Show workings and assumptions.",
            "Give a justified recommendation.",
        ],
    }
    evaluation = {
        "criterion_scores": [
            {"criterion": "Technical application to case facts", "score": 4, "max_mark": 8, "feedback": "Partial."},
            {"criterion": "Method, workings, and assumptions", "score": 3, "max_mark": 6, "feedback": "Partial."},
            {"criterion": "Evaluation and recommendation", "score": 3, "max_mark": 4, "feedback": "Okay."},
        ]
    }
    plan = StudyPlanGUI._plan_section_c_weakest_criterion_rewrite(
        dummy,
        question,
        evaluation,
        intelligence={
            "target_difficulty": "supportive",
            "struggle_mode": True,
            "rubric_emphasis": "Technical application to case facts",
            "recent_section_c_weakest_recurrence": 3,
            "calibration_bias": 1.2,
            "must_review_due": 4,
        },
    )
    assert isinstance(plan, dict)
    instruction = str(plan.get("instruction", ""))
    assert "Target length: 4-6 lines." in instruction
    assert "recurring weak criterion" in instruction.lower()
    assert "assumption check or sensitivity" in instruction.lower() or "assumption check" in instruction.lower()


def test_generate_section_c_question_uses_recovery_status_on_ollama_error():
    engine = types.SimpleNamespace(CHAPTERS=["Topic A"])
    dummy = types.SimpleNamespace(
        engine=engine,
        local_llm_enabled=True,
        _build_local_llm_model_failover_sequence=lambda **_kw: (["model-a"], None),
        _select_local_llm_model=lambda **_kw: ("model-a", None),
        _build_section_c_generation_prompt=lambda chapter, snapshot=None: "prompt",
        _ollama_generate_text=lambda model, prompt: ("", "timeout"),
        _default_section_c_question=lambda chapter: {"chapter": chapter, "prompt": "fallback"},
        _upsert_section_c_question=lambda chapter, row, persist=True: row,
        _compose_ollama_recovery_status=lambda err, **_kw: "RECOVERY STATUS",
    )

    row, warn = StudyPlanGUI._generate_section_c_question(dummy, "Topic A", snapshot={})

    assert isinstance(row, dict)
    assert row.get("prompt") == "fallback"
    assert warn == "RECOVERY STATUS"


def test_generate_section_c_question_uses_guardrail_status_on_parse_failure():
    engine = types.SimpleNamespace(CHAPTERS=["Topic A"])
    dummy = types.SimpleNamespace(
        engine=engine,
        local_llm_enabled=True,
        _build_local_llm_model_failover_sequence=lambda **_kw: (["model-a"], None),
        _select_local_llm_model=lambda **_kw: ("model-a", None),
        _build_section_c_generation_prompt=lambda chapter, snapshot=None: "prompt",
        _ollama_generate_text=lambda model, prompt: ("{}", None),
        _parse_generated_section_c_question=lambda text, chapter: (None, "JSON parse error"),
        _default_section_c_question=lambda chapter: {"chapter": chapter, "prompt": "fallback"},
        _upsert_section_c_question=lambda chapter, row, persist=True: row,
        _compose_ollama_guardrail_status=lambda detail, **_kw: "GUARDRAIL STATUS",
    )

    row, warn = StudyPlanGUI._generate_section_c_question(dummy, "Topic A", snapshot={})

    assert isinstance(row, dict)
    assert row.get("prompt") == "fallback"
    assert warn == "GUARDRAIL STATUS"


def test_generate_section_c_question_failover_uses_second_model():
    """When first model returns LLM error, second model is tried and success uses its response."""
    engine = types.SimpleNamespace(CHAPTERS=["Topic A"])
    valid_row = {"chapter": "Topic A", "scenario": "Generated case", "prompt": "Generated case"}
    calls = []

    def _ollama(model, prompt):
        calls.append(model)
        if model == "sec-1":
            return ("", "timeout")
        return ("{}", None)

    def _parse(text, chapter):
        if not (text or "").strip():
            return (None, "No JSON")
        return (dict(valid_row), None)

    dummy = types.SimpleNamespace(
        engine=engine,
        local_llm_enabled=True,
        _build_local_llm_model_failover_sequence=lambda **_kw: (["sec-1", "sec-2"], None),
        _select_local_llm_model=lambda **_kw: ("sec-1", None),
        _build_section_c_generation_prompt=lambda chapter, snapshot=None: "prompt",
        _ollama_generate_text=_ollama,
        _parse_generated_section_c_question=_parse,
        _upsert_section_c_question=lambda chapter, row, persist=True: row,
    )

    row, warn = StudyPlanGUI._generate_section_c_question(dummy, "Topic A", snapshot={})

    assert isinstance(row, dict)
    assert row.get("scenario") == "Generated case"
    assert warn is None
    assert "sec-1" in calls and "sec-2" in calls


def test_format_ai_tutor_transcript_labels_roles():
    dummy = _make_dummy()
    transcript = StudyPlanGUI._format_ai_tutor_transcript(
        dummy,
        [
            {"role": "user", "content": "Question"},
            {"role": "assistant", "content": "Answer"},
        ],
    )
    assert transcript.startswith("You:\nQuestion")
    assert "Tutor:\nAnswer" in transcript


def test_clean_ai_tutor_text_removes_markdown_and_latex_noise():
    dummy = _make_dummy()
    raw = (
        "### Practice Questions\n\n"
        "**Q1:** Cost = \\\\frac{2}{98} \\\\times \\\\frac{365}{20} = 37.2\\\\%.\n"
        "```json\n{\"ignore\": true}\n```\n"
    )
    cleaned = StudyPlanGUI._clean_ai_tutor_text(dummy, raw)
    assert "Practice Questions" in cleaned
    assert "Q1: Cost = (2/98) x (365/20) = 37.2%." in cleaned
    assert "```" not in cleaned
    assert "\\frac" not in cleaned
    assert "\\times" not in cleaned
    assert "\\%" not in cleaned


def test_clean_ai_tutor_text_handles_escaped_braces_in_latex():
    dummy = _make_dummy()
    raw = "Rate = \\\\frac\\{2\\}\\{98\\} \\\\times 100\\\\%"
    cleaned = StudyPlanGUI._clean_ai_tutor_text(dummy, raw)
    assert "Rate = (2/98) x 100%" in cleaned
    assert "\\frac" not in cleaned


def test_format_ai_tutor_transcript_cleans_assistant_content():
    dummy = _make_dummy()
    transcript = StudyPlanGUI._format_ai_tutor_transcript(
        dummy,
        [
            {"role": "assistant", "content": "**A:** \\\\frac{1}{2} \\\\times 100\\\\%"},
        ],
    )
    assert "Tutor:\nA: (1/2) x 100%" in transcript


def test_clean_ai_tutor_text_strips_disclaimers():
    """AI output is cleaned so disclaimers are removed and text reads as direct advice."""
    from studyplan_ai_tutor import clean_ai_tutor_text

    raw = "As an AI assistant I cannot give financial advice.\n\nUse WACC = (E/V)*Re + (D/V)*Rd."
    cleaned = clean_ai_tutor_text(raw)
    assert "As an AI" not in cleaned
    assert "I cannot" not in cleaned
    assert "Use WACC" in cleaned


def test_clean_ai_tutor_text_human_readable_math():
    """Formulas and math are converted to human-readable form (fractions, powers, sqrt)."""
    from studyplan_ai_tutor import clean_ai_tutor_text

    raw = "NPV = \\\\frac{CF_1}{(1+r)} + \\\\sqrt{x}; variance \\\\leq 0.05; x^2 and \\\\beta."
    cleaned = clean_ai_tutor_text(raw)
    assert "\\frac" not in cleaned
    assert "\\sqrt" not in cleaned
    assert "\\leq" not in cleaned
    assert "\\beta" not in cleaned
    assert "/" in cleaned or "(" in cleaned
    assert "sqrt(" in cleaned or "sqrt " in cleaned
    assert "²" in cleaned or "^2" in cleaned
    assert "beta" in cleaned


def test_ollama_generate_text_stream_parses_ndjson_and_emits_chunks(monkeypatch):
    dummy = _make_dummy()

    lines = [
        json.dumps({"response": "Hello ", "done": False}).encode("utf-8") + b"\n",
        json.dumps({"response": "world", "done": True}).encode("utf-8") + b"\n",
    ]

    class _FakeResponse:
        def __init__(self, payload_lines):
            self._lines = list(payload_lines)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def readline(self):
            if not self._lines:
                return b""
            return self._lines.pop(0)

    def _fake_urlopen(_req, timeout=None):
        assert timeout is not None
        return _FakeResponse(lines)

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    seen = []
    text, err = StudyPlanGUI._ollama_generate_text_stream(
        dummy,
        model="demo:latest",
        prompt="Say hello",
        on_chunk=lambda piece: seen.append(piece),
    )
    assert err is None
    assert text == "Hello world"
    assert seen == ["Hello ", "world"]


def test_ollama_generate_text_stream_honors_cancellation(monkeypatch):
    dummy = _make_dummy()

    lines = [
        json.dumps({"response": "Part 1", "done": False}).encode("utf-8") + b"\n",
        json.dumps({"response": "Part 2", "done": True}).encode("utf-8") + b"\n",
    ]

    class _FakeResponse:
        def __init__(self, payload_lines):
            self._lines = list(payload_lines)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def readline(self):
            if not self._lines:
                return b""
            return self._lines.pop(0)

    monkeypatch.setattr(urllib.request, "urlopen", lambda _req, timeout=None: _FakeResponse(lines))

    stopped = {"flag": False}

    def _on_chunk(_piece: str):
        stopped["flag"] = True

    text, err = StudyPlanGUI._ollama_generate_text_stream(
        dummy,
        model="demo:latest",
        prompt="stream",
        on_chunk=_on_chunk,
        cancel_check=lambda: bool(stopped["flag"]),
    )
    assert err == "cancelled"
    assert text == "Part 1"


def test_ollama_generate_text_retries_transient_error(monkeypatch):
    dummy = _make_dummy()
    calls = {"count": 0}

    def _fake_request(_path, payload=None, timeout_seconds=None):
        calls["count"] += 1
        if calls["count"] == 1:
            return None, "HTTP 503: service unavailable"
        return {"response": "ok"}, None

    monkeypatch.setattr(dummy, "_ollama_request_json", _fake_request, raising=False)
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)
    text, err = StudyPlanGUI._ollama_generate_text(dummy, model="demo:latest", prompt="ping")
    assert err is None
    assert text == "ok"
    assert calls["count"] == 2


def test_ollama_generate_text_returns_busy_when_runtime_slot_unavailable():
    dummy = _make_dummy()
    calls: list[tuple[str, bool, str]] = []
    dummy._is_local_llm_model_on_cooldown = lambda _model: (False, 0, "")
    dummy._acquire_ollama_request_slot = lambda wait_seconds=None: (False, 180)
    dummy._record_local_llm_model_outcome = (
        lambda model_name, success=False, err="": calls.append((str(model_name), bool(success), str(err)))
    )
    text, err = StudyPlanGUI._ollama_generate_text_with_options(
        dummy,
        model="demo:latest",
        prompt="ping",
        num_ctx=2048,
        temperature=0.2,
        use_response_cache=False,
    )
    assert text == ""
    assert isinstance(err, str) and "runtime busy" in err.lower()
    assert calls and calls[-1][0] == "demo:latest" and calls[-1][1] is False


def test_ollama_generate_text_stream_retries_transient_error_before_chunks(monkeypatch):
    dummy = _make_dummy()
    calls = {"count": 0}

    lines = [
        json.dumps({"response": "retry ", "done": False}).encode("utf-8") + b"\n",
        json.dumps({"response": "success", "done": True}).encode("utf-8") + b"\n",
    ]

    class _FakeResponse:
        def __init__(self, payload_lines):
            self._lines = list(payload_lines)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def readline(self):
            if not self._lines:
                return b""
            return self._lines.pop(0)

    def _fake_urlopen(_req, timeout=None):
        calls["count"] += 1
        if calls["count"] == 1:
            raise urllib.error.URLError("connection reset by peer")
        return _FakeResponse(lines)

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)

    seen = []
    text, err = StudyPlanGUI._ollama_generate_text_stream(
        dummy,
        model="demo:latest",
        prompt="stream",
        on_chunk=lambda piece: seen.append(piece),
    )
    assert err is None
    assert text == "retry success"
    assert seen == ["retry ", "success"]
    assert calls["count"] == 2


def test_ollama_generate_text_stream_recovers_with_compact_non_stream_fallback(monkeypatch):
    dummy = _make_dummy()
    outcomes: list[tuple[str, bool, str]] = []
    released = {"count": 0}
    dummy._is_local_llm_model_on_cooldown = lambda _model: (False, 0, "")
    dummy._acquire_ollama_request_slot = lambda wait_seconds=None: (True, 0)
    dummy._release_ollama_request_slot = lambda: released.__setitem__("count", int(released["count"]) + 1)
    dummy._record_local_llm_model_outcome = (
        lambda model_name, success=False, err="": outcomes.append((str(model_name), bool(success), str(err)))
    )
    dummy._get_ollama_retry_limit = lambda: 0
    dummy._should_compact_recovery_retry = lambda _err: True
    dummy._reduce_prompt_for_recovery = lambda prompt: f"compact::{str(prompt)[:18]}"
    dummy._coerce_ollama_reduced_num_ctx = lambda _value=None: 1024
    dummy._ollama_generate_text_with_options = (
        lambda model, prompt, *, num_ctx, temperature=0.2, use_response_cache=False, **kwargs: ("Recovered text", None)
    )

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(urllib.error.URLError("connection reset by peer")),
    )
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)
    seen: list[str] = []
    text, err = StudyPlanGUI._ollama_generate_text_stream(
        dummy,
        model="demo:latest",
        prompt="Long prompt requiring fallback",
        on_chunk=lambda piece: seen.append(piece),
    )
    assert err is None
    assert text == "Recovered text"
    assert seen == ["Recovered text"]
    assert released["count"] == 1
    assert outcomes and outcomes[-1][0] == "demo:latest" and outcomes[-1][1] is True


def test_extract_first_json_object_handles_markdown_wrappers():
    dummy = _make_dummy()
    wrapped = "```json\n{\"action\":\"quiz\",\"topic\":\"Topic A\"}\n```"
    got = StudyPlanGUI._extract_first_json_object(dummy, wrapped)
    assert got == "{\"action\":\"quiz\",\"topic\":\"Topic A\"}"


def test_normalize_ai_coach_recommendation_uses_action_topic_fallback_and_clamps_duration():
    dummy = _make_ai_coach_dummy()
    payload = {
        "action_topics": {
            "focus": "Topic A",
            "quiz": "Topic B",
            "drill": "Topic A",
            "interleave": "Topic B",
            "review": "Topic A",
        }
    }
    raw = {
        "action": "quiz",
        "duration_minutes": 200,
        "reason": "Quiz now",
        "confidence": 1.5,
    }
    rec, err = StudyPlanGUI._normalize_ai_coach_recommendation(dummy, raw, payload)
    assert err is None
    assert rec is not None
    assert rec["action"] == "quiz"
    assert rec["topic"] == "Topic B"
    assert rec["duration_minutes"] == 60
    assert rec["confidence"] == 1.0


def test_normalize_ai_coach_recommendation_rejects_review_without_due_cards():
    dummy = _make_ai_coach_dummy()
    payload = {"action_topics": {"review": "Topic B"}}
    raw = {
        "action": "review",
        "topic": "Topic B",
        "duration_minutes": 10,
        "reason": "Clear reviews",
    }
    rec, err = StudyPlanGUI._normalize_ai_coach_recommendation(dummy, raw, payload)
    assert rec is None
    assert err is not None
    assert "no due review" in err.lower()


def test_build_ai_coach_fallback_prefers_review_when_due_exists():
    dummy = _make_ai_coach_dummy()
    payload = {
        "recommended_topic": "Topic B",
        "weak_chapter": "Topic A",
        "must_review_due": 4,
        "has_questions": True,
        "retrieval": {"force_retrieval": False},
        "action_topics": {
            "focus": "Topic B",
            "quiz": "Topic B",
            "drill": "Topic A",
            "interleave": "Topic B",
            "review": "Topic A",
        },
    }
    rec = StudyPlanGUI._build_ai_coach_fallback_recommendation(dummy, payload, issue="")
    assert rec["action"] == "review"
    assert rec["topic"] == "Topic A"


def test_build_ai_coach_prompt_includes_learning_context_when_available():
    dummy = _make_local_context_dummy()
    payload = {
        "recommended_topic": "Topic A",
        "action_topics": {"focus": "Topic A"},
        "days_to_exam": 24,
        "must_review_due": 6,
    }
    prompt = StudyPlanGUI._build_ai_coach_prompt(dummy, payload)
    assert "Runtime contract (coach):" in prompt
    assert "first-class local model inside StudyPlan" in prompt
    assert "Learning context (aggregated app state):" in prompt
    assert "Payload JSON:" in prompt


def test_build_ai_coach_prompt_omits_learning_context_when_packet_fails():
    dummy = _make_local_context_dummy()
    dummy._build_local_ai_context_packet = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
    payload = {
        "recommended_topic": "Topic A",
        "action_topics": {"focus": "Topic A"},
        "days_to_exam": 80,
        "must_review_due": 0,
    }
    prompt = StudyPlanGUI._build_ai_coach_prompt(dummy, payload)
    assert "Runtime contract (coach):" in prompt
    assert "Learning context (aggregated app state):" not in prompt
    assert "Payload JSON:" in prompt


def test_build_local_ai_runtime_contract_adapts_phase_and_pressure():
    dummy = _make_dummy()
    text = StudyPlanGUI._build_local_ai_runtime_contract(
        dummy,
        "coach",
        days_to_exam=12,
        must_review_due=9,
    )
    assert "Runtime contract (coach):" in text
    assert "Exam phase: final_push" in text
    assert "pressure state: due_pressure_high" in text


def test_get_topic_must_review_due_count_ignores_out_of_range_indices():
    today = datetime.date(2026, 2, 14)
    today_iso = today.isoformat()
    engine = types.SimpleNamespace(
        CHAPTERS=["Topic A"],
        must_review={"Topic A": {"999": today_iso, "0": today_iso}},
        get_questions=lambda _topic: ["Q0", "Q1"],
        _parse_date=lambda value: datetime.date.fromisoformat(value) if isinstance(value, str) else None,
    )
    dummy = types.SimpleNamespace(engine=engine)
    count = StudyPlanGUI._get_topic_must_review_due_count(dummy, "Topic A", today=today)
    assert count == 1


def test_find_due_review_topic_prefers_chapter_with_must_review_pressure():
    today = datetime.date(2026, 2, 14)
    engine = types.SimpleNamespace(
        CHAPTERS=["Topic A", "Topic B"],
        must_review={"Topic A": {}, "Topic B": {"0": today.isoformat()}},
        srs_data={"Topic A": [], "Topic B": []},
        get_questions=lambda topic: ["Q0", "Q1"] if topic in {"Topic A", "Topic B"} else [],
        _parse_date=lambda value: datetime.date.fromisoformat(value) if isinstance(value, str) else None,
        is_overdue=lambda _item, _today: False,
    )
    dummy = types.SimpleNamespace(
        engine=engine,
        current_topic="Topic A",
        _has_chapters=lambda: True,
        _get_recommended_topic=lambda: "Topic A",
        _get_coach_candidate_score=lambda _topic: 0.0,
        _topic_has_questions=lambda topic: topic in {"Topic A", "Topic B"},
    )
    dummy._get_topic_must_review_due_count = types.MethodType(StudyPlanGUI._get_topic_must_review_due_count, dummy)
    dummy._get_topic_due_review_count = types.MethodType(StudyPlanGUI._get_topic_due_review_count, dummy)
    topic, due_total, must_due = StudyPlanGUI._find_due_review_topic(dummy, preferred_topic="Topic A")
    assert topic == "Topic B"
    assert due_total == 1
    assert must_due == 1


def test_sanitize_must_review_desync_backfills_from_overdue_after_dropping_stale_indices():
    today = datetime.date(2026, 2, 14)
    today_iso = today.isoformat()
    saved = {"count": 0}

    def _parse_date(value):
        try:
            return datetime.date.fromisoformat(str(value))
        except Exception:
            return None

    def _is_overdue(item, ref_day):
        if not isinstance(item, dict):
            return False
        raw_last = item.get("last_review")
        if not isinstance(raw_last, str) or not raw_last:
            return False
        try:
            last = datetime.date.fromisoformat(raw_last)
            interval = max(1, int(item.get("interval", 1) or 1))
        except Exception:
            return False
        return (last + datetime.timedelta(days=interval)) <= ref_day

    engine = types.SimpleNamespace(
        CHAPTERS=["Topic A"],
        must_review={"Topic A": {"8": today_iso}},
        srs_data={"Topic A": [{"last_review": "2026-01-01", "interval": 1, "efactor": 2.5}]},
        get_questions=lambda _topic: ["Q0"],
        _parse_date=_parse_date,
        is_overdue=_is_overdue,
        save_data=lambda: saved.__setitem__("count", saved["count"] + 1),
    )
    dummy = types.SimpleNamespace(engine=engine)
    dummy._get_topic_must_review_due_count = types.MethodType(StudyPlanGUI._get_topic_must_review_due_count, dummy)
    stats = StudyPlanGUI._sanitize_must_review_desync(dummy, backfill_from_srs=True, today=today)
    assert stats["changed"] is True
    assert stats["dropped_out_of_range"] == 1
    assert stats["backfilled"] == 1
    assert stats["due_after"] == 1
    assert engine.must_review["Topic A"].get("0") == today_iso
    assert saved["count"] == 1


def test_on_clear_must_review_sanitizes_then_starts_recovered_topic():
    picked_topics: list[str] = []
    started: list[tuple[str, int, str]] = []
    notices: list[str] = []
    state = {"calls": 0}

    def _find_due(_preferred):
        state["calls"] += 1
        if state["calls"] == 1:
            return "", 0, 0
        return "Topic B", 3, 2

    dummy = types.SimpleNamespace(
        current_topic="Topic A",
        _ensure_coach_selection=lambda: None,
        _ensure_chapters_ready=lambda _label: True,
        _get_drill_topic=lambda: "Topic A",
        _get_recommended_topic=lambda: "Topic A",
        _find_due_review_topic=_find_due,
        _sanitize_must_review_desync=lambda backfill_from_srs=True: {
            "changed": True,
            "dropped_total": 2,
            "backfilled": 1,
        },
        _set_current_topic=lambda topic: picked_topics.append(topic),
        start_quiz_session=lambda topic=None, total_override=None, kind="quiz": started.append(
            (str(topic or ""), int(total_override or 0), str(kind or ""))
        ),
        send_notification=lambda _title, msg: notices.append(str(msg)),
    )
    StudyPlanGUI.on_clear_must_review(dummy, None)
    assert picked_topics[-1] == "Topic B"
    assert started[-1] == ("Topic B", 6, "review")
    assert any("Recovered due review on Topic B" in msg for msg in notices)


def test_validate_selected_file_size_rejects_directory(tmp_path):
    dummy = types.SimpleNamespace()
    with pytest.raises(ValueError):
        StudyPlanGUI._validate_selected_file_size(dummy, str(tmp_path), 1024, "Import")


def test_stop_quiz_or_review_timer_if_active_stops_supported_kinds():
    calls: list[bool] = []
    dummy = types.SimpleNamespace(
        _action_timer_kind="review",
        _stop_action_timer=lambda finalize=True: calls.append(bool(finalize)),
    )
    dummy._is_quiz_or_review_timer_kind = types.MethodType(StudyPlanGUI._is_quiz_or_review_timer_kind, dummy)
    dummy._stop_quiz_or_review_timer_if_active = types.MethodType(
        StudyPlanGUI._stop_quiz_or_review_timer_if_active,
        dummy,
    )
    stopped = StudyPlanGUI._stop_quiz_or_review_timer_if_active(dummy, finalize=True)
    assert stopped is True
    assert calls == [True]


def test_stop_quiz_or_review_timer_if_active_ignores_non_quiz_kinds():
    calls: list[bool] = []
    dummy = types.SimpleNamespace(
        _action_timer_kind="pomodoro_focus",
        _stop_action_timer=lambda finalize=True: calls.append(bool(finalize)),
    )
    dummy._is_quiz_or_review_timer_kind = types.MethodType(StudyPlanGUI._is_quiz_or_review_timer_kind, dummy)
    dummy._stop_quiz_or_review_timer_if_active = types.MethodType(
        StudyPlanGUI._stop_quiz_or_review_timer_if_active,
        dummy,
    )
    stopped = StudyPlanGUI._stop_quiz_or_review_timer_if_active(dummy, finalize=True)
    assert stopped is False
    assert calls == []


def test_cleanup_quiz_dialog_runtime_stops_timer_and_clears_dialog():
    calls: list[bool] = []
    dummy = types.SimpleNamespace(
        _quiz_reason_job_token=7,
        quiz_dialog=object(),
        _stop_quiz_or_review_timer_if_active=lambda finalize=True: calls.append(bool(finalize)),
    )
    StudyPlanGUI._cleanup_quiz_dialog_runtime(dummy, finalize_timer=True)
    assert dummy.quiz_dialog is None
    assert dummy._quiz_reason_job_token == 8
    assert calls == [True]


def test_cleanup_quiz_dialog_runtime_tolerates_missing_token_and_finalize_false():
    calls: list[bool] = []
    dummy = types.SimpleNamespace(
        quiz_dialog=object(),
        _stop_quiz_or_review_timer_if_active=lambda finalize=True: calls.append(bool(finalize)),
    )
    StudyPlanGUI._cleanup_quiz_dialog_runtime(dummy, finalize_timer=False)
    assert dummy.quiz_dialog is None
    assert calls == [False]


def test_append_ai_tutor_rag_pdf_path_adds_and_clears_runtime_cache(tmp_path):
    first_pdf = tmp_path / "first.pdf"
    second_pdf = tmp_path / "second.pdf"
    first_pdf.write_bytes(b"%PDF-1.4\nfirst")
    second_pdf.write_bytes(b"%PDF-1.4\nsecond")

    from studyplan.components.performance.caching import PerformanceCacheService
    perf_cache = PerformanceCacheService({"cache_max_size": 100, "default_ttl_seconds": 300, "cache_ttl": {}})
    perf_cache.set("rag_doc:stale", {"chunks": []})

    calls = {"saved": 0, "tutor_refresh": 0, "settings_refresh": 0}
    dummy = types.SimpleNamespace(
        ai_tutor_rag_pdfs=str(first_pdf),
        _perf_cache=perf_cache,
        save_preferences=lambda: calls.__setitem__("saved", calls["saved"] + 1),
        _refresh_tutor_workspace_page=lambda: calls.__setitem__("tutor_refresh", calls["tutor_refresh"] + 1),
        _refresh_settings_workspace_page=lambda: calls.__setitem__("settings_refresh", calls["settings_refresh"] + 1),
    )
    dummy._normalize_user_file_path = types.MethodType(StudyPlanGUI._normalize_user_file_path, dummy)
    dummy._validate_import_source_path = types.MethodType(StudyPlanGUI._validate_import_source_path, dummy)
    dummy._validate_selected_file_size = types.MethodType(StudyPlanGUI._validate_selected_file_size, dummy)
    dummy._get_ai_tutor_rag_max_pdf_bytes = types.MethodType(StudyPlanGUI._get_ai_tutor_rag_max_pdf_bytes, dummy)

    added, message = StudyPlanGUI._append_ai_tutor_rag_pdf_path(dummy, str(second_pdf))

    assert added is True
    assert "Added Tutor RAG PDF" in message
    paths = [row.strip() for row in str(dummy.ai_tutor_rag_pdfs or "").splitlines() if row.strip()]
    assert paths == [str(first_pdf), str(second_pdf)]
    assert perf_cache.get("rag_doc:stale") is None
    assert calls == {"saved": 1, "tutor_refresh": 1, "settings_refresh": 1}


def test_append_ai_tutor_rag_pdf_path_rejects_duplicate(tmp_path):
    first_pdf = tmp_path / "first.pdf"
    first_pdf.write_bytes(b"%PDF-1.4\nfirst")

    from studyplan.components.performance.caching import PerformanceCacheService
    calls = {"saved": 0}
    dummy = types.SimpleNamespace(
        ai_tutor_rag_pdfs=str(first_pdf),
        _perf_cache=PerformanceCacheService({"cache_max_size": 100, "default_ttl_seconds": 300, "cache_ttl": {}}),
        save_preferences=lambda: calls.__setitem__("saved", calls["saved"] + 1),
        _refresh_tutor_workspace_page=lambda: None,
        _refresh_settings_workspace_page=lambda: None,
    )
    dummy._normalize_user_file_path = types.MethodType(StudyPlanGUI._normalize_user_file_path, dummy)
    dummy._validate_import_source_path = types.MethodType(StudyPlanGUI._validate_import_source_path, dummy)
    dummy._validate_selected_file_size = types.MethodType(StudyPlanGUI._validate_selected_file_size, dummy)
    dummy._get_ai_tutor_rag_max_pdf_bytes = types.MethodType(StudyPlanGUI._get_ai_tutor_rag_max_pdf_bytes, dummy)

    added, message = StudyPlanGUI._append_ai_tutor_rag_pdf_path(dummy, str(first_pdf))

    assert added is False
    assert "already in Tutor RAG sources" in message
    assert calls["saved"] == 0


def test_stop_tutor_workspace_runtime_cancels_stream_and_poll_sources():
    removed: list[int] = []
    set_running_calls: list[bool] = []
    stopped_models: list[str] = []
    cancel_event = threading.Event()
    state = {
        "active": True,
        "job_id": 4,
        "cancel_event": cancel_event,
        "model": "llama3:8b",
        "stream_watchdog_id": 17,
        "model_poll_id": 23,
        "set_running": lambda running: set_running_calls.append(bool(running)),
    }
    dummy = types.SimpleNamespace(
        _tutor_workspace_state=state,
        _force_remove_glib_source=lambda source_id: removed.append(int(source_id)),
        _ollama_stop_model=lambda model_name: stopped_models.append(str(model_name)),
    )

    StudyPlanGUI._stop_tutor_workspace_runtime(dummy)

    assert cancel_event.is_set() is True
    assert removed == [17, 23]
    assert set_running_calls == [False]
    assert stopped_models == ["llama3:8b"]
    assert state["active"] is False
    assert state["stream_watchdog_id"] == 0
    assert state["model_poll_id"] == 0
    assert state["cancel_event"] is None


def test_shutdown_core_runtime_is_idempotent_and_calls_blocking_engine_shutdown():
    calls: dict[str, int] = {
        "pomodoro_state": 0,
        "scheduler_cancel": 0,
        "lifecycle_close": 0,
        "stop_workspace": 0,
        "stop_break": 0,
        "drain_glib": 0,
        "engine_shutdown": 0,
    }
    removed: list[int] = []
    action_finalize: list[bool] = []
    dummy = types.SimpleNamespace(
        _core_runtime_shutdown=False,
        _set_pomodoro_active_state=lambda active: calls.__setitem__("pomodoro_state", calls["pomodoro_state"] + (0 if active else 1)),
        _ui_refresh_scheduler=types.SimpleNamespace(cancel_all=lambda: calls.__setitem__("scheduler_cancel", calls["scheduler_cancel"] + 1)),
        _ui_dialog_lifecycle=types.SimpleNamespace(close_all=lambda: calls.__setitem__("lifecycle_close", calls["lifecycle_close"] + 1)),
        _ai_tutor_global_autopilot_id=31,
        _ai_tutor_global_autopilot_busy=True,
        _stop_tutor_workspace_runtime=lambda: calls.__setitem__("stop_workspace", calls["stop_workspace"] + 1),
        _focus_timer_id=41,
        pomodoro_timer_id=51,
        _stop_break_timer=lambda: calls.__setitem__("stop_break", calls["stop_break"] + 1),
        _stop_action_timer=lambda finalize=True: action_finalize.append(bool(finalize)),
        _drain_registered_glib_sources=lambda: calls.__setitem__("drain_glib", calls["drain_glib"] + 1),
        _force_remove_glib_source=lambda source_id: removed.append(int(source_id)),
        engine=types.SimpleNamespace(
            shutdown_runtime=lambda wait_for_workers=True: calls.__setitem__(
                "engine_shutdown",
                calls["engine_shutdown"] + (1 if bool(wait_for_workers) else 0),
            )
        ),
    )

    StudyPlanGUI._shutdown_core_runtime(dummy, finalize_timers=True)
    StudyPlanGUI._shutdown_core_runtime(dummy, finalize_timers=True)

    assert calls["pomodoro_state"] == 1
    assert calls["scheduler_cancel"] == 1
    assert calls["lifecycle_close"] == 1
    assert calls["stop_workspace"] == 1
    assert calls["stop_break"] == 1
    assert calls["drain_glib"] == 1
    assert calls["engine_shutdown"] == 1
    assert action_finalize == [True]
    assert removed == [31, 41, 51]
    assert dummy._ai_tutor_global_autopilot_id == 0
    assert dummy._ai_tutor_global_autopilot_busy is False
    assert dummy._focus_timer_id is None
    assert dummy.pomodoro_timer_id is None


def test_start_stop_core_housekeeping_timers_registers_and_cleans_sources(monkeypatch):
    import studyplan_app as appmod

    timer_calls: list[tuple[int, int]] = []
    registered: list[int] = []
    removed: list[int] = []
    next_id = {"value": 101}

    def _fake_timeout_add(delay_ms, _cb):
        source_id = int(next_id["value"])
        next_id["value"] = source_id + 1
        timer_calls.append((int(delay_ms), source_id))
        return source_id

    monkeypatch.setattr(appmod.GLib, "timeout_add", _fake_timeout_add)

    dummy = types.SimpleNamespace(
        _core_runtime_shutdown=False,
        _auto_train_timer_id=0,
        _semantic_warmup_timer_id=0,
        _window_poll_timer_id=0,
        _daily_question_generation_timer_id=0,
        _auto_train_ml_tick=lambda: True,
        _semantic_warmup_tick=lambda: False,
        _poll_window_size=lambda: True,
        _register_glib_source=lambda source_id: registered.append(int(source_id)),
        _force_remove_glib_source=lambda source_id: removed.append(int(source_id)),
    )

    StudyPlanGUI._start_core_housekeeping_timers(dummy)

    assert [row[0] for row in timer_calls] == [60000, 4000, 2000, 90000]
    assert registered == [101, 102, 103, 104]
    assert int(dummy._auto_train_timer_id) == 101
    assert int(dummy._semantic_warmup_timer_id) == 102
    assert int(dummy._window_poll_timer_id) == 103
    assert int(dummy._daily_question_generation_timer_id) == 104

    StudyPlanGUI._stop_core_housekeeping_timers(dummy)

    assert removed == [101, 102, 103, 104]
    assert int(dummy._auto_train_timer_id) == 0
    assert int(dummy._semantic_warmup_timer_id) == 0
    assert int(dummy._window_poll_timer_id) == 0
    assert int(getattr(dummy, "_daily_question_generation_timer_id", 0) or 0) == 0


def test_start_core_housekeeping_timers_skips_semantic_and_auto_train_in_smoke_mode(monkeypatch):
    import studyplan_app as appmod

    timer_calls: list[tuple[int, int]] = []
    registered: list[int] = []
    loky_diag_labels: list[str] = []
    next_id = {"value": 201}

    def _fake_timeout_add(delay_ms, _cb):
        source_id = int(next_id["value"])
        next_id["value"] = source_id + 1
        timer_calls.append((int(delay_ms), source_id))
        return source_id

    monkeypatch.setattr(appmod.GLib, "timeout_add", _fake_timeout_add)
    monkeypatch.setattr(appmod, "_log_loky_diagnostics", lambda label: loky_diag_labels.append(str(label)))

    dummy = types.SimpleNamespace(
        _core_runtime_shutdown=False,
        _dialog_smoke_mode=False,
        _smoke_mode_bootstrap=True,
        _auto_train_timer_id=0,
        _semantic_warmup_timer_id=0,
        _window_poll_timer_id=0,
        _daily_question_generation_timer_id=0,
        _auto_train_ml_tick=lambda: True,
        _semantic_warmup_tick=lambda: False,
        _poll_window_size=lambda: True,
        _register_glib_source=lambda source_id: registered.append(int(source_id)),
        _force_remove_glib_source=lambda _source_id: None,
    )

    StudyPlanGUI._start_core_housekeeping_timers(dummy)

    assert [row[0] for row in timer_calls] == [2000, 90000]
    assert registered == [201, 202]
    assert int(dummy._auto_train_timer_id) == 0
    assert int(dummy._semantic_warmup_timer_id) == 0
    assert int(dummy._window_poll_timer_id) == 201
    assert int(dummy._daily_question_generation_timer_id) == 202
    assert loky_diag_labels == ["semantic_warmup_skipped"]


def test_single_instance_lock_acquire_release_with_existing_lock(tmp_path):
    import fcntl
    import studyplan_app as appmod

    lock_path = str(tmp_path / "app_instance.lock")
    appmod._release_single_instance_lock()
    try:
        assert appmod._acquire_single_instance_lock(lock_path) is True
        assert appmod._acquire_single_instance_lock(lock_path) is True
        appmod._release_single_instance_lock()

        blocker_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(blocker_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert appmod._acquire_single_instance_lock(lock_path) is False
        finally:
            try:
                fcntl.flock(blocker_fd, fcntl.LOCK_UN)
            except Exception:
                pass
            os.close(blocker_fd)
    finally:
        appmod._release_single_instance_lock()


def test_cleanup_quiz_dialog_runtime_ignores_stale_session_token():
    calls: dict[str, int] = {"stop": 0}
    active_dialog = object()
    dummy = types.SimpleNamespace(
        _quiz_reason_job_token=9,
        quiz_dialog=active_dialog,
        quiz_session={"session_token": 22},
        _stop_quiz_or_review_timer_if_active=lambda finalize=True: calls.__setitem__("stop", calls["stop"] + 1),
    )

    StudyPlanGUI._cleanup_quiz_dialog_runtime(dummy, finalize_timer=True, session_token=21, dialog=active_dialog)

    assert calls["stop"] == 0
    assert int(dummy._quiz_reason_job_token) == 9
    assert dummy.quiz_dialog is active_dialog


def test_cleanup_quiz_dialog_runtime_applies_for_matching_session_token():
    calls: dict[str, int] = {"stop": 0}
    active_dialog = object()
    dummy = types.SimpleNamespace(
        _quiz_reason_job_token=9,
        quiz_dialog=active_dialog,
        quiz_session={"session_token": 22},
        _stop_quiz_or_review_timer_if_active=lambda finalize=True: calls.__setitem__("stop", calls["stop"] + 1),
    )

    StudyPlanGUI._cleanup_quiz_dialog_runtime(dummy, finalize_timer=True, session_token=22, dialog=active_dialog)

    assert calls["stop"] == 1
    assert int(dummy._quiz_reason_job_token) == 10
    assert dummy.quiz_dialog is None


def test_cleanup_quiz_dialog_runtime_refreshes_ui_after_abrupt_close():
    calls = {"stop": 0, "timer_label": 0, "dashboard": 0, "recommendations": 0, "study_room": 0, "tutor": 0}
    active_dialog = object()
    dummy = types.SimpleNamespace(
        _quiz_reason_job_token=4,
        quiz_dialog=active_dialog,
        quiz_session={"session_token": 7},
        _stop_quiz_or_review_timer_if_active=lambda finalize=True: calls.__setitem__("stop", calls["stop"] + 1),
        _update_action_timer_label=lambda: calls.__setitem__("timer_label", calls["timer_label"] + 1),
        update_dashboard=lambda: calls.__setitem__("dashboard", calls["dashboard"] + 1),
        update_recommendations=lambda: calls.__setitem__("recommendations", calls["recommendations"] + 1),
        update_study_room_card=lambda: calls.__setitem__("study_room", calls["study_room"] + 1),
        _refresh_tutor_workspace_page=lambda: calls.__setitem__("tutor", calls["tutor"] + 1),
    )

    StudyPlanGUI._cleanup_quiz_dialog_runtime(dummy, finalize_timer=True, session_token=7, dialog=active_dialog)

    assert calls == {
        "stop": 1,
        "timer_label": 1,
        "dashboard": 1,
        "recommendations": 1,
        "study_room": 1,
        "tutor": 1,
    }
    assert dummy.quiz_dialog is None


def test_cleanup_quiz_dialog_runtime_stale_token_skips_ui_reconciliation():
    calls = {"stop": 0, "timer_label": 0, "dashboard": 0}
    active_dialog = object()
    dummy = types.SimpleNamespace(
        _quiz_reason_job_token=4,
        quiz_dialog=active_dialog,
        quiz_session={"session_token": 99},
        _stop_quiz_or_review_timer_if_active=lambda finalize=True: calls.__setitem__("stop", calls["stop"] + 1),
        _update_action_timer_label=lambda: calls.__setitem__("timer_label", calls["timer_label"] + 1),
        update_dashboard=lambda: calls.__setitem__("dashboard", calls["dashboard"] + 1),
    )

    StudyPlanGUI._cleanup_quiz_dialog_runtime(dummy, finalize_timer=True, session_token=7, dialog=active_dialog)

    assert calls == {"stop": 0, "timer_label": 0, "dashboard": 0}
    assert dummy.quiz_dialog is active_dialog


def test_on_close_request_uses_runtime_shutdown_and_non_blocking_recap_notification():
    calls: dict[str, int] = {"shutdown": 0, "notify": 0, "save_data": 0, "save_status": 0}
    dummy = types.SimpleNamespace(
        _closing_from_recap=False,
        _shutdown_core_runtime=lambda finalize_timers=True: calls.__setitem__("shutdown", calls["shutdown"] + 1),
        _build_daily_recap_text=lambda: (
            "Daily Recap • 2026-03-06\n"
            "Pomodoros: 3\n"
            "Quiz questions: 18  •  Quiz sessions: 2\n"
            "Daily plan: 2/3 completed"
        ),
        send_notification=lambda _title, _body: calls.__setitem__("notify", calls["notify"] + 1),
        engine=types.SimpleNamespace(save_data=lambda: calls.__setitem__("save_data", calls["save_data"] + 1)),
        update_save_status_display=lambda: calls.__setitem__("save_status", calls["save_status"] + 1),
        _schedule_close_hard_exit=lambda _delay=0: None,
        get_application=lambda: None,
    )

    close_now = StudyPlanGUI.on_close_request(dummy)
    assert close_now is False
    assert calls == {"shutdown": 1, "notify": 1, "save_data": 1, "save_status": 1}
    assert dummy._closing_from_recap is True

    close_again = StudyPlanGUI.on_close_request(dummy)
    assert close_again is False
    assert calls == {"shutdown": 2, "notify": 1, "save_data": 2, "save_status": 2}


def test_get_remaining_today_blocks_consumes_completed_blocks_progressively():
    now_iso = datetime.datetime.now().isoformat(timespec="seconds")
    blocks = [
        {"kind": "Focus", "topic": "Topic A", "minutes": 25},
        {"kind": "Break", "topic": "", "minutes": 5},
        {"kind": "Focus", "topic": "Topic A", "minutes": 25},
        {"kind": "Recall", "topic": "Topic A", "minutes": 25},
        {"kind": "Quiz", "topic": "Topic A", "minutes": 10},
        {"kind": "Focus", "topic": "Topic B", "minutes": 25},
    ]
    dummy = types.SimpleNamespace(
        daily_pomodoros_by_chapter={"Topic A": 2},
        action_time_sessions=[
            {"kind": "pomodoro_recall", "topic": "Topic A", "seconds": 600.0, "timestamp": now_iso},
        ],
    )
    dummy._count_action_sessions_today = types.MethodType(StudyPlanGUI._count_action_sessions_today, dummy)
    dummy._get_today_block_completion_counts = types.MethodType(StudyPlanGUI._get_today_block_completion_counts, dummy)

    pending, done_count, total_count = StudyPlanGUI._get_remaining_today_blocks(dummy, blocks)

    assert done_count == 3
    assert total_count == 5  # break blocks are informational and excluded from progression matching
    assert [blk.get("kind") for blk in pending] == ["Quiz", "Focus"]
    assert [blk.get("topic") for blk in pending] == ["Topic A", "Topic B"]


def test_get_today_blocks_preview_returns_next_pending_block_for_today_schedule():
    now_iso = datetime.datetime.now().isoformat(timespec="seconds")
    engine = types.SimpleNamespace(
        exam_date=datetime.date.today(),
        has_availability=lambda: True,
        generate_study_schedule=lambda days=1: [
            {
                "date": datetime.date.today().isoformat(),
                "minutes": 120,
                "blocks": [
                    {"kind": "Focus", "topic": "Topic A", "minutes": 25},
                    {"kind": "Focus", "topic": "Topic A", "minutes": 25},
                    {"kind": "Recall", "topic": "Topic A", "minutes": 25},
                    {"kind": "Quiz", "topic": "Topic A", "minutes": 10},
                    {"kind": "Focus", "topic": "Topic B", "minutes": 25},
                ],
            }
        ],
    )
    dummy = types.SimpleNamespace(
        engine=engine,
        daily_pomodoros_by_chapter={"Topic A": 2},
        action_time_sessions=[
            {"kind": "pomodoro_recall", "topic": "Topic A", "seconds": 600.0, "timestamp": now_iso},
            {"kind": "quiz", "topic": "Topic A", "seconds": 300.0, "timestamp": now_iso},
        ],
        _preview_swap=False,
        _preview_swap_date="",
    )
    dummy._count_action_sessions_today = types.MethodType(StudyPlanGUI._count_action_sessions_today, dummy)
    dummy._get_today_block_completion_counts = types.MethodType(StudyPlanGUI._get_today_block_completion_counts, dummy)
    dummy._get_remaining_today_blocks = types.MethodType(StudyPlanGUI._get_remaining_today_blocks, dummy)

    preview = StudyPlanGUI._get_today_blocks_preview(dummy)
    assert preview
    assert preview[0].get("kind") == "Focus"
    assert preview[0].get("topic") == "Topic B"


def test_render_grounded_tutor_feedback_falls_back_when_evidence_fields_missing():
    dummy = types.SimpleNamespace()
    payload = StudyPlanGUI._render_grounded_tutor_feedback(
        dummy,
        "NPV compares discounted cash flows.",
        mode="teach",
        evidence_confidence=None,
        citations_count=None,
    )
    assert payload["evidence_confidence"] == 0.0
    assert payload["citations_count"] == 0
    assert payload["band"] == "Low confidence"
    assert "Trust signal: Low confidence" in str(payload["trust_summary"])


def test_render_grounded_tutor_feedback_coerces_invalid_confidence_and_citations():
    dummy = types.SimpleNamespace()
    payload = StudyPlanGUI._render_grounded_tutor_feedback(
        dummy,
        "Working-capital analysis should link inventory, receivables, and payables.",
        mode="teach",
        evidence_confidence="bad-value",
        citations_count="n/a",
    )
    assert payload["evidence_confidence"] == 0.0
    assert payload["citations_count"] == 0
    assert "Evidence:" in str(payload["details_text"])
