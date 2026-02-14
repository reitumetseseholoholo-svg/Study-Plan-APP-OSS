import datetime
import json
import types
import urllib.error
import urllib.request

import pytest
from studyplan_ai_tutor import (
    build_rag_context_block,
    classify_ollama_error,
    chunk_text_for_rag,
    compute_tutor_control_state,
    lexical_rank_rag_chunks,
    normalize_tutor_timeout_seconds,
    should_keep_response_bottom,
)

try:
    from studyplan_app import StudyPlanGUI
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
    dummy._gpt4all_auto_import_enabled = types.MethodType(StudyPlanGUI._gpt4all_auto_import_enabled, dummy)
    dummy._gpt4all_models_dir = types.MethodType(StudyPlanGUI._gpt4all_models_dir, dummy)
    dummy._normalize_gpt4all_filename_to_ollama_model = types.MethodType(
        StudyPlanGUI._normalize_gpt4all_filename_to_ollama_model, dummy
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
        module_title="ACCA FM",
        chapter="Investment Decisions",
    )
    assert "Module: ACCA FM" in prompt
    assert "Current chapter: Investment Decisions" in prompt
    assert "USER: Explain NPV." in prompt
    assert "ASSISTANT: NPV discounts cash flows." in prompt
    assert "USER: Give me a 3-question drill." in prompt
    assert prompt.endswith("ASSISTANT:")


def test_build_ai_tutor_context_prompt_clamps_to_last_10_messages():
    dummy = _make_dummy()
    history = []
    for i in range(12):
        history.append({"role": "user", "content": f"u{i}"})
    prompt = StudyPlanGUI._build_ai_tutor_context_prompt(
        dummy,
        history=history,
        user_prompt="latest",
        module_title="ACCA FM",
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
        module_title="ACCA FM",
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
        module_title="ACCA FM",
        current_topic="Cost of Capital",
        semantic_enabled=False,
        engine=types.SimpleNamespace(),
    )
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
            "error_class": "Busy",
            "latency_ms": -5,
            "prompt_chars": "120",
            "response_chars": 240,
            "timeout_seconds": 9999,
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
    assert cleaned["ts_utc"]

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
            },
            {
                "outcome": "cancelled",
                "error_class": "timeout",
                "latency_ms": 1200,
                "prompt_chars": 100,
                "response_chars": 150,
                "prompt_tokens_est": 25,
                "response_tokens_est": 38,
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
    assert summary["p95_latency_ms"] == pytest.approx(1200.0)
    assert summary["avg_prompt_chars"] == pytest.approx((120 + 100 + 80 + 60) / 4.0)
    assert summary["error_classes"] == {"busy": 2, "timeout": 1}


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
            "p95_latency_ms": 1700.0,
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
    assert "AI Tutor latency avg/p95 (ms): 830.0/1700.0" in msg
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
