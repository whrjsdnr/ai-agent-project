"""Agent tool adapter for the project's calculator functions."""

from typing import Literal

from pydantic import BaseModel

from ai_agent_project import calculator
from ai_agent_project.agent.execution_observation import observe_tool
from ai_agent_project.tools.base import ToolDefinition, ToolResult

Number = int | float


class CalculatorInput(BaseModel):
    """Validated input for a calculator operation."""

    operation: Literal["add", "subtract", "multiply", "divide"]
    a: Number
    b: Number


class CalculatorTool:
    """Expose the existing calculator module as a single agent tool."""

    name = "calculator"
    description = "Perform addition, subtraction, multiplication, or division."
    input_schema = CalculatorInput

    @observe_tool("calculator")
    def execute(self, arguments: dict[str, object]) -> ToolResult:
        """Run one validated calculator operation."""
        try:
            values = self.input_schema.model_validate(arguments)
            operation = getattr(calculator, values.operation)
            result = operation(values.a, values.b)
        except (TypeError, ValueError, ZeroDivisionError) as error:
            return ToolResult(success=False, error=str(error))

        return ToolResult(success=True, data={"result": result})

    def definition(self) -> ToolDefinition:
        """Return the calculator metadata exposed to an LLM."""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema.model_json_schema(),
        )
