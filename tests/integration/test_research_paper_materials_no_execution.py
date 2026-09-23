"""Static regression coverage for the non-executing 3C-2 production surface."""

import ast
from pathlib import Path

import pytest

_PAPER_MATERIALS_SURFACE = (
    "src/ai_agent_project/agent/research.py",
    "src/ai_agent_project/agent/research_application.py",
    "src/ai_agent_project/agent/research_file_store.py",
    "src/ai_agent_project/llm/providers/openai_research_paper_materials.py",
    "src/ai_agent_project/cli.py",
    "src/ai_agent_project/api/app.py",
)


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


@pytest.mark.parametrize("relative_path", _PAPER_MATERIALS_SURFACE)
def test_paper_materials_surface_has_no_execution_calls(relative_path: str) -> None:
    """Paper materials can call its LLM provider, never a workload executor."""
    source = Path(relative_path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=relative_path)
    prohibited = {
        "exec",
        "eval",
        "os.system",
        "subprocess.run",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
    }
    calls = {
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and (name := _call_name(node.func)) is not None
    }
    assert not calls & prohibited
