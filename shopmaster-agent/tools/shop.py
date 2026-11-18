"""Native LangChain tools. Each operation in shopmaster/operations.py becomes one tool.

The tool's name comes from the function name, its description from the docstring, and the
argument schema from the type hints. Run `uv run show_tool_schemas.py` to see exactly what
the LLM receives.
"""
from langchain_core.tools import StructuredTool

from shopmaster.operations import ALL_OPERATIONS, WRITE_TOOL_NAMES

ALL_TOOLS = [StructuredTool.from_function(func) for func in ALL_OPERATIONS]

__all__ = ["ALL_TOOLS", "WRITE_TOOL_NAMES"]
