"""Turn messy legacy values into clean ones.

Two sections:
  1. Field parsers   - one tiny function per kind of dirty value (price, date, bool...).
  2. Row mappers     - build the models from the raw JSON / XML / CSV the API returns.

All of this is plain deterministic code: no LLM needed to clean data.
"""
import csv
import io
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

from .errors import ShopError
from .models import Customer, Order, OrderLine, Product, StockRow

# ---------------------------------------------------------------- 1. field parsers

STATUS_NAMES = {0: "NEW", 1: "PAID", 2: "SHIPPED", 3: "DELIVERED", 7: "HOLD", 9: "CANCELLED"}
STATUS_CODES = {name: code for code, name in STATUS_NAMES.items()}

_CANONICAL_CATEGORIES = ["Electronics", "Home & Garden", "Tools", "Sports", "Toys", "Kitchen", "Office"]


def _letters_only(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


_CATEGORY_BY_KEY = {_letters_only(c): c for c in _CANONICAL_CATEGORIES}


def parse_category(raw: str | None) -> str | None:
    """'electronics', 'ELECTRONICS ', 'home-garden' -> 'Electronics', 'Home & Garden'."""
    if raw is None or not raw.strip():
        return None
    return _CATEGORY_BY_KEY.get(_letters_only(raw), raw.strip().title())


def parse_price(raw) -> float | None:
    """'19.99', '$24.50', '1,299.00', '12.50 ' -> float.  'N/A', '' -> None."""
    if raw is None:
        return None
    s = str(raw).replace("$", "").replace(",", "").strip()
    if not re.fullmatch(r"-?\d+(\.\d+)?", s):
        return None
    return round(float(s), 2)


def parse_bool(raw) -> bool | None:
    """'Y', '1', 'true', 'yes' -> True.  'N', '0', 'false', 'no' -> False.  '' / None -> None."""
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in ("y", "yes", "1", "true", "t"):
        return True
    if s in ("n", "no", "0", "false", "f"):
        return False
    return None


_DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y", "%d-%b-%Y"]


def parse_date(raw) -> date | None:
    """Handles 2021-03-15, 03/15/2021 (US order assumed), 15-Mar-2021 and epoch seconds."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s.isdigit() and len(s) >= 9:
        return datetime.fromtimestamp(int(s), tz=timezone.utc).date()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_phone(raw: str | None) -> str | None:
    """'(555) 010-1234', '555.010.1234', '+1 555 010 1234' -> '+15550101234'."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return f"+1{digits}" if len(digits) == 10 else None


def parse_email(raw: str | None) -> str | None:
    """Trim + lowercase. 'n/a' and blanks become None."""
    if raw is None:
        return None
    s = raw.strip().lower()
    return s if "@" in s else None


def parse_name(fname: str | None, lname: str | None) -> tuple[str | None, str | None]:
    """Fixes 'SMITH, JOHN' stored in fname, and ALL-CAPS names."""
    first, last = (fname or "").strip(), (lname or "").strip()
    if not last and "," in first:
        last, first = [part.strip() for part in first.split(",", 1)]

    def tidy(s: str) -> str | None:
        return (s.title() if s.isupper() else s) or None

    return tidy(first), tidy(last)


def parse_zip(raw) -> str | None:
    """The API sends ZIPs as numbers, so 02134 arrives as 2134."""
    if raw is None:
        return None
    s = str(raw).strip()
    return s.zfill(5) if s.isdigit() else (s or None)


def _clean_text(raw: str | None) -> str | None:
    """Strip HTML tags and extra whitespace from descriptions."""
    if not raw:
        return None
    s = re.sub(r"<[^>]+>", " ", raw)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def _sku(raw: str) -> str:
    return raw.strip().upper()


# ---------------------------------------------------------------- 2. row mappers

def product_from_list_row(r: dict) -> Product:
    """products.do rows have lowercase keys."""
    return Product(
        id=int(r["prod_id"]),
        sku=_sku(r["sku"]),
        name=(r.get("name") or "").strip(),
        category=parse_category(r.get("cat")),
        price=parse_price(r.get("price")),
        in_stock=parse_bool(r.get("in_stock")),
        last_updated=parse_date(r.get("last_upd")),
    )


def product_from_detail(d: dict) -> Product:
    """product/{id} has UPPER_CASE keys and the price already in cents."""
    cents = d.get("PRICE_CENTS")
    return Product(
        id=int(d["PROD_ID"]),
        sku=_sku(d["SKU"]),
        name=(d.get("PROD_NAME") or "").strip(),
        category=parse_category(d.get("CATEGORY")),
        price=None if cents is None else round(cents / 100, 2),
        in_stock=parse_bool(d.get("IN_STOCK")),
        last_updated=parse_date(d.get("LAST_UPD")),
        qty_on_hand=d.get("QTY_ON_HAND"),
        discontinued=bool(parse_bool(d.get("DISCONTINUED"))),
        description=_clean_text(d.get("DESCR")),
        weight=d.get("WEIGHT"),
    )


def customer_from_json(d: dict) -> Customer:
    first, last = parse_name(d.get("fname"), d.get("lname"))
    return Customer(
        id=int(d["cust_no"]),
        first_name=first,
        last_name=last,
        email=parse_email(d.get("Email")),
        phone=parse_phone(d.get("Phone")),
        active=parse_bool(d.get("active")) is not False,  # null means active
        city=d.get("city"),
        state=d.get("state"),
        zip=parse_zip(d.get("zip")),
        notes=d.get("notes"),
    )


def order_from_list_row(r: dict) -> Order:
    code = int(r["STATUS"])
    return Order(
        order_no=r["ORDER_NO"],
        customer_id=int(r["CUST_NO"]),  # arrives as a string here
        order_date=parse_date(r.get("ORDER_DATE")),
        status=STATUS_NAMES.get(code, f"UNKNOWN_{code}"),
        total=parse_price(r.get("TOTAL")),
    )


def order_from_xml(content: bytes | str) -> Order:
    """order.do returns XML. A missing order is an <error> element (with HTTP 200!)."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise ShopError("UNEXPECTED_RESPONSE", f"Could not read order XML: {e}", retryable=True)
    if root.tag == "error":
        raise ShopError("NOT_FOUND", (root.text or "Order not found").strip(),
                        hint="Check the order number, or use list_orders to find it")
    customer = root.find("customer")
    status = root.find("status")
    code = int(status.get("code")) if status is not None else -1
    lines = [
        OrderLine(sku=_sku(el.get("sku", "")), qty=int(el.get("qty", "0")), unit_price=parse_price(el.get("price")))
        for el in root.findall("./lines/line")
    ]
    return Order(
        order_no=root.get("no", ""),
        customer_id=int(customer.get("id")) if customer is not None else 0,
        order_date=parse_date(root.findtext("date")),
        status=STATUS_NAMES.get(code, f"UNKNOWN_{code}"),
        total=parse_price(root.findtext("total")),
        lines=lines,
    )


def stock_rows_from_csv(text: str) -> list[StockRow]:
    """inventory.do returns CSV with CRLF line endings."""
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        try:
            rows.append(StockRow(sku=_sku(r["SKU"]), qty=int(r["QTY"]), warehouse=r["WH"].strip()))
        except (KeyError, ValueError, AttributeError):
            continue  # skip junk lines
    return rows
