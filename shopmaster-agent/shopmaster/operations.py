"""The 8 operations the agent can perform. Each one becomes a TOOL.

* The type hints + Field(description=...) ARE the schema the LLM sees.
* The docstring is the description the LLM reads to decide WHEN to call the tool.
* `@safe` makes every function return a JSON string and never raise.

The same functions are used twice: as native LangChain tools (tools/shop.py)
and as an MCP server (mcp_server/server.py).
"""
import os
from typing import Annotated

from dotenv import load_dotenv
from pydantic import Field

from .client import ShopMasterClient
from .envelope import safe
from .errors import ShopError
from .models import OrderLineInput, OrderStatus
from .parsers import parse_category

# ------------------------------------------------------------------ shared client

_client: ShopMasterClient | None = None


def get_client() -> ShopMasterClient:
    """One client (and so one login session) shared by all tools."""
    global _client
    if _client is None:
        load_dotenv()
        _client = ShopMasterClient(
            base_url=os.getenv("SHOPMASTER_BASE_URL", "http://localhost:8080/legacy"),
            user=os.getenv("SHOPMASTER_USER", "svc_agent"),
            password=os.getenv("SHOPMASTER_PASS", "Winter2009!"),
        )
    return _client


def set_client(client: ShopMasterClient | None):
    """Used by tests to plug in a fake."""
    global _client
    _client = client


def _dump(model) -> dict:
    return model.model_dump(mode="json", exclude_none=True)


# ------------------------------------------------------------------ READ tools

@safe
def search_products(
    query: Annotated[str | None, Field(description="Words from the product name, e.g. 'mouse' or 'yoga'. Omit to browse.")] = None,
    category: Annotated[str | None, Field(description="One of: Electronics, Home & Garden, Tools, Sports, Toys, Kitchen, Office.")] = None,
    max_price: Annotated[float | None, Field(description="Only products priced at or below this amount in USD.")] = None,
    in_stock_only: Annotated[bool, Field(description="Only products flagged as in stock.")] = False,
    limit: Annotated[int, Field(ge=1, le=20, description="Maximum number of products to return.")] = 10,
):
    """Search the product catalogue by name, category and price. Use this FIRST whenever the user mentions a
    product, and to find a product's SKU or id. The in_stock field comes from an unreliable legacy flag:
    call check_stock before promising availability."""
    products = get_client().list_products(query)
    wanted_cat = parse_category(category) if category else None
    matches = [
        p for p in products
        if (wanted_cat is None or p.category == wanted_cat)
        and (max_price is None or (p.price is not None and p.price <= max_price))
        and (not in_stock_only or p.in_stock is True)
    ]
    return {"total_matches": len(matches), "showing": min(len(matches), limit),
            "products": [_dump(p) for p in matches[:limit]]}


@safe
def get_product(product_id: Annotated[int, Field(description="Numeric product id from search_products.")]):
    """Get full details of ONE product (description, weight, quantity on hand, discontinued flag)."""
    return _dump(get_client().get_product(product_id))


@safe
def check_stock(sku: Annotated[str, Field(description="Product SKU, e.g. 'SKU-1001'. Case does not matter.")]):
    """Check the real quantity in stock for a SKU. Use this before promising availability or creating an order."""
    rows = get_client().check_stock(sku)
    if not rows:
        raise ShopError("NOT_FOUND", f"No inventory record for {sku}.", hint="Use search_products to find the right SKU.")
    data = {"sku": rows[0].sku, "total_qty": sum(r.qty for r in rows), "rows": [_dump(r) for r in rows]}
    if len(rows) > 1:
        data["warning"] = (f"This SKU appears {len(rows)} times in inventory (a data-quality problem). "
                           "Report the rows and tell the user the figure is uncertain.")
    return data


@safe
def find_customer(
    email: Annotated[str | None, Field(description="Customer email address.")] = None,
    customer_id: Annotated[int | None, Field(description="Numeric customer id.")] = None,
):
    """Look up a customer by email or customer id. Provide at least one. Use this before creating an order to get
    the customer id and to check the account is active."""
    if not email and customer_id is None:
        raise ShopError("BAD_REQUEST", "Provide an email or a customer_id.")
    customers = get_client().find_customers(email=email, customer_id=customer_id)
    if not customers:
        raise ShopError("NOT_FOUND", "No matching customer.", hint="Ask the user to double-check the email or id.")
    return {"customers": [_dump(c) for c in customers]}


@safe
def list_orders(
    customer_id: Annotated[int | None, Field(description="Only orders of this customer.")] = None,
    status: Annotated[OrderStatus | None, Field(description="Only orders in this status.")] = None,
    limit: Annotated[int, Field(ge=1, le=50, description="Maximum number of orders to return.")] = 20,
):
    """List orders, newest last, optionally for one customer and/or status. Returns summaries without line items;
    use get_order for the full detail of one order."""
    code = None
    if status is not None:
        from .parsers import STATUS_CODES
        code = STATUS_CODES[OrderStatus(status).value]
    orders, total = get_client().list_orders(customer_id=customer_id, status_code=code, count=limit)
    return {"total": total, "showing": len(orders), "orders": [_dump(o) for o in orders]}


@safe
def get_order(order_no: Annotated[str, Field(description="Order number like 'ORD-000012'.")]):
    """Get the full detail of ONE order: status, total and line items."""
    return _dump(get_client().get_order(order_no))


# ------------------------------------------------------------------ WRITE tools (the agent asks a human first)

@safe
def create_order(
    customer_id: Annotated[int, Field(description="Customer id from find_customer. The customer must be active.")],
    lines: Annotated[list[OrderLineInput], Field(min_length=1, description="What to order: one entry per SKU.")],
):
    """WRITE: create a new order for a customer. Only call this after you have confirmed the customer (find_customer),
    resolved the exact SKUs (search_products) and checked stock (check_stock). A human approves it before it runs."""
    client = get_client()
    clean = [OrderLineInput.model_validate(l).model_dump() for l in lines]
    before = client.list_orders(customer_id=customer_id, count=1)[1]
    try:
        result = client.create_order(customer_id, clean)
    except ShopError as e:
        if e.code != "UNCERTAIN_RESULT":
            raise
        # The server crashed or timed out. Did the order get created anyway? Look at the order history.
        after = client.list_orders(customer_id=customer_id, count=1)[1]
        if after > before:
            newest = client.list_orders(customer_id=customer_id, start=after - 1, count=1)[0][0]
            return {"order_no": newest.order_no, "total": newest.total,
                    "note": "ShopMaster reported an error, but the order WAS created (found in order history). Do not create it again."}
        result = client.create_order(customer_id, clean)  # nothing was created, so one retry is safe
    return result


@safe
def update_order_status(
    order_no: Annotated[str, Field(description="Order number like 'ORD-000012'.")],
    new_status: Annotated[OrderStatus, Field(description="The status to move the order to.")],
):
    """WRITE: change an order's status (e.g. PAID -> SHIPPED, or cancel it). Cancelling puts stock back and cannot be
    undone. Allowed moves: NEW->PAID, PAID->SHIPPED, SHIPPED->DELIVERED, NEW/PAID->CANCELLED. A human approves it first."""
    get_client().update_order_status(order_no, OrderStatus(new_status).value)
    return {"order_no": order_no, "new_status": OrderStatus(new_status).value}


READ_OPERATIONS = [search_products, get_product, check_stock, find_customer, list_orders, get_order]
WRITE_OPERATIONS = [create_order, update_order_status]
ALL_OPERATIONS = READ_OPERATIONS + WRITE_OPERATIONS
WRITE_TOOL_NAMES = {f.__name__ for f in WRITE_OPERATIONS}
