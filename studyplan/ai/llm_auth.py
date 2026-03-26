from __future__ import annotations

from dataclasses import dataclass
import json
import ipaddress
import os
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import urlparse


@dataclass(frozen=True)
class DiscoveredLLMAuth:
    """Resolved request headers for an OpenAI-compatible LLM endpoint."""

    headers: dict[str, str]
    provider: str
    source: str
    key_name: str


def discover_llm_auth_headers(
    endpoint: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    search_paths: Sequence[str | os.PathLike[str]] | None = None,
) -> DiscoveredLLMAuth | None:
    """Discover an API credential for an OpenAI-compatible cloud endpoint.

    The search order is:
    - explicit generic overrides from the process environment
    - provider-specific environment variables inferred from the endpoint host
    - credentials stored in conventional local files
    - a broader fallback scan of common provider env vars

    Returns headers ready to attach to ``urllib.request.Request``.
    """

    env_map = dict(env or os.environ)
    provider, localish = _endpoint_provider_hint(endpoint)

    candidates: list[tuple[str, tuple[str, ...], dict[str, str], str]] = []

    # Explicit generic override: always wins.
    candidates.extend(
        [
            ("generic", ("STUDYPLAN_CLOUD_LLAMACPP_AUTH_BEARER",), {"Authorization": "Bearer {token}"}, "generic_override"),
            ("generic", ("STUDYPLAN_LLM_AUTH_BEARER",), {"Authorization": "Bearer {token}"}, "generic_override"),
            ("generic", ("STUDYPLAN_LLM_GATEWAY_API_KEY",), {"Authorization": "Bearer {token}"}, "generic_override"),
            ("generic", ("LLM_GATEWAY_API_KEY",), {"Authorization": "Bearer {token}"}, "generic_override"),
            ("generic", ("LLM_API_KEY",), {"Authorization": "Bearer {token}"}, "generic_override"),
        ]
    )

    provider_rules = _provider_rules_for(provider)
    if provider_rules:
        candidates.extend(provider_rules)

    # Generic fallbacks when the endpoint host is not a known provider.
    if provider == "generic" and not localish:
        candidates.extend(_common_fallback_rules())

    file_values = _load_discovery_files(search_paths)

    for rule_provider, key_names, header_templates, source_label in candidates:
        token_name, token_value = _find_token(env_map, file_values, key_names)
        if not token_name or not token_value:
            continue
        headers = _render_headers(header_templates, token_value)
        return DiscoveredLLMAuth(
            headers=headers,
            provider=rule_provider,
            source=source_label,
            key_name=token_name,
        )

    return None


def _render_headers(templates: dict[str, str], token: str) -> dict[str, str]:
    value = str(token or "").strip()
    headers: dict[str, str] = {}
    for name, template in templates.items():
        if "{token}" in template:
            rendered = template.format(token=value)
        else:
            rendered = template
        headers[name] = rendered
    return headers


def _find_token(
    env_map: Mapping[str, str],
    file_values: Mapping[str, str],
    key_names: Sequence[str],
) -> tuple[str, str]:
    for key_name in key_names:
        env_value = str(env_map.get(key_name, "") or "").strip()
        if env_value:
            return key_name, env_value
        file_value = str(file_values.get(key_name, "") or "").strip()
        if file_value:
            return key_name, file_value
    return "", ""


def _endpoint_provider_hint(endpoint: str | None) -> tuple[str, bool]:
    raw = str(endpoint or "").strip()
    if not raw:
        return "generic", False
    candidate = raw if "://" in raw else f"http://{raw}"
    try:
        parsed = urlparse(candidate)
    except Exception:
        return "generic", False
    host = str(parsed.hostname or "").strip().lower()
    if not host:
        return "generic", False
    localish = False
    try:
        ip_val = ipaddress.ip_address(host)
        localish = bool(ip_val.is_loopback or ip_val.is_private)
    except Exception:
        localish = bool(host in {"localhost"} or host.endswith(".local") or host.endswith(".lan"))
    if localish:
        return "generic", True
    if "openrouter.ai" in host:
        return "openrouter", False
    if "api.openai.com" in host:
        return "openai", False
    if "anthropic.com" in host:
        return "anthropic", False
    if "generativelanguage.googleapis.com" in host or "ai.google.dev" in host or host.endswith("googleapis.com"):
        return "gemini", False
    if "openai.azure.com" in host or host.endswith(".azure.com"):
        return "azure", False
    if "moonshot.cn" in host or "api.moonshot.ai" in host:
        return "moonshot", False
    if "mistral.ai" in host:
        return "mistral", False
    return "generic", False


def _provider_rules_for(provider: str) -> list[tuple[str, tuple[str, ...], dict[str, str], str]]:
    if provider == "openrouter":
        return [
            ("openrouter", ("OPENROUTER_API_KEY",), {"Authorization": "Bearer {token}"}, "provider_env"),
        ]
    if provider == "openai":
        return [
            ("openai", ("OPENAI_API_KEY",), {"Authorization": "Bearer {token}"}, "provider_env"),
        ]
    if provider == "anthropic":
        return [
            (
                "anthropic",
                ("ANTHROPIC_API_KEY",),
                {"Authorization": "Bearer {token}", "x-api-key": "{token}"},
                "provider_env",
            ),
        ]
    if provider == "gemini":
        return [
            (
                "gemini",
                ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
                {"Authorization": "Bearer {token}", "x-goog-api-key": "{token}"},
                "provider_env",
            ),
        ]
    if provider == "azure":
        return [
            ("azure", ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_KEY"), {"api-key": "{token}"}, "provider_env"),
        ]
    if provider == "moonshot":
        return [
            ("moonshot", ("MOONSHOT_API_KEY", "KIMI_API_KEY"), {"Authorization": "Bearer {token}"}, "provider_env"),
        ]
    if provider == "mistral":
        return [
            ("mistral", ("MISTRAL_API_KEY",), {"Authorization": "Bearer {token}"}, "provider_env"),
        ]
    return []


def _common_fallback_rules() -> list[tuple[str, tuple[str, ...], dict[str, str], str]]:
    return [
        ("generic", ("OPENROUTER_API_KEY",), {"Authorization": "Bearer {token}"}, "fallback_env"),
        ("generic", ("OPENAI_API_KEY",), {"Authorization": "Bearer {token}"}, "fallback_env"),
        ("generic", ("ANTHROPIC_API_KEY",), {"Authorization": "Bearer {token}", "x-api-key": "{token}"}, "fallback_env"),
        (
            "generic",
            ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
            {"Authorization": "Bearer {token}", "x-goog-api-key": "{token}"},
            "fallback_env",
        ),
        ("generic", ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_KEY"), {"api-key": "{token}"}, "fallback_env"),
        ("generic", ("MOONSHOT_API_KEY", "KIMI_API_KEY"), {"Authorization": "Bearer {token}"}, "fallback_env"),
        ("generic", ("MISTRAL_API_KEY",), {"Authorization": "Bearer {token}"}, "fallback_env"),
    ]


def _load_discovery_files(
    search_paths: Sequence[str | os.PathLike[str]] | None,
) -> dict[str, str]:
    out: dict[str, str] = {}
    paths = _normalize_search_paths(search_paths)
    for path in paths:
        for candidate in _candidate_files_for_path(path):
            payload = _load_credentials_file(candidate)
            for key, value in payload.items():
                if key not in out and value:
                    out[key] = value
    return out


def _normalize_search_paths(search_paths: Sequence[str | os.PathLike[str]] | None) -> list[Path]:
    candidates: list[Path] = []
    raw_paths = list(search_paths or ())
    if not raw_paths:
        raw_paths = [Path.cwd(), Path.home() / ".config" / "studyplan"]
    for item in raw_paths:
        try:
            path = Path(item).expanduser()
        except Exception:
            continue
        if path not in candidates:
            candidates.append(path)
    return candidates


def _candidate_files_for_path(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.exists():
        return []
    files = [
        path / ".env",
        path / "llm.env",
        path / "llm.json",
        path / "llm-auth.json",
        path / "auth.json",
        path / "secrets" / ".env",
        path / "secrets" / "llm.env",
        path / "secrets" / "llm.json",
        path / "secrets" / "llm-auth.json",
        path / "secrets" / "auth.json",
    ]
    return [candidate for candidate in files if candidate.exists() and candidate.is_file()]


def _load_credentials_file(path: Path) -> dict[str, str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            payload = json.loads(raw)
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        out: dict[str, str] = {}
        for key, value in payload.items():
            text = str(value or "").strip()
            if text:
                out[str(key).strip()] = text
        return out
    return _parse_env_text(raw)


def _parse_env_text(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in str(raw or "").splitlines():
        row = line.strip()
        if not row or row.startswith("#"):
            continue
        if row.startswith("export "):
            row = row[7:].lstrip()
        if "=" not in row:
            continue
        key, value = row.split("=", 1)
        name = key.strip()
        if not name:
            continue
        text = value.strip()
        if text and len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
            text = text[1:-1]
        if text:
            out[name] = text
    return out
