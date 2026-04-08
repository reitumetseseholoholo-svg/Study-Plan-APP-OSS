from types import SimpleNamespace


def test_build_question_stats_export_rows_includes_qid_keys_and_manual_links():
    from studyplan_app_runtime_helpers import build_question_stats_export_rows

    chapter = "FM Function"
    engine = SimpleNamespace(
        QUESTIONS={chapter: [{"question": "Q1?", "outcome_ids": ["direct1"]}]},
        question_stats={
            chapter: {
                "fp1": {
                    "attempts": 2,
                    "correct": 1,
                    "linked_outcome_ids": ["manual1"],
                    "linked_outcome_source": "manual",
                    "linked_outcome_at": "2026-03-27T12:00:00",
                }
            }
        },
        _question_qid=lambda ch, idx: "fp1" if (ch == chapter and idx == 0) else str(idx),
        resolve_question_outcomes=lambda ch, idx: {"outcome_ids": ["resolved1"]} if (ch == chapter and idx == 0) else {"outcome_ids": []},
    )

    rows = build_question_stats_export_rows(engine)
    assert rows and rows[0][0] == "Chapter"
    assert len(rows) == 2
    data = rows[1]
    assert data[0] == chapter
    assert data[1] == 0
    assert data[2] == "Q1?"
    assert data[10] == "direct1"
    assert data[11] == "manual1"
    assert data[12] == "manual"
    assert data[13] == "2026-03-27T12:00:00"
    assert data[14] == "resolved1"
