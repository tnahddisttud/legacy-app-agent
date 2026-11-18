"""Every tool returns the same small JSON shape, success or failure:

    {"ok": true,  "data": {...}}
    {"ok": false, "error": {"code": "...", "message": "...", "retryable": false, "hint": "..."}}

`safe` guarantees a tool NEVER raises: if anything goes wrong the LLM gets an error
message it can reason about, instead of the whole agent crashing.
"""
import functools
import inspect
import json

from .errors import ShopError


def ok(data) -> str:
    return json.dumps({"ok": True, "data": data}, default=str)


def fail(code: str, message: str, retryable: bool = False, hint: str | None = None) -> str:
    error = {"code": code, "message": message, "retryable": retryable}
    if hint:
        error["hint"] = hint
    return json.dumps({"ok": False, "error": error})


def safe(fn):
    """Decorator: run `fn` (which returns plain data or raises ShopError) and return a JSON string."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> str:
        try:
            return ok(fn(*args, **kwargs))
        except ShopError as e:
            return fail(e.code, e.message, e.retryable, e.hint)
        except Exception as e:  # last line of defence: never crash the agent
            return fail("UNEXPECTED", f"{type(e).__name__}: {e}")

    # The wrapper returns a JSON *string*; tell frameworks (LangChain, MCP) that.
    wrapper.__signature__ = inspect.signature(fn).replace(return_annotation=str)
    wrapper.__annotations__ = {**getattr(fn, "__annotations__", {}), "return": str}
    return wrapper
