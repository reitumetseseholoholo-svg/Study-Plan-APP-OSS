"""Tests for the auto question generation feature."""

from studyplan.practice_loop_controller import PracticeLoopController
from studyplan.question_generator import DummyQGenService, OllamaQGenService, get_qgen_service


def test_auto_generate_questions_default():
    """Default controller uses OllamaQGenService; returns a list of strings (may be empty when Ollama is not running)."""
    controller = PracticeLoopController()
    questions = controller.auto_generate_questions(topic="NPV", count=3)
    assert isinstance(questions, list)
    assert all(isinstance(q, str) for q in questions)
    assert all(q.strip() == q and q for q in questions)


def test_get_qgen_service_returns_ollama_instance():
    """get_qgen_service() returns an OllamaQGenService by default."""
    svc = get_qgen_service()
    assert isinstance(svc, OllamaQGenService)


def test_ollama_qgen_service_unreachable_returns_empty_list():
    """OllamaQGenService returns [] when Ollama is unreachable (no exception raised)."""
    svc = OllamaQGenService(host="http://127.0.0.1:19999", model="none", timeout_seconds=5.0)
    result = svc.generate_questions(topic="NPV", count=3)
    assert result == []


def test_ollama_qgen_service_parse_questions():
    """_parse_questions correctly strips numbering and returns clean lines."""
    svc = OllamaQGenService()
    text = "1. What is NPV?\n2) How is IRR calculated?\n3- Define WACC in brief."
    questions = svc._parse_questions(text, 5)
    assert len(questions) == 3
    assert all("?" in q or len(q) > 10 for q in questions)
    assert not any(q[0].isdigit() for q in questions)


def test_ollama_qgen_service_parse_questions_respects_count_cap():
    svc = OllamaQGenService()
    text = "\n".join(f"{i+1}. Question number {i+1} about finance?" for i in range(10))
    questions = svc._parse_questions(text, 4)
    assert len(questions) == 4


def test_auto_generate_questions_injected_service():
    dummy = DummyQGenService()
    controller = PracticeLoopController(qgen_svc=dummy)
    qlist = controller.auto_generate_questions(topic="WACC", source_text="cost of capital", count=2)
    assert all("WACC" in q for q in qlist)
    assert len(qlist) == 2


def test_auto_generate_questions_sanitizes_inputs():
    controller = PracticeLoopController(qgen_svc=DummyQGenService())
    qlist = controller.auto_generate_questions(topic="   ", count=0)
    assert len(qlist) == 1
    assert "General" in qlist[0]


def test_auto_generate_questions_clamps_large_count():
    controller = PracticeLoopController(qgen_svc=DummyQGenService())
    qlist = controller.auto_generate_questions(topic="NPV", count=999)
    assert len(qlist) == 20


def test_auto_generate_questions_backend_failure_returns_empty_list():
    class BrokenService:
        def generate_questions(self, **kwargs):
            raise RuntimeError("backend unavailable")

    controller = PracticeLoopController(qgen_svc=BrokenService())
    qlist = controller.auto_generate_questions(topic="NPV", count=3)
    assert qlist == []


def test_auto_generate_questions_invalid_backend_payload_returns_empty_list():
    class InvalidPayloadService:
        def generate_questions(self, **kwargs):
            return "not-a-list"

    controller = PracticeLoopController(qgen_svc=InvalidPayloadService())
    qlist = controller.auto_generate_questions(topic="NPV", count=3)
    assert qlist == []


def test_auto_generate_questions_none_payload_returns_empty_list():
    class NonePayloadService:
        def generate_questions(self, **kwargs):
            return None

    controller = PracticeLoopController(qgen_svc=NonePayloadService())
    qlist = controller.auto_generate_questions(topic="NPV", count=3)
    assert qlist == []


def test_auto_generate_questions_output_contract_is_clean_string_list():
    class MixedPayloadService:
        def generate_questions(self, **kwargs):
            return ["  q1  ", "", None, "q2", "   ", 123, "q4"]

    controller = PracticeLoopController(qgen_svc=MixedPayloadService())
    qlist = controller.auto_generate_questions(topic="NPV", count=3)
    assert qlist == ["q1", "q2", "123"]
    assert all(isinstance(q, str) for q in qlist)
    assert all(q.strip() == q for q in qlist)
    assert all(q for q in qlist)


def test_regression_auto_generate_questions_malformed_dict_payload_returns_empty_list():
    class DictPayloadService:
        def generate_questions(self, **kwargs):
            return {"q1": "bad-shape"}

    controller = PracticeLoopController(qgen_svc=DictPayloadService())
    qlist = controller.auto_generate_questions(topic="NPV", count=3)
    assert qlist == []


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])

