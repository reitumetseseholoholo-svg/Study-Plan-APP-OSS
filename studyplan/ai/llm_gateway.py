from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from typing import Any, Sequence
from urllib.parse import urlparse

from .model_routing import routed_failover_chain_for_purpose, routed_primary_for_purpose


@dataclass(frozen=True)
class ResolvedOpenAICompatibleEndpoint:
    endpoint: str
    source: str
    request_timeout_seconds: float = 8.0
    auth_mode: str = "discovery"


def resolve_openai_compatible_endpoint(config: Any) -> ResolvedOpenAICompatibleEndpoint | None:
    """Resolve the active OpenAI-compatible endpoint.

    Preference order:
    1. explicit gateway endpoint
    2. legacy cloud llama.cpp endpoint when it is intentionally internet-hosted
    """
    gateway_enabled = bool(getattr(config, "LLM_GATEWAY_ENABLED", False))
    gateway_endpoint = str(getattr(config, "LLM_GATEWAY_ENDPOINT", "") or "").strip()
    if gateway_enabled and gateway_endpoint:
        timeout_s = float(getattr(config, "LLM_GATEWAY_REQUEST_TIMEOUT_SECONDS", 8.0) or 8.0)
        timeout_s = max(1.0, min(60.0, timeout_s))
        return ResolvedOpenAICompatibleEndpoint(
            endpoint=gateway_endpoint,
            source="gateway",
            request_timeout_seconds=timeout_s,
            auth_mode="discovery",
        )

    endpoint = str(getattr(config, "LLAMA_CPP_ENDPOINT", "") or "").strip()
    if not endpoint:
        return None
    prefer_external = bool(getattr(config, "CLOUD_LLAMACPP_PREFER_EXTERNAL", False))
    if not prefer_external:
        return None
    parsed = urlparse(endpoint if "://" in endpoint else f"http://{endpoint}")
    hostname = str(getattr(parsed, "hostname", "") or "").strip().lower()
    scheme = str(getattr(parsed, "scheme", "") or "").strip().lower()
    if scheme not in {"http", "https"} or not hostname:
        return None
    try:
        ip_val = ipaddress.ip_address(hostname)
        if bool(ip_val.is_loopback or ip_val.is_private):
            return None
    except Exception:
        if hostname in {"localhost"} or hostname.endswith(".local") or hostname.endswith(".lan"):
            return None
    timeout_s = float(getattr(config, "CLOUD_LLAMACPP_REQUEST_TIMEOUT_SECONDS", 8.0) or 8.0)
    timeout_s = max(1.0, min(60.0, timeout_s))
    return ResolvedOpenAICompatibleEndpoint(
        endpoint=endpoint,
        source="llama_cpp_cloud",
        request_timeout_seconds=timeout_s,
        auth_mode="cloud_llamacpp",
    )


def resolve_openai_compatible_model_candidates(
    *,
    purpose: str,
    requested_model: str = "",
    configured_model: str = "",
    fallback_models: Sequence[str] | str = (),
    extra_candidates: Sequence[str] | None = None,
) -> list[str]:
    """Build a stable candidate list for OpenAI-compatible backends."""
    ordered: list[str] = []
    seen: set[str] = set()

    def _append(value: Any) -> None:
        item = str(value or "").strip()
        if not item or item in seen:
            return
        seen.add(item)
        ordered.append(item)

    _append(requested_model)
    _append(configured_model)
    if isinstance(fallback_models, str):
        tokens = fallback_models.replace(";", ",").replace("\n", ",").split(",")
        for token in tokens:
            _append(token)
    else:
        for item in list(fallback_models or []):
            _append(item)
    for item in list(extra_candidates or []):
        _append(item)

    if not ordered:
        return []

    primary = routed_primary_for_purpose(str(purpose or ""), ordered)
    failovers = routed_failover_chain_for_purpose(str(purpose or ""), ordered)

    final: list[str] = []
    final_seen: set[str] = set()

    def _add(value: str) -> None:
        item = str(value or "").strip()
        if not item or item in final_seen or item not in seen:
            return
        final_seen.add(item)
        final.append(item)

    _add(primary)
    for item in failovers:
        _add(item)
    for item in ordered:
        _add(item)
    return final
