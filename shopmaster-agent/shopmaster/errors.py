"""One exception type for everything that can go wrong when calling ShopMaster.

The client RAISES ShopError. The tool layer CATCHES it and turns it into a small
JSON message the LLM can read (see envelope.py). Tools never crash the agent.
"""


class ShopError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False, hint: str | None = None):
        super().__init__(message)
        self.code = code            # short machine-readable code, e.g. "NOT_FOUND"
        self.message = message      # what happened, in plain English
        self.retryable = retryable  # would trying the same call again help?
        self.hint = hint            # what the LLM could do next
