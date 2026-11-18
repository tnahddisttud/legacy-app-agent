"""The agent: one call to LangChain's `create_agent`. No custom graph.

create_agent gives us the whole  model -> tools -> model ... loop. We add four things:
  1. a system prompt (with today's date),
  2. HumanInTheLoopMiddleware: write tools pause for a human to approve or reject,
  3. response_format: the final answer comes back as a structured `AgentAnswer`,
  4. ModelFallbackMiddleware (optional): if the main model's call fails, the same request goes to a backup model.
"""
from datetime import date
from pathlib import Path

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware, ModelFallbackMiddleware, dynamic_prompt
from langchain.agents.structured_output import ToolStrategy
from pydantic import BaseModel, Field

_PROMPT = (Path(__file__).parent.parent / "prompts" / "system.md").read_text(encoding="utf-8")


class AgentAnswer(BaseModel):
    """The structured final answer. Programs can read this; humans read `summary`."""
    summary: str = Field(description=(
        "The complete answer for the user, in plain language. It must contain the actual information asked for: "
        "when the user asks for a list (orders, products, customers...), write EVERY item on its own line with its "
        "key fields (e.g. 'ORD-000001 | customer 9 | 2023-12-17 | PAID | $1100.56'), never just say that you found them. "
        "Keep any intro or closing to one sentence."))
    actions_taken: list[str] = Field(
        default_factory=list,
        description="Write actions that were actually completed and confirmed by a tool (tool result ok=true), "
                    "e.g. 'Created order ORD-000041 for customer 7'. Empty if none.")
    warnings: list[str] = Field(
        default_factory=list,
        description="Data-quality problems or uncertainties the user should know about. Empty if none.")
    needs_follow_up: bool = Field(
        default=False,
        description="True if the user must answer a question or make a decision before the task can be finished.")


# ToolStrategy delivers the answer as a tool call named after the class; the UI and tests skip that "tool".
ANSWER_TOOL_NAME = AgentAnswer.__name__


@dynamic_prompt
def system_prompt(request) -> str:
    # Static text first, dynamic text (today's date) last: good for prompt caching.
    return f"{_PROMPT}\n\nToday's date: {date.today().isoformat()}"


def build_agent(tools, llm, write_tool_names: set[str], checkpointer=None, fallback_llm=None):
    """`tools` can be native LangChain tools OR tools loaded from an MCP server: the agent doesn't care.
    `fallback_llm` (optional) takes over for a model call when `llm` raises an error (rate limit, bad output...)."""
    approval_gate = HumanInTheLoopMiddleware(
        # Enforced in code, not in the prompt: a write tool can't run until a human approves it.
        interrupt_on={name: {"allowed_decisions": ["approve", "reject"]} for name in sorted(write_tool_names)},
        description_prefix="The agent wants to perform this action. Approve?",
    )
    return create_agent(
        model=llm,
        tools=tools,
        middleware=[system_prompt, approval_gate] + ([ModelFallbackMiddleware(fallback_llm)] if fallback_llm else []),
        # ToolStrategy = structured output via a tool call. Works with any model that supports tool calling.
        response_format=ToolStrategy(AgentAnswer),
        checkpointer=checkpointer,  # a checkpointer is required: the approval pause saves the state
        name="shopmaster-agent",
    )
