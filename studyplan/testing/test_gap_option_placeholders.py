from studyplan.question_quality import gap_options_look_like_llm_placeholders


def test_detects_full_option_text_templates():
    opts = ["Full option text A", "Full option text B", "Full option text C", "Full option text D"]
    assert gap_options_look_like_llm_placeholders(opts)


def test_allows_real_distractors():
    opts = [
        "Recognised in other comprehensive income",
        "Expensed immediately",
        "Capitalised as PPE",
        "Disclosed only in the notes",
    ]
    assert not gap_options_look_like_llm_placeholders(opts)
