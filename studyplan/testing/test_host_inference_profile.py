"""Tests for RAM/CPU-aware llama defaults."""

from studyplan.ai.host_inference_profile import MemSnapshot, _memory_pressure, suggested_auto_llama_extra_args


def test_memory_pressure_tiers():
    assert _memory_pressure(MemSnapshot()) == "unknown"
    tight = MemSnapshot(
        mem_total_kb=6 * 1024 * 1024,
        mem_available_kb=900 * 1024,
        swap_total_kb=6 * 1024 * 1024,
        swap_free_kb=4 * 1024 * 1024,
    )
    assert _memory_pressure(tight) == "high"
    ok = MemSnapshot(
        mem_total_kb=64 * 1024 * 1024,
        mem_available_kb=32 * 1024 * 1024,
        swap_total_kb=8 * 1024 * 1024,
        swap_free_kb=8 * 1024 * 1024,
    )
    assert _memory_pressure(ok) == "low"


def test_auto_llama_extras_only_under_high_pressure():
    assert suggested_auto_llama_extra_args(
        MemSnapshot(
            mem_total_kb=64 * 1024 * 1024,
            mem_available_kb=40 * 1024 * 1024,
            swap_total_kb=0,
            swap_free_kb=0,
        )
    ) == []
    extras = suggested_auto_llama_extra_args(
        MemSnapshot(
            mem_total_kb=6 * 1024 * 1024,
            mem_available_kb=800 * 1024,
            swap_total_kb=6 * 1024 * 1024,
            swap_free_kb=2 * 1024 * 1024,
        )
    )
    assert "--no-mmap" in extras


def test_ctx_batch_respond_to_patched_snapshot(monkeypatch):
    from studyplan.ai import host_inference_profile as hip

    hi = MemSnapshot(
        mem_total_kb=6 * 1024 * 1024,
        mem_available_kb=700 * 1024,
        swap_total_kb=6 * 1024 * 1024,
        swap_free_kb=3 * 1024 * 1024,
    )
    lo = MemSnapshot(
        mem_total_kb=64 * 1024 * 1024,
        mem_available_kb=40 * 1024 * 1024,
        swap_total_kb=0,
        swap_free_kb=0,
    )
    monkeypatch.setattr(hip, "mem_snapshot", lambda: hi)
    assert hip.default_llama_server_ctx_size() == 2048
    assert hip.default_llama_server_batch_size() == 256
    assert hip.default_ollama_client_num_ctx() == 2048
    monkeypatch.setattr(hip, "mem_snapshot", lambda: lo)
    assert hip.default_llama_server_ctx_size() == 4096
    assert hip.default_llama_server_batch_size() == 512


def test_ollama_app_concurrency_defaults_track_pressure(monkeypatch):
    from studyplan.ai import host_inference_profile as hip

    hi = MemSnapshot(
        mem_total_kb=6 * 1024 * 1024,
        mem_available_kb=700 * 1024,
        swap_total_kb=6 * 1024 * 1024,
        swap_free_kb=3 * 1024 * 1024,
    )
    mod = MemSnapshot(
        mem_total_kb=12 * 1024 * 1024,
        mem_available_kb=3 * 1024 * 1024,
        swap_total_kb=2 * 1024 * 1024,
        swap_free_kb=2 * 1024 * 1024,
    )
    lo = MemSnapshot(
        mem_total_kb=64 * 1024 * 1024,
        mem_available_kb=40 * 1024 * 1024,
        swap_total_kb=0,
        swap_free_kb=0,
    )
    monkeypatch.setattr(hip, "mem_snapshot", lambda: hi)
    assert hip.default_ollama_app_max_concurrent_requests() == 1
    assert hip.default_ollama_app_queue_wait_seconds() == 4.0
    monkeypatch.setattr(hip, "mem_snapshot", lambda: mod)
    assert hip.default_ollama_app_max_concurrent_requests() == 2
    assert hip.default_ollama_app_queue_wait_seconds() == 2.5
    monkeypatch.setattr(hip, "mem_snapshot", lambda: lo)
    assert hip.default_ollama_app_max_concurrent_requests() == 3
    assert hip.default_ollama_app_queue_wait_seconds() == 1.5


def test_oom_tuning_defaults_track_pressure(monkeypatch):
    from studyplan.ai import host_inference_profile as hip

    hi = MemSnapshot(
        mem_total_kb=6 * 1024 * 1024,
        mem_available_kb=700 * 1024,
        swap_total_kb=6 * 1024 * 1024,
        swap_free_kb=3 * 1024 * 1024,
    )
    mod = MemSnapshot(
        mem_total_kb=12 * 1024 * 1024,
        mem_available_kb=3 * 1024 * 1024,
        swap_total_kb=2 * 1024 * 1024,
        swap_free_kb=2 * 1024 * 1024,
    )
    lo = MemSnapshot(
        mem_total_kb=64 * 1024 * 1024,
        mem_available_kb=40 * 1024 * 1024,
        swap_total_kb=0,
        swap_free_kb=0,
    )
    monkeypatch.setattr(hip, "mem_snapshot", lambda: hi)
    assert hip.default_llama_server_idle_shutdown_seconds() == 90.0
    assert hip.default_performance_cache_max_size() == 400
    assert hip.default_ai_tutor_rag_max_sources() == 4
    assert hip.default_ai_tutor_rag_max_pdf_bytes() == 96 * 1024 * 1024
    assert hip.default_ai_tutor_max_response_chars() == 7000
    monkeypatch.setattr(hip, "mem_snapshot", lambda: mod)
    assert hip.default_llama_server_idle_shutdown_seconds() == 180.0
    assert hip.default_performance_cache_max_size() == 700
    assert hip.default_ai_tutor_rag_max_sources() == 5
    assert hip.default_ai_tutor_rag_max_pdf_bytes() == 160 * 1024 * 1024
    assert hip.default_ai_tutor_max_response_chars() == 9500
    monkeypatch.setattr(hip, "mem_snapshot", lambda: lo)
    assert hip.default_llama_server_idle_shutdown_seconds() == 300.0
    assert hip.default_performance_cache_max_size() == 1000
    assert hip.default_ai_tutor_rag_max_sources() == 6
    assert hip.default_ai_tutor_rag_max_pdf_bytes() == 256 * 1024 * 1024
    assert hip.default_ai_tutor_max_response_chars() == 12000
