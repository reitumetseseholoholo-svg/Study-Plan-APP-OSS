import json
import types
import urllib.request

import pytest

try:
    from studyplan_app import StudyPlanGUI
except Exception as exc:  # pragma: no cover - environment-dependent import gate
    pytest.skip(f"studyplan_app import unavailable: {exc}", allow_module_level=True)


def _make_dummy(host: str = "127.0.0.1:11434"):
    dummy = types.SimpleNamespace(
        local_llm_host=host,
        local_llm_timeout_seconds=30,
    )
    dummy._allow_remote_ollama_hosts = types.MethodType(StudyPlanGUI._allow_remote_ollama_hosts, dummy)
    dummy._is_local_or_private_host = types.MethodType(StudyPlanGUI._is_local_or_private_host, dummy)
    dummy._normalize_ollama_host = types.MethodType(StudyPlanGUI._normalize_ollama_host, dummy)
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


def test_validate_selected_file_size_rejects_directory(tmp_path):
    dummy = types.SimpleNamespace()
    with pytest.raises(ValueError):
        StudyPlanGUI._validate_selected_file_size(dummy, str(tmp_path), 1024, "Import")
