"""Test the agent with a scripted fake LLM: no API key, no network.

The fake LLM says exactly what we tell it to. We are testing the AGENT (tool loop, approval gate,
error handling), not the model's intelligence.
"""
import asyncio

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agent.agent import ANSWER_TOOL_NAME, build_agent
from tools.shop import ALL_TOOLS, WRITE_TOOL_NAMES


class ScriptedLLM(BaseChatModel):
    script: list
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        reply = self.script[self.calls]
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=reply)])

    def bind_tools(self, tools, **kwargs):
        return self


def tool_call(name, args, id="call_1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": id}])


def final_answer(summary="done"):
    """The scripted LLM's last step: the structured answer (create_agent exposes it as a tool, see ANSWER_TOOL_NAME)."""
    return tool_call(ANSWER_TOOL_NAME, {"summary": summary}, id="call_final")


def approve():
    return Command(resume={"decisions": [{"type": "approve"}]})


def reject():
    return Command(resume={"decisions": [{"type": "reject", "message": '{"ok": false, "error": {"code": "REJECTED_BY_USER"}}'}]})


class BrokenLLM(ScriptedLLM):
    """A main model that always fails, like Groq answering 429 (rate limit) or 400 (botched tool call)."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        raise RuntimeError("Error code: 429 - rate limit reached")


def run(llm, first_input, config_id="t1", fallback_llm=None):
    agent = build_agent(ALL_TOOLS, llm, WRITE_TOOL_NAMES, checkpointer=MemorySaver(), fallback_llm=fallback_llm)
    config = {"configurable": {"thread_id": config_id}}
    result = asyncio.run(agent.ainvoke({"messages": [HumanMessage(first_input)]}, config))
    return agent, config, result


def tool_messages(result):
    return [m for m in result["messages"] if isinstance(m, ToolMessage) and m.name != ANSWER_TOOL_NAME]


def test_read_tool_runs_without_asking_a_human(client):
    llm = ScriptedLLM(script=[tool_call("check_stock", {"sku": "SKU-1001"}), final_answer()])
    _, _, result = run(llm, "stock of SKU-1001?")
    assert "__interrupt__" not in result
    assert '"total_qty": 5' in tool_messages(result)[0].content
    assert result["structured_response"].summary == "done"


def test_write_tool_pauses_for_approval_and_nothing_happens_yet(client, shop):
    order = {"customer_id": 7, "lines": [{"sku": "SKU-1001", "qty": 2}]}
    llm = ScriptedLLM(script=[tool_call("create_order", order), final_answer()])
    agent, config, result = run(llm, "order 2 of SKU-1001 for customer 7")
    interrupt = result["__interrupt__"][0].value
    assert interrupt["action_requests"][0]["name"] == "create_order"
    assert shop.orders == []                                   # PAUSED: no order exists yet
    assert shop.count("POST", "/orders.do") == 0


def test_approving_runs_the_write(client, shop):
    order = {"customer_id": 7, "lines": [{"sku": "SKU-1001", "qty": 2}]}
    llm = ScriptedLLM(script=[tool_call("create_order", order), final_answer()])
    agent, config, _ = run(llm, "order it")
    result = asyncio.run(agent.ainvoke(approve(), config))
    assert len(shop.orders) == 1 and shop.orders[0]["no"] == "ORD-000001"
    assert '"ok": true' in tool_messages(result)[0].content
    assert result["structured_response"] is not None


def test_rejecting_does_not_run_the_write_and_llm_is_told(client, shop):
    order = {"customer_id": 7, "lines": [{"sku": "SKU-1001", "qty": 2}]}
    llm = ScriptedLLM(script=[tool_call("create_order", order), final_answer()])
    agent, config, _ = run(llm, "order it")
    result = asyncio.run(agent.ainvoke(reject(), config))
    assert shop.orders == [] and shop.count("POST", "/orders.do") == 0
    assert "REJECTED_BY_USER" in tool_messages(result)[0].content


def test_tool_errors_flow_back_to_the_llm_instead_of_crashing(client):
    llm = ScriptedLLM(script=[tool_call("check_stock", {"sku": "SKU-NOPE"}), final_answer()])
    _, _, result = run(llm, "stock of SKU-NOPE?")
    assert '"code": "NOT_FOUND"' in tool_messages(result)[0].content
    assert result["structured_response"].summary == "done"


def test_the_fallback_model_takes_over_when_the_main_model_fails(client):
    main = BrokenLLM(script=[])
    backup = ScriptedLLM(script=[tool_call("check_stock", {"sku": "SKU-1001"}), final_answer("backup answered")])
    _, _, result = run(main, "stock of SKU-1001?", fallback_llm=backup)
    assert main.calls > 0 and backup.calls == 2                # the backup did the whole job
    assert '"total_qty": 5' in tool_messages(result)[0].content
    assert result["structured_response"].summary == "backup answered"


def test_the_fallback_is_not_used_while_the_main_model_works(client):
    main = ScriptedLLM(script=[final_answer("main answered")])
    backup = ScriptedLLM(script=[final_answer("backup answered")])
    _, _, result = run(main, "hi", fallback_llm=backup)
    assert backup.calls == 0
    assert result["structured_response"].summary == "main answered"


def test_without_a_fallback_the_error_still_surfaces(client):
    with pytest.raises(RuntimeError, match="429"):
        run(BrokenLLM(script=[]), "hi")
