"""The tool layer: JSON envelopes, schemas, and the duplicate-order safety net."""
import asyncio
import json

import httpx

from shopmaster import operations as ops
from shopmaster.client import ShopMasterClient
from tools.shop import ALL_TOOLS


def call(fn, **kwargs):
    return json.loads(fn(**kwargs))


def test_search_cleans_and_filters(client):
    out = call(ops.search_products, category="home garden", max_price=6)
    assert out["ok"] and out["data"]["total_matches"] == 15          # the 15 even-numbered items cost $5.50
    assert all(p["price"] == 5.5 and p["category"] == "Home & Garden" for p in out["data"]["products"])
    assert out["data"]["showing"] == 10                               # default limit


def test_check_stock_ok_and_not_found(client):
    assert call(ops.check_stock, sku="sku-1001")["data"]["total_qty"] == 5
    err = call(ops.check_stock, sku="SKU-NOPE")
    assert err["ok"] is False and err["error"]["code"] == "NOT_FOUND" and "hint" in err["error"]


def test_duplicate_sku_gets_a_warning(client):
    data = call(ops.check_stock, sku="SKU-1004")["data"]
    assert data["total_qty"] == 12 and "warning" in data


def test_tools_never_raise_even_when_server_is_down():
    def boom(request):
        raise httpx.ConnectError("refused")
    ops.set_client(ShopMasterClient(transport=httpx.MockTransport(boom), sleep=lambda s: None))
    try:
        out = call(ops.get_order, order_no="ORD-000001")
        assert out["ok"] is False and out["error"]["code"] == "NETWORK" and out["error"]["retryable"]
    finally:
        ops.set_client(None)


def test_create_order_happy_path_and_out_of_stock(client, shop):
    ok = call(ops.create_order, customer_id=7, lines=[{"sku": "SKU-1001", "qty": 2}])
    assert ok["ok"] and ok["data"]["order_no"] == "ORD-000001"
    short = call(ops.create_order, customer_id=7, lines=[{"sku": "SKU-1001", "qty": 50}])
    assert short["error"]["code"] == "OUT_OF_STOCK"
    unknown = call(ops.create_order, customer_id=7, lines=[{"sku": "SKU-ZZZ", "qty": 1}])
    assert unknown["error"]["code"] == "ORDER_REJECTED" and "search_products" in unknown["error"]["hint"]


def test_server_crash_AFTER_commit_does_not_create_a_duplicate_order(client, shop):
    shop.post_commit_500 = True                      # order saved, then the server answers 500
    out = call(ops.create_order, customer_id=7, lines=[{"sku": "SKU-1001", "qty": 1}])
    assert out["ok"] and out["data"]["order_no"] == "ORD-000001" and "WAS created" in out["data"]["note"]
    assert len(shop.orders) == 1                     # exactly one order, even though the call "failed"


def test_server_crash_BEFORE_commit_is_retried_once(client, shop):
    call(ops.check_stock, sku="SKU-1001")            # log in first
    shop.script.append(("POST", httpx.Response(500, text="<html>Tomcat</html>")))   # nothing saved
    out = call(ops.create_order, customer_id=7, lines=[{"sku": "SKU-1001", "qty": 1}])
    assert out["ok"] and len(shop.orders) == 1       # one retry, one order


def test_bad_enum_is_rejected_by_the_schema_not_the_api(client):
    tool = next(t for t in ALL_TOOLS if t.name == "update_order_status")
    try:
        tool.invoke({"order_no": "ORD-000001", "new_status": "TELEPORTED"})
        assert False, "should have been rejected"
    except Exception as e:                           # LangChain's ToolNode turns this into a message for the LLM
        assert "new_status" in str(e)


def test_schemas_describe_everything_the_llm_needs():
    by_name = {t.name: t for t in ALL_TOOLS}
    assert set(by_name) == {"search_products", "get_product", "check_stock", "find_customer", "list_orders",
                            "get_order", "create_order", "update_order_status"}
    schema = by_name["create_order"].args_schema.model_json_schema()
    qty = schema["$defs"]["OrderLineInput"]["properties"]["qty"]
    assert qty["minimum"] == 1 and qty["maximum"] == 99 and qty["description"]
    assert set(schema["$defs"]["OrderStatus"]["enum"] if "OrderStatus" in schema["$defs"] else ["NEW"]) >= {"NEW"}
    assert all(t.description for t in ALL_TOOLS)
    assert "enum" in json.dumps(by_name["update_order_status"].args_schema.model_json_schema())


def test_mcp_server_exposes_same_tools_with_annotations():
    from mcp_server.server import mcp
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    assert set(tools) == {t.name for t in ALL_TOOLS}
    assert tools["check_stock"].annotations.readOnlyHint is True
    assert tools["create_order"].annotations.readOnlyHint is False
    assert tools["update_order_status"].annotations.destructiveHint is True
    assert tools["create_order"].inputSchema["properties"]["lines"]["minItems"] == 1
