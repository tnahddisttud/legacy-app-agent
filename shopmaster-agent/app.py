"""A chat UI for the ShopMaster agent.   Run it with:   uv run streamlit run app.py

The agent code is NOT changed: we call the same `build_agent(...)` as run_agent.py and just show what it does.
Streamlit re-runs this whole file on every click, so everything that must survive lives in `st.session_state`.
"""
import json
import uuid

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agent.agent import ANSWER_TOOL_NAME, build_agent
from agent.llm import get_fallback_llm, get_llm
from shopmaster.envelope import fail
from shopmaster.operations import WRITE_TOOL_NAMES
from tools.shop import ALL_TOOLS

EXAMPLES = [
    "Do you have wireless mice under $50?",
    "Is SKU-1004 in stock?",
    "Show me all the orders",
    "Order 2 of SKU-1001 for customer 3",
    "Cancel order ORD-000002",
]

st.set_page_config(page_title="ShopMaster Agent", page_icon="🛒")
load_dotenv()
ss = st.session_state


@st.cache_resource  # build the agent once, not on every re-run
def get_bot():
    return build_agent(ALL_TOOLS, get_llm(), WRITE_TOOL_NAMES, checkpointer=MemorySaver(), fallback_llm=get_fallback_llm())


try:
    bot = get_bot()
except Exception as e:  # most likely: GROQ_API_KEY missing from .env
    st.error(f"Could not start the agent: {type(e).__name__}: {e}\n\nCheck GROQ_API_KEY and LLM_MODEL in `.env`.")
    st.stop()


# ----------------------------------------------------------------------------- state
def new_chat():
    ss.messages = []        # what we draw: user messages and "turns" (tool steps + final answer)
    ss.pending = None       # set while the agent waits for a human to approve a write
    ss.thread_id = f"ui-{uuid.uuid4().hex[:8]}"   # a new thread = the agent forgets the old chat


if "messages" not in ss:
    new_chat()


# ----------------------------------------------------------------------------- drawing
def md(text: str) -> str:
    """Plain text -> safe markdown: `$` would start a math formula, and single newlines get swallowed."""
    return text.replace("$", r"\$").replace("\n", "  \n")


def rows_of(data):
    """If a tool result holds a list of records (orders, products...), return it so we can show a table."""
    if isinstance(data, list) and data and all(isinstance(r, dict) for r in data):
        return data
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list) and value and all(isinstance(r, dict) for r in value):
                return value
    return None


def render_step(step: dict):
    args = ", ".join(f"{k}={v!r}" for k, v in step["args"].items())
    st.markdown(f"🔧 **{step['name']}** `({args})`")
    result = step["result"]
    if result is None:
        st.caption("⏳ waiting…")
    elif not result.get("ok"):
        error = result.get("error", {})
        show = st.warning if error.get("code") == "REJECTED_BY_USER" else st.error
        show(f"{error.get('code', 'ERROR')}: {error.get('message', result)}")
    else:
        data = result["data"]
        rows = rows_of(data)
        if rows:
            # nested values (like order lines) are shown as JSON text so the table stays flat
            flat = [{k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in r.items()} for r in rows]
            st.dataframe(pd.DataFrame(flat), hide_index=True, width="stretch")
        else:
            st.json(data, expanded=False)


def render_turn(turn: dict, running: bool = False):
    """One agent reply: the tool steps it took (a collapsible box), then its final structured answer."""
    steps, answer = turn["steps"], turn["answer"]
    if steps:
        label = "Working…" if running else f"🔧 Used {len(steps)} tool call{'s' if len(steps) > 1 else ''}"
        with st.status(label, state="running" if running else "complete", expanded=answer is None):
            for step in steps:
                render_step(step)
    elif running:
        st.caption("Thinking…")
    if answer:
        st.markdown(md(answer["summary"]))
        for action in answer["actions_taken"]:
            st.success(action, icon="✅")
        for warning in answer["warnings"]:
            st.warning(warning)
        if answer["needs_follow_up"]:
            st.info("The agent is waiting for your reply.", icon="↩️")
        if turn.get("model"):
            st.caption(f"🤖 {turn['model']}")  # shows when the fallback model had to step in
    if turn["error"]:
        st.error(turn["error"])


# ----------------------------------------------------------------------------- talking to the agent
def parse_result(text) -> dict:
    """A tool result is JSON, but a rejection arrives as 'User rejected ... with reason: {json}', so try from the first '{'."""
    text = str(text)
    for start in (0, text.find("{")):
        if start >= 0:
            try:
                return json.loads(text[start:])
            except ValueError:
                pass
    return {"ok": False, "error": {"message": text}}


def absorb(turn: dict, update: dict):
    """Fold one streamed update from the agent into the turn we draw."""
    for message in update.get("messages", []):
        if isinstance(message, AIMessage):
            turn["model"] = (message.response_metadata or {}).get("model_name") or turn.get("model")  # who is speaking
            for call in message.tool_calls:
                already_shown = any(step["id"] == call["id"] for step in turn["steps"])  # the approval step repeats it
                if call["name"] != ANSWER_TOOL_NAME and not already_shown:  # that "tool" just delivers the final answer
                    turn["steps"].append({"id": call["id"], "name": call["name"], "args": call["args"], "result": None})
        elif isinstance(message, ToolMessage):
            for step in turn["steps"]:
                if step["id"] == message.tool_call_id:
                    step["result"] = parse_result(message.content)
    if update.get("structured_response") is not None:
        turn["answer"] = update["structured_response"].model_dump()


def finish(turn: dict):
    """Sometimes the model ends without calling the answer tool (e.g. right after a rejection). Say something anyway."""
    rejected = any(((s["result"] or {}).get("error") or {}).get("code") == "REJECTED_BY_USER" for s in turn["steps"])
    summary = "Okay, I did not perform that action." if rejected else "The agent stopped without an answer. Try asking again."
    turn["answer"] = {"summary": summary, "actions_taken": [], "warnings": [], "needs_follow_up": False}


def drive(payload, turn: dict, box):
    """Run the agent and redraw `box` after every step, so the user watches it work."""
    config = {"configurable": {"thread_id": ss.thread_id}, "recursion_limit": 25,
              "run_name": "shopmaster-agent-execution", "tags": ["shopmaster-agent", "streamlit"]}
    try:
        for chunk in bot.stream(payload, config, stream_mode="updates"):
            for node, update in chunk.items():
                if node == "__interrupt__":
                    ss.pending = update[0].value        # a write action: wait for the human
                elif update:
                    absorb(turn, update)
            with box.container():
                render_turn(turn, running=True)
        if turn["answer"] is None and not ss.pending:
            finish(turn)
    except Exception as e:                               # keep the app alive whatever happens
        turn["error"] = f"{type(e).__name__}: {e}"
    st.rerun()                                           # redraw the page from the saved state


# ----------------------------------------------------------------------------- the page
with st.sidebar:
    st.header("🛒 ShopMaster Agent")
    st.button("➕ New chat", on_click=new_chat, width="stretch")
    st.caption("Try one of these:")
    for example in EXAMPLES:
        st.button(example, on_click=lambda text=example: ss.update(queued=text), width="stretch")

st.title("🛒 ShopMaster Agent")

last_box = None
for message in ss.messages:                              # draw the whole conversation so far
    with st.chat_message(message["role"]):
        last_box = st.empty()
        with last_box.container():
            if message["role"] == "user":
                st.markdown(md(message["content"]))
            else:
                render_turn(message)

if ss.pending:                                           # the agent is paused until a human decides
    with st.container(border=True):
        st.warning("**Approval needed.** The agent wants to change data in the shop:")
        for action in ss.pending["action_requests"]:
            st.code(f"{action['name']}({json.dumps(action['args'], indent=2)})", language="python")
        approve_col, reject_col = st.columns(2)
        decision = None
        if approve_col.button("✅ Approve", type="primary", width="stretch"):
            decision = {"type": "approve"}
        if reject_col.button("❌ Reject", width="stretch"):
            decision = {"type": "reject", "message": fail(
                "REJECTED_BY_USER", "A human rejected this action. It was NOT performed.",
                hint="Do not retry. Tell the user it was not done and ask what they want instead.")}
        if decision:
            count = len(ss.pending["action_requests"])
            ss.pending = None
            drive(Command(resume={"decisions": [decision] * count}), ss.messages[-1], last_box)

prompt = st.chat_input("Ask about products, stock, customers or orders…", disabled=bool(ss.pending))
prompt = prompt or ss.pop("queued", None)                # a clicked example works like a typed question
if prompt and not ss.pending:
    turn = {"role": "assistant", "steps": [], "answer": None, "error": None}
    ss.messages += [{"role": "user", "content": prompt}, turn]
    with st.chat_message("user"):
        st.markdown(md(prompt))
    with st.chat_message("assistant"):
        box = st.empty()
    drive({"messages": [HumanMessage(prompt)]}, turn, box)
