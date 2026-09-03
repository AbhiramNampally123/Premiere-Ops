"""Errors that are safe to show at the terminal."""


class AgentError(Exception):
    """Base class for expected, user-actionable failures."""


class ConfigError(AgentError):
    """The environment does not contain a valid configuration."""


class DependencyError(AgentError):
    """An optional official SDK is not installed."""


class MCPError(AgentError):
    """The Grafana MCP connection or protocol failed."""


class ToolInvocationError(MCPError):
    """A read-only tool could not be called safely."""


class GeminiError(AgentError):
    """Gemini could not produce a response."""


class ToolLoopLimitError(GeminiError):
    """The model requested more tool rounds than the configured limit."""


class UnsupportedQuestionError(AgentError):
    """No supported read/query path is available for the question."""