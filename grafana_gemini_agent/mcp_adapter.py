"""A bounded, read-only adapter around the official Python MCP client."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import re
from dataclasses import dataclass
from typing import Any, Awaitable

from .config import AgentConfig
from .errors import DependencyError, MCPError, ToolInvocationError, UnsupportedQuestionError


_NAME_WORDS = re.compile(r"[^a-zA-Z0-9_]")
_MUTATION_WORDS = {
    "create",
    "delete",
    "destroy",
    "edit",
    "execute",
    "mutate",
    "patch",
    "remove",
    "set",
    "update",
    "write",
}
_READ_WORDS = {
    "alert",
    "dashboard",
    "datasource",
    "fetch",
    "get",
    "list",
    "loki",
    "metric",
    "metrics",
    "prometheus",
    "query",
    "read",
    "search",
}


@dataclass(frozen=True)
class ToolSpec:
    """The safe subset of an MCP tool exposed to Gemini."""

    name: str
    gemini_name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolObservation:
    tool_name: str
    serialized: str
    is_error: bool = False
    empty: bool = False
    truncated: bool = False


class GrafanaMcpAdapter:
    """Owns one MCP session and exposes only bounded read/query operations."""

    def __init__(self, config: AgentConfig, session: Any | None = None) -> None:
        self.config = config
        self._session = session
        self._stack: contextlib.AsyncExitStack | None = None
        self._connected = session is not None

    async def __aenter__(self) -> GrafanaMcpAdapter:
        if self._session is None:
            await self._open_session()
        await self._run("initialize", self._session.initialize())
        self._connected = True
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self._connected = False
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None

    async def _open_session(self) -> None:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:
            raise DependencyError(
                "The official MCP client is not installed. Install grafana_gemini_agent requirements."
            ) from exc

        self._stack = contextlib.AsyncExitStack()
        if self.config.mcp_transport == "stdio":
            params = StdioServerParameters(
                command=self.config.mcp_command or "",
                args=list(self.config.mcp_args),
            )
            read_stream, write_stream = await self._stack.enter_async_context(stdio_client(params))
        elif self.config.mcp_transport == "sse":
            try:
                from mcp.client.sse import sse_client
            except ImportError as exc:
                raise DependencyError(
                    "This MCP client does not include SSE transport; use streamable-http or upgrade mcp."
                ) from exc
            read_stream, write_stream = await self._stack.enter_async_context(
                sse_client(self.config.mcp_url or "", headers=self.config.mcp_headers)
            )
        else:
            try:
                from mcp.client.streamable_http import streamable_http_client
            except ImportError as exc:
                raise DependencyError(
                    "This MCP client does not include streamable HTTP; upgrade the mcp package."
                ) from exc
            transport_parameters = inspect.signature(streamable_http_client).parameters
            if "headers" in transport_parameters:
                transport = streamable_http_client(
                    self.config.mcp_url or "", headers=self.config.mcp_headers
                )
            elif "http_client" in transport_parameters:
                # Recent MCP clients take an httpx2 client instead of headers.
                # Register it with our exit stack so its credentials and sockets
                # are released with the MCP session.
                try:
                    import httpx2
                except ImportError as exc:
                    raise DependencyError(
                        "The installed MCP client needs its httpx2 transport dependency."
                    ) from exc
                http_client = httpx2.AsyncClient(
                    headers=self.config.mcp_headers,
                    timeout=self.config.mcp_timeout_seconds,
                )
                await self._stack.enter_async_context(http_client)
                transport = streamable_http_client(
                    self.config.mcp_url or "", http_client=http_client
                )
            else:
                raise DependencyError(
                    "The installed MCP client exposes an unsupported streamable HTTP API."
                )
            read_stream, write_stream, _ = await self._stack.enter_async_context(transport)

        self._session = ClientSession(read_stream, write_stream)
        await self._stack.enter_async_context(self._session)

    async def discover_tools(self) -> list[ToolSpec]:
        self._require_connected()
        try:
            result = await self._run("tool discovery", self._session.list_tools())
        except MCPError:
            raise
        raw_tools = getattr(result, "tools", None)
        if raw_tools is None and isinstance(result, dict):
            raw_tools = result.get("tools")
        if not isinstance(raw_tools, list):
            raise MCPError("Grafana MCP returned a malformed tool list; verify the server version.")

        tools: list[ToolSpec] = []
        used_names: set[str] = set()
        for raw in raw_tools:
            name = _field(raw, "name")
            if not isinstance(name, str) or not name.strip() or not is_read_only_tool(raw):
                continue
            schema = _field(raw, "inputSchema")
            if not isinstance(schema, dict):
                schema = {"type": "object", "properties": {}}
            gemini_name = _gemini_name(name, used_names)
            used_names.add(gemini_name)
            description = _field(raw, "description")
            tools.append(
                ToolSpec(
                    name=name,
                    gemini_name=gemini_name,
                    description=description.strip() if isinstance(description, str) else "",
                    input_schema=schema,
                )
            )
        if not tools:
            raise UnsupportedQuestionError(
                "The Grafana MCP server exposed no supported read/query tools. "
                "Check the server configuration and enabled Grafana tools."
            )
        return tools

    async def call_tool(self, tool: ToolSpec, arguments: dict[str, Any]) -> ToolObservation:
        self._require_connected()
        if not is_read_only_tool({"name": tool.name, "description": tool.description}):
            raise ToolInvocationError(f"Tool {tool.name} is not an approved read/query tool.")
        if not isinstance(arguments, dict):
            raise ToolInvocationError(
                f"Invalid arguments for read tool {tool.name}: expected a JSON object."
            )
        try:
            result = await self._run(
                f"read tool {tool.name}",
                self._session.call_tool(tool.name, arguments),
            )
        except MCPError:
            raise
        return normalize_result(tool.name, result, self.config.max_response_bytes)

    async def _run(self, operation: str, awaitable: Awaitable[Any]) -> Any:
        try:
            return await asyncio.wait_for(awaitable, timeout=self.config.mcp_timeout_seconds)
        except asyncio.TimeoutError:
            raise MCPError(
                f"Grafana MCP {operation} timed out after {self.config.mcp_timeout_seconds:g}s. "
                "Check connectivity or increase the MCP timeout."
            ) from None
        except MCPError:
            raise
        except Exception as exc:
            raise MCPError(
                f"Grafana MCP {operation} failed ({type(exc).__name__}). "
                "Verify the endpoint, authentication, and server logs."
            ) from exc

    def _require_connected(self) -> None:
        if not self._connected or self._session is None:
            raise MCPError("Grafana MCP session is not connected.")


def is_read_only_tool(tool: Any) -> bool:
    name = _field(tool, "name")
    description = _field(tool, "description")
    searchable = " ".join(item for item in (name, description) if isinstance(item, str))
    tokens = set(
        re.sub(
            r"([a-z0-9])([A-Z])",
            r"\1_\2",
            re.sub(r"[^a-zA-Z0-9]+", "_", searchable),
        ).lower().split("_")
    )
    if tokens & _MUTATION_WORDS:
        return False
    return bool(tokens & _READ_WORDS)


def normalize_result(tool_name: str, result: Any, max_bytes: int) -> ToolObservation:
    is_error = bool(_field(result, "isError") or _field(result, "is_error"))
    content = _field(result, "content")
    structured = _field(result, "structuredContent")
    if structured is None:
        structured = _field(result, "structured_content")
    payload: dict[str, Any] = {"is_error": is_error}
    if content is not None:
        payload["content"] = _json_safe(content)
    if structured is not None:
        payload["structured_content"] = _json_safe(structured)
    empty = content in (None, [], "") and structured in (None, {}, [], "")
    if empty:
        payload["empty"] = True

    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    encoded = serialized.encode("utf-8")
    truncated = len(encoded) > max_bytes
    if truncated:
        preview_budget = max(1, max_bytes - 80)
        preview = encoded[:preview_budget].decode("utf-8", errors="ignore")
        serialized = json.dumps(
            {
                "is_error": is_error,
                "_truncated": True,
                "preview": preview,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return ToolObservation(
        tool_name=tool_name,
        serialized=serialized,
        is_error=is_error,
        empty=empty,
        truncated=truncated,
    )


def _field(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump())
    if hasattr(value, "__dict__"):
        return _json_safe(vars(value))
    return str(value)


def _gemini_name(name: str, used: set[str]) -> str:
    candidate = _NAME_WORDS.sub("_", name).strip("_") or "grafana_read"
    if candidate[0].isdigit():
        candidate = f"tool_{candidate}"
    candidate = candidate[:60]
    base = candidate
    suffix = 2
    while candidate in used:
        candidate = f"{base[:56]}_{suffix}"
        suffix += 1
    return candidate