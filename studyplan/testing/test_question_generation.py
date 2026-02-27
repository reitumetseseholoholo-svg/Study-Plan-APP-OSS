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


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
