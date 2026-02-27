"""Tests for the auto question generation feature."""

from studyplan.practice_loop_controller import PracticeLoopController
from studyplan.question_generator import DummyQGenService, get_qgen_service


def test_auto_generate_questions_default():
    controller = PracticeLoopController()
    questions = controller.auto_generate_questions(topic="NPV", count=3)
    assert len(questions) == 3
    assert "Auto-generated" in questions[0]


def test_auto_generate_questions_injected_service():
    dummy = DummyQGenService()
    controller = PracticeLoopController(qgen_svc=dummy)
    qlist = controller.auto_generate_questions(topic="WACC", source_text="cost of capital", count=2)
    assert all("WACC" in q for q in qlist)
    assert len(qlist) == 2


def test_get_qgen_service_selects_llamacpp_backend(monkeypatch):
    monkeypatch.setenv("STUDYPLAN_QGEN_BACKEND", "llama_cpp")
    monkeypatch.setenv("STUDYPLAN_LLAMACPP_SYNC_OLLAMA", "0")
    svc = get_qgen_service()
    assert svc.__class__.__name__ == "LlamaCppHTTPQGenService"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
