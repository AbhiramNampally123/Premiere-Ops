from __future__ import annotations

import asyncio
import unittest

from grafana_gemini_agent.config import AgentConfig
from grafana_gemini_agent.errors import (
    ConfigError,
    GeminiError,
    MCPError,
    ToolInvocationError,
    ToolLoopLimitError,
    UnsupportedQuestionError,
)
from grafana_gemini_agent.gemini_agent import GeminiReasoningAgent
from grafana_gemini_agent.mcp_adapter import GrafanaMcpAdapter, normalize_result


def config_env(**overrides: str) -> dict[str, str]:
    env = {
        "GEMINI_API_KEY": "test-only-key",
        "GRAFANA_MCP_TRANSPORT": "streamable-http",
        "GRAFANA_MCP_URL": "https://grafana.example.test/mcp",
    }
    env.update(overrides)
    return env


class FakeMcpSession:
    def __init__(self, tools: list[dict]) -> None:
        self.tools = tools
        self.calls: list[tuple[str, dict]] = []

    async def initialize(self) -> None:
        return None

    async def list_tools(self) -> dict:
        return {"tools": self.tools}

    async def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        return {"content": [{"type": "text", "text": "observed value: 42"}]}


class FakeResponse:
    def __init__(self, text: str = "", function_calls: list | None = None) -> None:
        self.text = text
        self.function_calls = function_calls or []
        self.candidates = []


class FakeGemini:
    def __init__(self) -> None:
        self.requests: list[dict] = []

        class Models:
            def __init__(inner_self, outer: FakeGemini) -> None:
                inner_self.outer = outer

            def generate_content(inner_self, **kwargs):
                inner_self.outer.requests.append(kwargs)
                if len(inner_self.outer.requests) == 1:
                    return FakeResponse(function_calls=[{"name": "query_prometheus", "args": {"q": "up"}}])
                return FakeResponse(
                    "Observed value: 42. The result supports the query, but no time range was provided."
                )

        self.models = Models(self)


class AgentTests(unittest.TestCase):
    def test_configuration_requires_matching_transport_settings(self) -> None:
        with self.assertRaisesRegex(ConfigError, "GRAFANA_MCP_URL"):
            AgentConfig.from_env({"GEMINI_API_KEY": "secret", "GRAFANA_MCP_TRANSPORT": "sse"})
        with self.assertRaisesRegex(ConfigError, "GRAFANA_MCP_COMMAND"):
            AgentConfig.from_env({"GEMINI_API_KEY": "secret", "GRAFANA_MCP_TRANSPORT": "stdio"})

    def test_configuration_does_not_echo_api_key(self) -> None:
        with self.assertRaises(ConfigError) as context:
            AgentConfig.from_env(
                config_env(GRAFANA_MAX_TOOL_ROUNDS="not-a-number", GEMINI_API_KEY="do-not-print")
            )
        self.assertNotIn("do-not-print", str(context.exception))

    def test_discovery_filters_mutations_and_calls_read_tool(self) -> None:
        session = FakeMcpSession(
            [
                {"name": "query_prometheus", "description": "Read Prometheus metrics", "inputSchema": {}},
                {"name": "delete_dashboard", "description": "Delete a dashboard", "inputSchema": {}},
                {"name": "execute_command", "description": "Execute arbitrary action", "inputSchema": {}},
            ]
        )
        config = AgentConfig.from_env(config_env())

        async def exercise():
            adapter = GrafanaMcpAdapter(config, session=session)
            async with adapter:
                tools = await adapter.discover_tools()
                observation = await adapter.call_tool(tools[0], {"q": "up"})
            return tools, observation

        tools, observation = asyncio.run(exercise())
        self.assertEqual([tool.name for tool in tools], ["query_prometheus"])
        self.assertEqual(session.calls, [("query_prometheus", {"q": "up"})])
        self.assertIn("observed value: 42", observation.serialized)

    def test_camel_case_mutation_is_not_exposed(self) -> None:
        session = FakeMcpSession(
            [{"name": "getOrCreateDashboard", "description": "Get or create a dashboard"}]
        )
        config = AgentConfig.from_env(config_env())

        async def exercise():
            async with GrafanaMcpAdapter(config, session=session) as adapter:
                await adapter.discover_tools()

        with self.assertRaises(UnsupportedQuestionError):
            asyncio.run(exercise())

    def test_no_read_tools_is_actionable(self) -> None:
        session = FakeMcpSession([{"name": "update_dashboard", "description": "Update dashboards"}])
        config = AgentConfig.from_env(config_env())

        async def exercise():
            async with GrafanaMcpAdapter(config, session=session) as adapter:
                await adapter.discover_tools()

        with self.assertRaises(UnsupportedQuestionError):
            asyncio.run(exercise())

    def test_malformed_mcp_tool_list_is_rejected(self) -> None:
        class MalformedSession(FakeMcpSession):
            async def list_tools(self):
                return {"tools": {"not": "a list"}}

        config = AgentConfig.from_env(config_env())

        async def exercise():
            async with GrafanaMcpAdapter(config, session=MalformedSession([])) as adapter:
                await adapter.discover_tools()

        with self.assertRaisesRegex(MCPError, "malformed tool list"):
            asyncio.run(exercise())

    def test_mcp_timeout_is_actionable(self) -> None:
        class SlowSession(FakeMcpSession):
            async def list_tools(self):
                await asyncio.sleep(2)
                return {"tools": []}

        config = AgentConfig.from_env(config_env(GRAFANA_MCP_TIMEOUT_SECONDS="1"))

        async def exercise():
            async with GrafanaMcpAdapter(config, session=SlowSession([])) as adapter:
                await adapter.discover_tools()

        with self.assertRaisesRegex(MCPError, "timed out"):
            asyncio.run(exercise())

    def test_direct_mutation_call_is_rejected(self) -> None:
        session = FakeMcpSession([])
        config = AgentConfig.from_env(config_env())

        async def exercise():
            async with GrafanaMcpAdapter(config, session=session) as adapter:
                from grafana_gemini_agent.mcp_adapter import ToolSpec

                await adapter.call_tool(
                    ToolSpec("update_dashboard", "update_dashboard", "Update dashboard", {}),
                    {},
                )

        with self.assertRaises(ToolInvocationError):
            asyncio.run(exercise())

    def test_gemini_can_request_a_follow_up_read(self) -> None:
        session = FakeMcpSession(
            [{"name": "query_prometheus", "description": "Query Prometheus metrics", "inputSchema": {}}]
        )
        config = AgentConfig.from_env(config_env())
        gemini = FakeGemini()

        async def exercise():
            async with GrafanaMcpAdapter(config, session=session) as adapter:
                return await GeminiReasoningAgent(config, adapter, client=gemini).answer(
                    "What is the current value?"
                )

        answer = asyncio.run(exercise())
        self.assertIn("Observed value: 42", answer.text)
        self.assertEqual(answer.tools_used, ("query_prometheus",))
        self.assertEqual(len(gemini.requests), 2)
        self.assertEqual(session.calls[0][0], "query_prometheus")

    def test_tool_loop_limit_is_enforced(self) -> None:
        session = FakeMcpSession(
            [{"name": "query_prometheus", "description": "Query Prometheus metrics", "inputSchema": {}}]
        )
        config = AgentConfig.from_env(config_env(GRAFANA_MAX_TOOL_ROUNDS="1"))

        class AlwaysTool(FakeGemini):
            def __init__(self):
                super().__init__()
                self.models.generate_content = lambda **kwargs: FakeResponse(
                    function_calls=[{"name": "query_prometheus", "args": {}}]
                )

        async def exercise():
            async with GrafanaMcpAdapter(config, session=session) as adapter:
                await GeminiReasoningAgent(config, adapter, client=AlwaysTool()).answer("query")

        with self.assertRaises(ToolLoopLimitError):
            asyncio.run(exercise())

    def test_gemini_failure_does_not_echo_credential(self) -> None:
        session = FakeMcpSession(
            [{"name": "query_prometheus", "description": "Query Prometheus metrics", "inputSchema": {}}]
        )
        config = AgentConfig.from_env(config_env(GEMINI_API_KEY="do-not-echo"))

        class BrokenGemini:
            class Models:
                def generate_content(self, **kwargs):
                    raise RuntimeError("provider rejected request")

            models = Models()

        async def exercise():
            async with GrafanaMcpAdapter(config, session=session) as adapter:
                await GeminiReasoningAgent(config, adapter, client=BrokenGemini()).answer("query")

        with self.assertRaises(GeminiError) as context:
            asyncio.run(exercise())
        self.assertNotIn("do-not-echo", str(context.exception))

    def test_malformed_result_is_bounded_and_marked(self) -> None:
        result = normalize_result("query_prometheus", {"content": [{"text": "x" * 1000}]}, 100)
        self.assertTrue(result.truncated)
        self.assertIn("_truncated", result.serialized)


if __name__ == "__main__":
    unittest.main()