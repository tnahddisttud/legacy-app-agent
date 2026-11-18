"""Optional: talks to the REAL Java app. Skipped automatically when it isn't running.

    (in legacy-shop/)  docker compose up --build
    pytest tests/test_live_api.py -v
"""
import json

import httpx
import pytest

from shopmaster import operations as ops
from shopmaster.client import ShopMasterClient

BASE = "http://localhost:8080/legacy"


def shop_is_up() -> bool:
    try:
        return httpx.get(f"{BASE}/ping.do", timeout=2).text.strip() == "PONG"
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not shop_is_up(), reason="ShopMaster is not running on localhost:8080")


@pytest.fixture
def live():
    c = ShopMasterClient(base_url=BASE)
    ops.set_client(c)
    yield c
    ops.set_client(None)


def test_catalogue_is_complete_despite_the_page_cap(live):
    assert len(live.list_products()) == 60


def test_product_detail_and_stock(live):
    p = live.get_product(1)
    assert p.sku.startswith("SKU-") and p.name
    assert json.loads(ops.check_stock(sku=p.sku))["ok"]


def test_duplicate_sku_warning(live):
    assert "warning" in json.loads(ops.check_stock(sku="SKU-1004"))["data"]


def test_orders_xml_roundtrip(live):
    order = live.get_order("ORD-000001")
    assert order.order_no == "ORD-000001" and order.lines


def test_missing_order_is_not_found(live):
    assert json.loads(ops.get_order(order_no="ORD-999999"))["error"]["code"] == "NOT_FOUND"


def test_customers_lookup(live):
    assert live.find_customers(customer_id=1)[0].id == 1
