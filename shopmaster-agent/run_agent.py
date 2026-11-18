"""Chat with the ShopMaster agent in your terminal.

    uv run run_agent.py          # tools are plain Python functions
    uv run run_agent.py --mcp    # the SAME tools, served by an MCP server (mcp_server/server.py)
"""
import argparse
import asyncio
import os
import sys
import uuid
from contextlib import AsyncExitStack

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from agent.agent import build_agent
from agent.llm import get_fallback_llm, get_llm
from shopmaster.envelope import fail
from shopmaster.operations import WRITE_TOOL_NAMES

AGENT_NAME = "shopmaster-agent"


async def load_tools(stack: AsyncExitStack, use_mcp: bool):
    if not use_mcp:
        from tools.shop import ALL_TOOLS
        return ALL_TOOLS

    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langchain_mcp_adapters.tools import load_mcp_tools

    # Start the MCP server as a child process and talk to it over stdin/stdout.
    # Pass the settings explicitly: child processes don't inherit the whole environment.
    keys = ("SHOPMASTER_BASE_URL", "SHOPMASTER_USER", "SHOPMASTER_PASS")
    client = MultiServerMCPClient({"shopmaster": {
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-m", "mcp_server.server"],
        "cwd": os.path.dirname(os.path.abspath(__file__)),
        "env": {k: os.environ[k] for k in keys if k in os.environ},
    }})
    # One long-lived session = one server process = one shop login, reused by every tool call.
    session = await stack.enter_async_context(client.session("shopmaster"))
    return await load_mcp_tools(session)


def ask_human(interrupt_value: dict) -> dict:
    """Show the paused write actions and return the human's decisions (one per action, in order)."""
    print("\n⚠️  APPROVAL NEEDED:")
    decisions = []
    for action in interrupt_value["action_requests"]:
        print(f"   • {action['name']}({action['args']})")
        if input("   Approve? [y/N] ").strip().lower() in ("y", "yes"):
            decisions.append({"type": "approve"})
        else:
            # The LLM sees this as the tool result, so it knows the action was NOT performed.
            decisions.append({"type": "reject", "message": fail(
                "REJECTED_BY_USER", "A human rejected this action. It was NOT performed.",
                hint="Do not retry. Tell the user it was not done and ask what they want instead.")})
    return {"decisions": decisions}


def show(result: dict):
    answer = result.get("structured_response")
    print(f"\nAgent> {answer.summary if answer else '(no answer)'}")
    if not answer:
        return
    for a in answer.actions_taken:
        print(f"   ✔ {a}")
    for w in answer.warnings:
        print(f"   ⚠ {w}")
    if answer.needs_follow_up:
        print("   ↳ (waiting for your reply)")


async def main(use_mcp: bool):
    load_dotenv()
    async with AsyncExitStack() as stack:
        tools = await load_tools(stack, use_mcp)
        saver = await stack.enter_async_context(AsyncSqliteSaver.from_conn_string("agent_state.db"))
        fallback = get_fallback_llm()
        agent = build_agent(tools, get_llm(), WRITE_TOOL_NAMES, checkpointer=saver, fallback_llm=fallback)

        thread_id = f"cli-{uuid.uuid4().hex[:8]}"
        config = {
            "run_name": f"{AGENT_NAME}-execution",
            "tags": [AGENT_NAME, "dev", "mcp" if use_mcp else "native"],
            "metadata": {"agent_name": AGENT_NAME, "agent_version": "v0.1.0", "user_id": "workshop-user",
                         "thread_id": thread_id, "task_type": "chat"},
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 25,  # hard stop for runaway tool loops
        }
        print(f"ShopMaster agent ready ({'MCP' if use_mcp else 'native'} tools, {len(tools)} loaded, "
              f"fallback: {fallback.model if fallback else 'none'}). Type 'quit' to exit.")
        while True:
            text = input("\nYou> ").strip()
            if text.lower() in ("quit", "exit", "q"):
                break
            if not text:
                continue
            try:
                result = await agent.ainvoke({"messages": [HumanMessage(text)]}, config)
                while result.get("__interrupt__"):            # the agent is paused, waiting for a human
                    decisions = ask_human(result["__interrupt__"][0].value)
                    result = await agent.ainvoke(Command(resume=decisions), config)
                show(result)
            except Exception as e:                            # keep the chat alive whatever happens
                print(f"\n❌ {type(e).__name__}: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mcp", action="store_true", help="load the tools from the MCP server instead")
    asyncio.run(main(parser.parse_args().mcp))
