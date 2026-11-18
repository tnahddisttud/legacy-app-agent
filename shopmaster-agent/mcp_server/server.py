"""The same 8 operations, served over MCP (Model Context Protocol).

Run by hand:   uv run -m mcp_server.server       (speaks MCP over stdin/stdout)
The agent starts it for you:   uv run run_agent.py --mcp

IMPORTANT: never print() in this process. stdout is the MCP wire; logs must go to stderr.
"""
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from shopmaster import operations as ops

mcp = FastMCP("shopmaster")

# Annotations tell MCP clients what a tool does. They are hints, not security: the real
# approval gate lives in the agent graph.
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True)

for func in ops.READ_OPERATIONS:
    mcp.tool(annotations=READ_ONLY)(func)
mcp.tool(annotations=WRITE)(ops.create_order)
mcp.tool(annotations=DESTRUCTIVE)(ops.update_order_status)  # can cancel an order


@mcp.resource("shop://order-status-codes")
def order_status_codes() -> str:
    """Legend for order statuses and the allowed transitions."""
    return ("NEW -> PAID -> SHIPPED -> DELIVERED\n"
            "NEW or PAID -> CANCELLED (puts stock back)\n"
            "HOLD is a legacy status that must not be used.")


if __name__ == "__main__":
    mcp.run()  # stdio transport
