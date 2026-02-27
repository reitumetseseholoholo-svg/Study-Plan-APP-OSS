"""Tests for the auto question generation feature."""

from studyplan.practice_loop_controller import PracticeLoopController
from studyplan.question_generator import DummyQGenService


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
