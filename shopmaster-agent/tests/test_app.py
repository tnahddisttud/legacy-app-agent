"""Test the Streamlit chat UI (app.py) with Streamlit's own test runner, a scripted fake LLM and the fake shop.

No browser, no API key, no network. We check what the user would SEE: tables, the approval buttons, the answer.
"""
from pathlib import Path

import pytest
import streamlit as st
from langchain_core.messages import AIMessage
from streamlit.testing.v1 import AppTest

from tests.test_agent import ScriptedLLM, final_answer, tool_call

APP = str(Path(__file__).parent.parent / "app.py")
ORDER = {"customer_id": 7, "lines": [{"sku": "SKU-1001", "qty": 2}]}


@pytest.fixture
def open_app(client, monkeypatch):
    """Start the UI with a scripted LLM: `open_app(script)` returns the running AppTest."""
    def start(script):
        monkeypatch.setattr("agent.llm.get_llm", lambda: ScriptedLLM(script=script))
        st.cache_resource.clear()  # the UI builds its agent once and caches it; make sure it uses OUR llm
        at = AppTest.from_file(APP, default_timeout=30)
        at.run()
        assert not at.exception
        return at
    return start


def ask(at, text):
    at.chat_input[0].set_value(text).run()
    assert not at.exception
    return at


def press(at, label):
    next(b for b in at.button if label in b.label).click().run()
    assert not at.exception


def test_a_list_result_is_shown_as_a_table(open_app):
    at = open_app([tool_call("search_products", {}), final_answer("Found some items")])
    ask(at, "list products")
    assert len(at.dataframe) == 1                                  # the tool result became a table
    assert at.session_state.messages[-1]["answer"]["summary"] == "Found some items"
    assert at.session_state.pending is None and not at.error


def test_a_write_waits_for_approval_and_rejecting_does_nothing(open_app, shop):
    # After the rejection the "model" says nothing at all: the UI must still tell the user what happened.
    at = open_app([tool_call("create_order", ORDER), AIMessage(content="")])
    ask(at, "order it")
    assert at.session_state.pending is not None                    # paused
    assert at.chat_input[0].disabled                               # no new question while waiting
    assert shop.orders == []

    press(at, "Reject")
    turn = at.session_state.messages[-1]
    assert shop.orders == []                                       # never ran
    assert at.session_state.pending is None
    assert [s["name"] for s in turn["steps"]] == ["create_order"]  # shown once, not twice
    assert "did not perform" in turn["answer"]["summary"]
    assert any("REJECTED_BY_USER" in w.value for w in at.warning)  # the step shows a warning, not a red error
    assert not at.chat_input[0].disabled


def test_approving_runs_the_write(open_app, shop):
    at = open_app([tool_call("create_order", ORDER), final_answer("Order placed")])
    ask(at, "order it")
    press(at, "Approve")
    assert len(shop.orders) == 1
    assert at.session_state.messages[-1]["answer"]["summary"] == "Order placed"


def test_a_new_chat_clears_everything(open_app):
    at = open_app([tool_call("search_products", {}), final_answer("ok")])
    ask(at, "list products")
    press(at, "New chat")
    assert at.session_state.messages == [] and at.session_state.pending is None
