"""Registration and lookup for agent tools."""

from ai_agent_project.tools.base import Tool, ToolDefinition


class ToolNotFoundError(LookupError):
    """Raised when a requested tool has not been registered."""


class ToolRegistry:
    """Store tools by their unique names."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool, replacing no existing tool."""
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")

        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        """Return a registered tool or raise a clear lookup error."""
        try:
            return self._tools[name]
        except KeyError as error:
            raise ToolNotFoundError(f"Tool not found: {name}") from error

    def definitions(self) -> list[ToolDefinition]:
        """Return tool metadata suitable for an LLM request."""
        return [tool.definition() for tool in self._tools.values()]
