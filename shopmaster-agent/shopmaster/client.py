"""ShopMasterClient: the ONLY place that knows how ugly the legacy API is.

What it hides from everyone else:
  * logging in, the 5-minute token, and re-logging in when it dies
  * the rate limit (we slow ourselves down, and obey X-Retry-After-Ms if we get a 503)
  * random 500s (retried for reads, NOT blindly retried for writes)
  * five different response formats (JSON, XML, CSV, pipe-text, JSON-labelled-as-HTML)
"""
import json
import random
import threading
import time
from collections import deque

import httpx

from . import parsers as P
from .errors import ShopError
from .models import Customer, Order, Product, StockRow

SESSION_HEADER = "X-SM-Session"  # not "Authorization"!

_ORDER_HINTS = {
    "UNKNOWN_SKU": "Use search_products to find the correct SKU.",
    "CUST_NOT_FOUND": "Use find_customer to look up the customer id.",
    "CUST_INACTIVE": "This customer account is inactive. Do not retry; tell the user.",
    "DISCONTINUED": "This product is discontinued. Suggest an alternative with search_products.",
    "NO_PRICE": "This product has no price in the system, so it cannot be ordered.",
    "BAD_QTY": "Quantity must be a whole number from 1 to 99.",
}


class ShopMasterClient:
    def __init__(self, base_url="http://localhost:8080/legacy", user="svc_agent", password="Winter2009!",
                 *, timeout=10.0, max_retries=3, rate_max=12, rate_window=10.0,
                 transport=None, sleep=time.sleep):
        self.base_url = base_url.rstrip("/")
        self.user, self.password = user, password
        self.max_retries = max_retries
        self.rate_max, self.rate_window = rate_max, rate_window  # stay under the server's 15 per 10s
        self._sleep = sleep
        self._http = httpx.Client(timeout=timeout, transport=transport)
        self._token: str | None = None
        self._expires_at = 0.0
        self._auth_lock = threading.Lock()
        self._rate_lock = threading.Lock()
        self._calls: deque[float] = deque()

    # ------------------------------------------------------------ auth

    def _ensure_token(self) -> str:
        """Log in if we have no token, or it expires within 10 seconds."""
        if self._token is None or time.time() >= self._expires_at - 10:
            with self._auth_lock:
                if self._token is None or time.time() >= self._expires_at - 10:  # re-check inside the lock
                    self._do_login()
        return self._token

    def _relogin(self, bad_token: str | None):
        """The server rejected our token. Log in again, unless another thread already did."""
        with self._auth_lock:
            if self._token == bad_token or self._token is None:
                self._do_login()

    def _do_login(self):
        """Caller holds the lock. Response looks like 'OK|<token>|<expiryEpoch>' (HTTP 200 even on failure)."""
        resp = self._request("POST", "/login.do", data={"u": self.user, "p": self.password}, auth=False)
        parts = resp.text.strip().split("|")
        if len(parts) >= 3 and parts[0] == "OK":
            self._token, self._expires_at = parts[1], float(parts[2])
        else:
            raise ShopError("LOGIN_FAILED", f"Login rejected by ShopMaster: {resp.text.strip()[:80]}",
                            hint="Check SHOPMASTER_USER and SHOPMASTER_PASS. Do not retry.")

    # ------------------------------------------------------------ the one place HTTP happens

    def _throttle(self):
        """Client-side rate limit: never send more than rate_max requests per rate_window seconds."""
        while True:
            with self._rate_lock:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= self.rate_window:
                    self._calls.popleft()
                if len(self._calls) < self.rate_max:
                    self._calls.append(now)
                    return
                wait = self.rate_window - (now - self._calls[0])
            self._sleep(max(wait, 0.05))

    def _backoff(self, attempt: int):
        self._sleep(0.4 * 2 ** (attempt - 1) + random.uniform(0, 0.2))

    def _request(self, method, path, *, params=None, data=None, content=None, headers=None,
                 auth=True, idempotent=True) -> httpx.Response:
        """Send a request and deal with auth, rate limits and server errors.

        idempotent=True  -> safe to send twice (reads). We retry timeouts and 500s.
        idempotent=False -> a write. If we can't tell whether it worked, we raise
                            UNCERTAIN_RESULT instead of risking a duplicate.
        """
        attempt, relogged = 0, False
        while True:
            attempt += 1
            hdrs = dict(headers or {})
            token = None
            if auth:
                token = self._ensure_token()
                hdrs[SESSION_HEADER] = token
            self._throttle()

            try:
                resp = self._http.request(method, self.base_url + path, params=params, data=data,
                                          content=content, headers=hdrs)
            except httpx.TimeoutException:
                if idempotent and attempt < self.max_retries:
                    self._backoff(attempt)
                    continue
                if not idempotent:
                    raise ShopError("UNCERTAIN_RESULT", "The request timed out; the change may or may not have been applied.",
                                    hint="Check the current state (get_order / list_orders) before trying again.")
                raise ShopError("TIMEOUT", "ShopMaster did not answer in time.", retryable=True)
            except httpx.HTTPError as e:
                raise ShopError("NETWORK", f"Cannot reach ShopMaster: {type(e).__name__}", retryable=True,
                                hint="The service may be down. Tell the user rather than retrying forever.")

            status = resp.status_code

            # Token problems: expired (401 JSON), superseded (403 text) or missing (401 HTML).
            if auth and status in (401, 403):
                if relogged:
                    raise ShopError("AUTH_FAILED", "ShopMaster keeps rejecting our session even after logging in again.")
                relogged = True
                attempt -= 1  # re-logging in doesn't count as a retry
                self._relogin(token)
                continue

            # Rate limited: 503 + a non-standard header telling us how long to wait.
            if status == 503:
                try:
                    wait_ms = int(resp.headers.get("X-Retry-After-Ms", "1000"))
                except ValueError:
                    wait_ms = 1000
                if attempt >= self.max_retries:
                    raise ShopError("RATE_LIMITED", "ShopMaster is rate limiting us.", retryable=True,
                                    hint=f"Wait about {wait_ms / 1000:.0f} seconds, then try again.")
                self._sleep(min(wait_ms, 10_000) / 1000 + 0.1)
                continue  # a 503 is rejected before the handler runs, so retrying is safe even for writes

            # Random server crash (HTML stack trace).
            if status >= 500:
                if not idempotent:
                    raise ShopError("UNCERTAIN_RESULT", "ShopMaster crashed while handling a write; the change may or may not have been applied.",
                                    hint="Check the current state (get_order / list_orders) before trying again.")
                if attempt >= self.max_retries:
                    raise ShopError("SERVER_ERROR", "ShopMaster returned a server error.", retryable=True)
                self._backoff(attempt)
                continue

            return resp

    @staticmethod
    def _json(resp: httpx.Response):
        """Parse JSON from the body. We ignore Content-Type because the API lies (JSON labelled text/html)."""
        try:
            return json.loads(resp.text)
        except ValueError:
            raise ShopError("UNEXPECTED_RESPONSE", f"Expected JSON but got: {resp.text[:60]!r}", retryable=True)

    @staticmethod
    def _expect_200(resp: httpx.Response, what: str):
        if resp.status_code == 404:
            raise ShopError("NOT_FOUND", f"{what} not found.")
        if resp.status_code == 400:
            raise ShopError("BAD_REQUEST", f"ShopMaster rejected the request for {what}: {resp.text[:60]}")
        if resp.status_code != 200:
            raise ShopError("UNEXPECTED_RESPONSE", f"Unexpected HTTP {resp.status_code} for {what}.", retryable=True)

    # ------------------------------------------------------------ reads

    def list_products(self, query: str | None = None) -> list[Product]:
        """Fetch ALL matching products. The API silently caps pages at 25 rows, so we loop."""
        products, page = [], 1
        while True:
            params = {"pg": page, "sz": 25}
            if query:
                params["q"] = query
            resp = self._request("GET", "/products.do", params=params)
            self._expect_200(resp, "product list")
            result = self._json(resp)["result"]
            rows = result["rows"]
            products += [P.product_from_list_row(r) for r in rows]
            if not rows or len(products) >= result["cnt"] or page >= 20:
                return products
            page += 1

    def get_product(self, product_id: int) -> Product:
        resp = self._request("GET", f"/product/{product_id}")
        self._expect_200(resp, f"product {product_id}")
        return P.product_from_detail(self._json(resp))

    def check_stock(self, sku: str) -> list[StockRow]:
        resp = self._request("GET", "/inventory.do", params={"sku": sku.strip()})
        self._expect_200(resp, f"stock for {sku}")
        return P.stock_rows_from_csv(resp.text)

    def find_customers(self, email: str | None = None, customer_id: int | None = None) -> list[Customer]:
        params = {"limit": 20}
        if email:
            params["email"] = email.strip()
        if customer_id is not None:
            params["cust"] = customer_id
        resp = self._request("GET", "/customers.do", params=params)
        self._expect_200(resp, "customer search")
        return [P.customer_from_json(d) for d in self._json(resp)]

    def list_orders(self, customer_id: int | None = None, status_code: int | None = None,
                    start: int = 0, count: int = 20) -> tuple[list[Order], int]:
        params = {"start": start, "count": count}
        if customer_id is not None:
            params["custNo"] = customer_id
        if status_code is not None:
            params["status"] = status_code
        resp = self._request("GET", "/orders.do", params=params)
        self._expect_200(resp, "order list")
        body = self._json(resp)
        return [P.order_from_list_row(r) for r in body["orders"]], int(body["total"])

    def get_order(self, order_no: str) -> Order:
        resp = self._request("GET", "/order.do", params={"orderNo": order_no.strip()})
        self._expect_200(resp, f"order {order_no}")
        return P.order_from_xml(resp.content)

    # ------------------------------------------------------------ writes (never blindly retried)

    def create_order(self, customer_id: int, lines: list[dict]) -> dict:
        payload = {"custNo": customer_id, "lines": [{"sku": l["sku"], "qty": l["qty"]} for l in lines]}
        resp = self._request("POST", "/orders.do", content=json.dumps(payload),
                             headers={"Content-Type": "application/json"}, idempotent=False)
        if resp.status_code == 409:  # plain text "STOCK_SHORT:<sku>"
            sku = resp.text.strip().split(":", 1)[-1]
            raise ShopError("OUT_OF_STOCK", f"Not enough stock for {sku}.",
                            hint="Use check_stock, then offer a smaller quantity or another product.")
        self._expect_200(resp, "order creation")
        body = self._json(resp)  # HTTP 200 even when the order was rejected!
        if body.get("ok"):
            return {"order_no": body["orderNo"], "total": P.parse_price(body.get("total"))}
        errors = body.get("errors", [])
        hint = next((h for prefix, h in _ORDER_HINTS.items() if any(e.startswith(prefix) for e in errors)), None)
        raise ShopError("ORDER_REJECTED", "; ".join(errors) or "Order rejected.", hint=hint)

    def update_order_status(self, order_no: str, new_status: str) -> None:
        code = P.STATUS_CODES[new_status]
        resp = self._request("POST", "/order-status.do", params={"orderNo": order_no.strip(), "status": code},
                             idempotent=False)
        self._expect_200(resp, "status change")
        text = resp.text.strip()  # "OK" or "ERR:<CODE>", always HTTP 200
        if text == "OK":
            return
        if text == "ERR:NO_SUCH_ORDER":
            raise ShopError("NOT_FOUND", f"Order {order_no} not found.")
        if text == "ERR:INVALID_TRANSITION":
            raise ShopError("INVALID_TRANSITION", f"Order {order_no} cannot move to {new_status} from its current status.",
                            hint="Allowed moves: NEW->PAID, PAID->SHIPPED, SHIPPED->DELIVERED, NEW or PAID->CANCELLED. Use get_order to see the current status.")
        raise ShopError("BAD_REQUEST", f"ShopMaster said: {text}")
