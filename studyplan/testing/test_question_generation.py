"""Tests for the auto question generation feature."""

import json
import os

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


# ---------------------------------------------------------------------------
# Agent-based question generation tests
# ---------------------------------------------------------------------------

from studyplan.question_generator import (
    AgentOrchestrator,
    DummyStructuredQGenService,
    QGenAgent,
    StructuredQuestion,
    get_structured_qgen_service,
)


def test_dummy_structured_service_returns_correct_count():
    svc = DummyStructuredQGenService()
    questions = svc.generate_structured_questions(topic="NPV", count=4)
    assert len(questions) == 4


def test_dummy_structured_service_question_shape():
    svc = DummyStructuredQGenService()
    q = svc.generate_structured_questions(topic="WACC", count=1)[0]
    assert isinstance(q["question"], str) and q["question"]
    assert isinstance(q["options"], list) and len(q["options"]) == 4
    assert isinstance(q["correct"], str) and q["correct"]
    assert isinstance(q["explanation"], str) and q["explanation"]
    assert q["correct"] in q["options"]


def test_dummy_structured_service_topic_in_question():
    svc = DummyStructuredQGenService()
    q = svc.generate_structured_questions(topic="IAS 16", count=1)[0]
    assert "IAS 16" in q["question"]


def test_get_structured_qgen_service_returns_valid_service():
    svc = get_structured_qgen_service()
    qs = svc.generate_structured_questions(topic="Leases", count=2)
    assert len(qs) == 2


def test_qgen_agent_run_returns_chapter_keyed_dict():
    svc = DummyStructuredQGenService()
    agent = QGenAgent(chapter="Chapter 1: IFRS", service=svc, count=3)
    result = agent.run()
    assert "Chapter 1: IFRS" in result
    assert len(result["Chapter 1: IFRS"]) == 3


def test_qgen_agent_propagates_source_text():
    svc = DummyStructuredQGenService()
    agent = QGenAgent(chapter="Leases", service=svc, count=1, source_text="IFRS 16")
    result = agent.run()
    q_text = result["Leases"][0]["question"]
    assert "IFRS 16" in q_text


def test_orchestrator_generates_for_all_chapters():
    svc = DummyStructuredQGenService()
    orch = AgentOrchestrator(service=svc, max_workers=2)
    chapters = ["Chapter 1: IFRS", "Chapter 2: Conceptual Framework"]
    merged = orch.generate_for_chapters(chapters, count_per_chapter=3)
    assert set(merged.keys()) == set(chapters)
    for ch in chapters:
        assert len(merged[ch]) == 3


def test_orchestrator_preserves_chapter_order():
    svc = DummyStructuredQGenService()
    orch = AgentOrchestrator(service=svc, max_workers=4)
    chapters = [f"Chapter {i}" for i in range(1, 6)]
    merged = orch.generate_for_chapters(chapters, count_per_chapter=2)
    assert list(merged.keys()) == chapters


def test_orchestrator_empty_chapters_returns_empty_dict():
    svc = DummyStructuredQGenService()
    orch = AgentOrchestrator(service=svc)
    assert orch.generate_for_chapters([]) == {}


def test_orchestrator_skips_failing_agent():
    class FailingForChapter2:
        def generate_structured_questions(self, *, topic, source_text=None, count=5):
            if topic == "Chapter 2":
                raise RuntimeError("backend error")
            return DummyStructuredQGenService().generate_structured_questions(
                topic=topic, source_text=source_text, count=count
            )

    orch = AgentOrchestrator(service=FailingForChapter2())
    merged = orch.generate_for_chapters(["Chapter 1", "Chapter 2", "Chapter 3"], count_per_chapter=2)
    assert "Chapter 1" in merged
    assert "Chapter 2" not in merged
    assert "Chapter 3" in merged


def test_orchestrator_merged_output_is_json_serialisable():
    svc = DummyStructuredQGenService()
    orch = AgentOrchestrator(service=svc)
    merged = orch.generate_for_chapters(["Chapter 1"], count_per_chapter=2)
    serialised = json.dumps(merged)
    assert "Chapter 1" in serialised


def test_orchestrator_save_merged_output(tmp_path):
    svc = DummyStructuredQGenService()
    orch = AgentOrchestrator(service=svc)
    merged = orch.generate_for_chapters(["Chapter 1: IFRS"], count_per_chapter=2)
    out_path = str(tmp_path / "questions.json")
    AgentOrchestrator.save_merged_output(merged, out_path)
    with open(out_path) as fh:
        loaded = json.load(fh)
    assert "Chapter 1: IFRS" in loaded
    assert len(loaded["Chapter 1: IFRS"]) == 2


def test_orchestrator_save_creates_parent_dirs(tmp_path):
    svc = DummyStructuredQGenService()
    orch = AgentOrchestrator(service=svc)
    merged = orch.generate_for_chapters(["Ch1"], count_per_chapter=1)
    out_path = str(tmp_path / "nested" / "dir" / "questions.json")
    AgentOrchestrator.save_merged_output(merged, out_path)
    assert os.path.exists(out_path)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
