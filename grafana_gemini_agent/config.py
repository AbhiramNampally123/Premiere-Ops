"""Environment-backed configuration with validation and bounded limits."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import urlparse

from .errors import ConfigError


_TRANSPORTS = {"streamable-http", "sse", "stdio"}


@dataclass(frozen=True)
class AgentConfig:
    gemini_api_key: str = field(repr=False)
    gemini_model: str
    mcp_transport: str
    mcp_url: str | None
    mcp_command: str | None
    mcp_args: tuple[str, ...]
    mcp_headers: dict[str, str] = field(repr=False)
    mcp_env: dict[str, str] = field(repr=False)
    mcp_timeout_seconds: float
    gemini_timeout_seconds: float
    max_tool_rounds: int
    max_response_bytes: int

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AgentConfig:
        values = os.environ if env is None else env
        api_key = values.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise ConfigError("GEMINI_API_KEY is required; set it in the environment.")

        transport = values.get("GRAFANA_MCP_TRANSPORT", "streamable-http").strip().lower()
        if transport == "streamable_http":
            transport = "streamable-http"
        if transport not in _TRANSPORTS:
            choices = ", ".join(sorted(_TRANSPORTS))
            raise ConfigError(f"GRAFANA_MCP_TRANSPORT must be one of: {choices}.")

        url = values.get("GRAFANA_MCP_URL", "").strip() or None
        command = values.get("GRAFANA_MCP_COMMAND", "").strip() or None
        if transport in {"streamable-http", "sse"}:
            if not url:
                raise ConfigError(
                    f"GRAFANA_MCP_URL is required when transport is {transport}."
                )
            _validate_url(url)
            command = None
        elif not command:
            raise ConfigError("GRAFANA_MCP_COMMAND is required when transport is stdio.")
        else:
            url = None

        args = _parse_string_list(values.get("GRAFANA_MCP_ARGS_JSON", "[]"), "GRAFANA_MCP_ARGS_JSON")
        headers = _parse_headers(values.get("GRAFANA_MCP_HEADERS_JSON", "{}"))
        grafana_token = values.get("GRAFANA_TOKEN", "").strip()
        if grafana_token and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {grafana_token}"
        mcp_env = dict(values) if transport == "stdio" else {}
        if transport == "stdio" and grafana_token:
            mcp_env["GRAFANA_SERVICE_ACCOUNT_TOKEN"] = grafana_token

        return cls(
            gemini_api_key=api_key,
            gemini_model=_get_string(values, "GEMINI_MODEL", "gemini-3.6-flash"),
            mcp_transport=transport,
            mcp_url=url,
            mcp_command=command,
            mcp_args=tuple(args),
            mcp_headers=headers,
            mcp_env=mcp_env,
            mcp_timeout_seconds=_get_float(
                values, "GRAFANA_MCP_TIMEOUT_SECONDS", 20.0, minimum=1.0, maximum=120.0
            ),
            gemini_timeout_seconds=_get_float(
                values, "GEMINI_TIMEOUT_SECONDS", 45.0, minimum=1.0, maximum=180.0
            ),
            max_tool_rounds=_get_int(
                values, "GRAFANA_MAX_TOOL_ROUNDS", 4, minimum=1, maximum=8
            ),
            max_response_bytes=_get_int(
                values, "GRAFANA_MAX_RESPONSE_BYTES", 100_000, minimum=1_024, maximum=2_000_000
            ),
        )


def _get_string(env: Mapping[str, str], key: str, default: str) -> str:
    value = env.get(key, default).strip()
    if not value:
        raise ConfigError(f"{key} cannot be empty.")
    return value


def _get_float(
    env: Mapping[str, str],
    key: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    raw = env.get(key, str(default))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ConfigError(f"{key} must be a number between {minimum:g} and {maximum:g}.") from None
    if not minimum <= value <= maximum:
        raise ConfigError(f"{key} must be between {minimum:g} and {maximum:g}.")
    return value


def _get_int(
    env: Mapping[str, str],
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = env.get(key, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ConfigError(f"{key} must be an integer between {minimum} and {maximum}.") from None
    if not minimum <= value <= maximum:
        raise ConfigError(f"{key} must be between {minimum} and {maximum}.")
    return value


def _parse_string_list(raw: str, key: str) -> list[str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise ConfigError(f"{key} must be a JSON array of strings.") from None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{key} must be a JSON array of strings.")
    return value


def _parse_headers(raw: str) -> dict[str, str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise ConfigError("GRAFANA_MCP_HEADERS_JSON must be a JSON object of strings.") from None
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise ConfigError("GRAFANA_MCP_HEADERS_JSON must be a JSON object of strings.")
    if any("\r" in item or "\n" in item for item in value.values()):
        raise ConfigError("GRAFANA_MCP_HEADERS_JSON contains an invalid header value.")
    return dict(value)


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError("GRAFANA_MCP_URL must be an http(s) URL.")
    if parsed.username or parsed.password:
        raise ConfigError("GRAFANA_MCP_URL must not contain credentials; use headers instead.")