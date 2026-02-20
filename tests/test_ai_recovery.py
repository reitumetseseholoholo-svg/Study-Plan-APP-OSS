from studyplan.ai.recovery import build_recovery_sequence, classify_failure_kind, summarize_recovery


def test_classify_failure_kind_maps_host_unreachable():
    kind = classify_failure_kind("host_unreachable", "Connection refused")
    assert kind == "conn_refused"


def test_build_recovery_sequence_contains_expected_steps_for_timeout():
    seq = build_recovery_sequence("timeout")
    assert seq[:2] == ["retry_same_model", "reduce_context"]
    assert "switch_model" in seq
    assert seq[-1] == "concise_fallback"


def test_classify_failure_kind_detects_invalid_output():
    kind = classify_failure_kind("unknown", "Guardrail validation failed: expected valid JSON")
    assert kind == "invalid_output"


def test_build_recovery_sequence_invalid_output_uses_strict_json_retry():
    seq = build_recovery_sequence("invalid_output")
    assert seq[:2] == ["retry_same_model", "retry_strict_json"]
    assert seq[-1] == "concise_fallback"


def test_summarize_recovery_contains_hint_and_sequence():
    payload = summarize_recovery("timeout", "request timed out", model="model-a")
    assert payload["failure_kind"] == "timeout"
    assert isinstance(payload["recovery_sequence"], list)
    assert "Recovery" in payload["hint"]
