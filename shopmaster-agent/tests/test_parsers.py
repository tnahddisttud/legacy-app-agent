from datetime import date

import pytest

from shopmaster import parsers as P
from shopmaster.errors import ShopError


@pytest.mark.parametrize("raw,expected", [
    ("19.99", 19.99), ("$24.50", 24.50), ("1,299.00", 1299.0), ("12.50 ", 12.5), ("N/A", None), ("", None), (None, None), ("nan", None),
])
def test_parse_price(raw, expected):
    assert P.parse_price(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Y", True), ("1", True), ("true", True), ("yes", True), ("N", False), ("0", False), ("no", False), ("", None), (None, None),
])
def test_parse_bool(raw, expected):
    assert P.parse_bool(raw) is expected


@pytest.mark.parametrize("raw", ["2021-03-15", "03/15/2021", "15-Mar-2021", "1615766400", "03/15/2021 08:30:00"])
def test_parse_date_all_formats_agree(raw):
    assert P.parse_date(raw) == date(2021, 3, 15)


def test_parse_date_junk():
    assert P.parse_date("not a date") is None and P.parse_date(None) is None


@pytest.mark.parametrize("raw", ["(555) 010-1234", "555.010.1234", "5550101234", "+1 555 010 1234", "555-010-1234"])
def test_parse_phone(raw):
    assert P.parse_phone(raw) == "+15550101234"


def test_parse_email():
    assert P.parse_email("  JOHN@Example.com ") == "john@example.com"
    assert P.parse_email("n/a") is None and P.parse_email(None) is None


def test_parse_name():
    assert P.parse_name("SMITH, JOHN", None) == ("John", "Smith")
    assert P.parse_name("MARIA", "GARCIA") == ("Maria", "Garcia")
    assert P.parse_name("Wei", "Chen") == ("Wei", "Chen")


@pytest.mark.parametrize("raw,expected", [
    ("electronics", "Electronics"), ("ELECTRONICS ", "Electronics"), ("home-garden", "Home & Garden"),
    ("Home & Garden", "Home & Garden"), (None, None), ("", None),
])
def test_parse_category(raw, expected):
    assert P.parse_category(raw) == expected


def test_parse_zip_restores_leading_zero():
    assert P.parse_zip(2134) == "02134" and P.parse_zip("78701") == "78701"


def test_stock_csv_with_crlf():
    rows = P.stock_rows_from_csv("SKU,QTY,WH\r\nSKU-1001 ,5,WH-A\r\nsku-1002,0,WH-B\r\n")
    assert [(r.sku, r.qty) for r in rows] == [("SKU-1001", 5), ("SKU-1002", 0)]


XML = ('<?xml version="1.0" encoding="ISO-8859-1"?><order no="ORD-000001"><customer id="5"><name>A</name></customer>'
       '<date>03/15/2021</date><status code="2">SHIPPED</status><total>59.9800</total>'
       '<lines><line n="1" sku="sku-1001" qty="2" price="29.99"/></lines></order>')


@pytest.mark.parametrize("payload", [XML, XML.encode()])
def test_order_xml(payload):
    o = P.order_from_xml(payload)
    assert (o.order_no, o.customer_id, o.status, o.total) == ("ORD-000001", 5, "SHIPPED", 59.98)
    assert o.lines[0].sku == "SKU-1001" and o.lines[0].qty == 2


def test_order_xml_error_element_is_not_found():
    with pytest.raises(ShopError) as e:
        P.order_from_xml('<?xml version="1.0"?><error code="404">Order not found</error>')
    assert e.value.code == "NOT_FOUND"
