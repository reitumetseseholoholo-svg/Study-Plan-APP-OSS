from studyplan.ai.recovery import build_deterministic_fallback_response


def test_build_deterministic_fallback_response_is_stable_for_same_input():
    a = build_deterministic_fallback_response(
        error_code="timeout",
        message="queue wait exceeded",
        model="llama-test",
        topic_hint="npv",
    )
    b = build_deterministic_fallback_response(
        error_code="timeout",
        message="queue wait exceeded",
        model="llama-test",
        topic_hint="npv",
    )
    assert a == b
    assert a["error_code"] == "timeout"
    assert a["failure_kind"] == "timeout"
    assert a["fallback_code"] == "fallback_timeout"
    assert "npv" in str(a["text"]).lower()
    assert "quick practice step while i reconnect" in str(a["text"]).lower()


def test_build_deterministic_fallback_response_exposes_machine_readable_codes():
    out = build_deterministic_fallback_response(
        error_code="invalid_json",
        message="json parse failed",
        model="llama-test",
        topic_hint="wacc",
    )
    assert out["error_code"] == "invalid_json"
    assert out["failure_kind"] == "invalid_output"
    assert out["fallback_code"] == "fallback_invalid_output"
    assert isinstance(out["recovery_sequence"], list)
    assert out["recovery_sequence"]


def test_build_deterministic_fallback_response_model_unavailable_message():
    out = build_deterministic_fallback_response(
        error_code="model_missing",
        message="model not found",
        model="llama-test",
        topic_hint="variance analysis",
    )
    text = str(out["text"]).lower()
    assert "model is temporarily unavailable" in text
    assert "quick practice step while i reconnect" in text
    assert "variance analysis" in text
