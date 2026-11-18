"""The client's job: make the ugly API behave. Each test = one quirk."""
import httpx
import pytest

from shopmaster.errors import ShopError


def test_login_then_pagination_loops_past_the_25_row_cap(client, shop):
    products = client.list_products()
    assert len(products) == 30                            # 25 + 5, two pages
    assert shop.count("GET", "/products.do") == 2
    assert shop.logins == 1


def test_expired_token_is_refreshed_invisibly(client, shop):
    client.list_products("x")
    shop.expired.add(shop.token)                          # server now says "session expired" (401 JSON)
    assert client.get_product(1).id == 1                  # ...and the caller never notices
    assert shop.logins == 2


def test_superseded_token_is_refreshed_invisibly(client, shop):
    client.get_product(1)
    shop.token = "SOMEONE-ELSE"                           # another login killed ours (403 text)
    assert client.get_product(1).id == 1
    assert shop.logins == 2


def test_503_waits_as_long_as_the_server_asks(client, shop, sleeps):
    client.get_product(1)
    shop.script.append(("GET", httpx.Response(503, text="Server busy", headers={"X-Retry-After-Ms": "1500"})))
    assert client.get_product(1).id == 1
    assert any(s >= 1.5 for s in sleeps)


def test_503_forever_becomes_rate_limited_error(client, shop):
    client.get_product(1)
    for _ in range(3):
        shop.script.append(("GET", httpx.Response(503, text="busy", headers={"X-Retry-After-Ms": "100"})))
    with pytest.raises(ShopError) as e:
        client.get_product(1)
    assert e.value.code == "RATE_LIMITED" and e.value.retryable


def test_read_retries_a_random_500(client, shop):
    client.get_product(1)
    shop.script.append(("GET", httpx.Response(500, text="<html>Tomcat</html>")))
    assert client.get_product(1).id == 1


def test_write_is_never_blindly_retried_after_a_500(client, shop):
    client.get_product(1)
    shop.script.append(("POST", httpx.Response(500, text="<html>Tomcat</html>")))
    with pytest.raises(ShopError) as e:
        client.create_order(7, [{"sku": "SKU-1001", "qty": 1}])
    assert e.value.code == "UNCERTAIN_RESULT"
    assert shop.count("POST", "/orders.do") == 1          # exactly one attempt


def test_json_labelled_as_html_still_parses(client):
    c = client.find_customers(email="john@example.com")[0]
    assert (c.first_name, c.last_name, c.email, c.phone, c.zip) == ("John", "Smith", "john@example.com", "+15550101234", "02134")


def test_product_detail_cleans_everything(client):
    p = client.get_product(1)
    assert p.price == 5.5 and p.category == "Electronics" and p.in_stock is True
    assert p.description == "Nice thing" and p.discontinued is False and str(p.last_updated) == "2021-03-15"


def test_order_status_error_codes(client, shop):
    shop.orders.append({"no": "ORD-000001", "cust": 7, "status": 0, "total": "10.00", "lines": []})
    client.update_order_status("ORD-000001", "PAID")      # fine
    with pytest.raises(ShopError) as e:
        client.update_order_status("ORD-000001", "DELIVERED")
    assert e.value.code == "INVALID_TRANSITION"
    with pytest.raises(ShopError) as e:
        client.update_order_status("ORD-999999", "PAID")
    assert e.value.code == "NOT_FOUND"


def test_unreachable_server_is_a_clean_error(shop):
    from shopmaster.client import ShopMasterClient

    def boom(request):
        raise httpx.ConnectError("refused")

    c = ShopMasterClient(transport=httpx.MockTransport(boom), sleep=lambda s: None)
    with pytest.raises(ShopError) as e:
        c.get_product(1)
    assert e.value.code == "NETWORK"


def test_bad_password(shop, sleeps):
    from shopmaster.client import ShopMasterClient
    c = ShopMasterClient(password="wrong", transport=shop.transport(), sleep=sleeps.append)
    with pytest.raises(ShopError) as e:
        c.get_product(1)
    assert e.value.code == "LOGIN_FAILED"
