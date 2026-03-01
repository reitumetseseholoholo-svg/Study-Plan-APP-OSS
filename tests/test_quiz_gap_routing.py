from studyplan_app_kpi_routing import _adjust_outcome_gap_ratio, _build_gap_routing_meta, _combine_quiz_indices


def test_start_quiz_session_gap_quota_merge_quiz_kind():
    merged = _combine_quiz_indices("quiz", primary_indices=[2, 3, 4, 5], total=5, gap_indices=[0, 1, 2])
    assert merged == [0, 1, 2, 3, 4]


def test_start_quiz_session_review_kind_ignores_gap_quota():
    merged = _combine_quiz_indices("review", primary_indices=[9, 8, 7], total=2, gap_indices=[1, 2, 3])
    assert merged == [9, 8]


def test_start_quiz_session_no_duplicates_after_merge():
    merged = _combine_quiz_indices("drill", primary_indices=[2, 2, 3, 4], total=6, gap_indices=[1, 2, 3])
    assert merged == [1, 2, 3, 4]
    assert len(merged) == len(set(merged))


def test_start_quiz_session_fallback_to_srs_when_gap_unavailable():
    merged = _combine_quiz_indices("leech", primary_indices=[6, 5, 4], total=3, gap_indices=[])
    assert merged == [6, 5, 4]


def test_start_quiz_session_interleave_merge_behaves_like_non_review():
    merged = _combine_quiz_indices("interleave", primary_indices=[3, 4, 5], total=4, gap_indices=[1, 3])
    assert merged == [1, 3, 4, 5]


def test_build_gap_routing_meta_tracks_hits_and_quota():
    meta = _build_gap_routing_meta(
        kind="quiz",
        session_indices=[10, 2, 7, 4],
        gap_indices=[2, 5, 4, 4],
        requested_quota=3,
        eligible=True,
    )
    assert meta["active"] is True
    assert meta["eligible"] is True
    assert meta["requested"] == 3
    assert meta["available"] == 3
    assert meta["hit"] == 2
    assert meta["selected_total"] == 4
    assert abs(float(meta["hit_ratio"]) - (2.0 / 3.0)) < 1e-9


def test_build_gap_routing_meta_review_is_inactive():
    meta = _build_gap_routing_meta(
        kind="review",
        session_indices=[1, 2, 3],
        gap_indices=[1, 2],
        requested_quota=2,
        eligible=True,
    )
    assert meta["active"] is False
    assert meta["eligible"] is True
    assert meta["hit"] == 2


def test_build_gap_routing_meta_keeps_capability_fields():
    meta = _build_gap_routing_meta(
        kind="quiz",
        session_indices=[1, 2],
        gap_indices=[2],
        requested_quota=1,
        eligible=True,
        capability="D",
        capability_hit_rate=0.4,
    )
    assert meta["capability"] == "D"
    assert float(meta["capability_hit_rate"]) == 0.4


def test_adjust_outcome_gap_ratio_responds_to_capability_kpi():
    assert _adjust_outcome_gap_ratio(0.5, None) == 0.5
    assert _adjust_outcome_gap_ratio(0.5, 0.40) == 0.7
    assert _adjust_outcome_gap_ratio(0.5, 0.55) == 0.6
    assert _adjust_outcome_gap_ratio(0.5, 0.90) == 0.4
