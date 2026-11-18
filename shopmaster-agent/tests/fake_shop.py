"""A tiny in-memory imitation of ShopMaster, plugged into httpx as a fake transport.

It lets us test the client's retry / re-login / parsing logic with no network, no Java, no LLM.
It is NOT the real thing: the live tests (test_live_api.py) check the real API.
"""
import json
import time
from urllib.parse import parse_qs

import httpx


class FakeShop:
    def __init__(self):
        self.requests: list[tuple[str, str]] = []   # (method, path) of every request seen
        self.logins = 0
        self.token = None
        self.expired: set[str] = set()
        self.ttl = 300
        self.script: list[tuple[str, httpx.Response]] = []  # forced responses: (method or "*", response)
        self.post_commit_500 = False
        self.stock = {"SKU-1001": 5, "SKU-1002": 0}
        self.orders: list[dict] = []
        self.products = [
            {"prod_id": i, "sku": f"SKU-{1000 + i}", "name": f"Item {i}", "price": "10.00" if i % 2 else "$5.50",
             "cat": "electronics" if i % 2 else "home-garden", "in_stock": "Y", "last_upd": "03/15/2021"}
            for i in range(1, 31)
        ]

    def transport(self):
        return httpx.MockTransport(self.handle)

    def count(self, method, path_suffix):
        return sum(1 for m, p in self.requests if m == method and p.endswith(path_suffix))

    # -------------------------------------------------------------- the "server"
    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        q = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        self.requests.append((request.method, path))

        if path.endswith("/ping.do"):
            return httpx.Response(200, text="PONG")
        if path.endswith("/login.do"):
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            if form.get("u") != "svc_agent" or form.get("p") != "Winter2009!":
                return httpx.Response(200, text="FAIL|BAD_CREDENTIALS")
            self.logins += 1
            self.token = f"TOK{self.logins}"
            return httpx.Response(200, text=f"OK|{self.token}|{int(time.time()) + self.ttl}")

        # --- auth: three different failure formats, like the real thing
        tok = request.headers.get("X-SM-Session")
        if not tok:
            return httpx.Response(401, text="<html><body><h1>Login required</h1></body></html>")
        if tok in self.expired:
            return httpx.Response(401, json={"err": "session expired", "code": 1002})
        if tok != self.token:
            return httpx.Response(403, text="Access Denied")

        if self.script and self.script[0][0] in (request.method, "*"):
            return self.script.pop(0)[1]

        if path.endswith("/products.do"):
            sz = min(int(q.get("sz", 10)), 25)
            pg = int(q.get("pg", 1))
            rows = self.products[(pg - 1) * sz: pg * sz]
            return httpx.Response(200, json={"result": {"rows": rows, "cnt": len(self.products), "pg": pg}, "ts": 1})
        if "/product/" in path:
            pid = int(path.rsplit("/", 1)[1])
            p = next((x for x in self.products if x["prod_id"] == pid), None)
            if p is None:
                return httpx.Response(404, text="no such item")
            return httpx.Response(200, json={"PROD_ID": pid, "SKU": p["sku"], "PROD_NAME": p["name"], "DESCR": "<b>Nice</b><br>thing",
                                             "PRICE_CENTS": 550, "PRICE_RAW": p["price"], "CATEGORY": "electronics ",
                                             "IN_STOCK": "1", "QTY_ON_HAND": 7, "LAST_UPD": "1615766400", "WEIGHT": "1.2kg",
                                             "DISCONTINUED": None})
        if path.endswith("/inventory.do"):
            sku = q.get("sku", "").strip().upper()
            body = "SKU,QTY,WH\r\n" + "".join(f"{s},{n},WH-A\r\n" for s, n in self.stock.items() if not sku or s == sku)
            if sku == "SKU-1004":
                body += "SKU-1004,3,WH-A\r\nsku-1004 ,9,WH-B\r\n"
            return httpx.Response(200, text=body, headers={"content-type": "text/csv"})
        if path.endswith("/customers.do"):
            data = [{"cust_no": 7, "fname": "SMITH, JOHN", "lname": None, "Email": " JOHN@EXAMPLE.COM ", "Phone": "(555) 010-1234",
                     "active": "Y", "zip": 2134, "city": "Boston", "state": "MA"}]
            return httpx.Response(200, text=json.dumps(data), headers={"content-type": "text/html;charset=ISO-8859-1"})
        if path.endswith("/orders.do") and request.method == "GET":
            cust = q.get("custNo")
            rows = [o for o in self.orders if cust is None or str(o["cust"]) == cust]
            start, count = int(q.get("start", 0)), int(q.get("count", 20))
            page = rows[start:start + count]
            return httpx.Response(200, json={"orders": [
                {"ORDER_NO": o["no"], "CUST_NO": str(o["cust"]), "ORDER_DATE": "11/12/2026 10:00:00", "STATUS": o["status"],
                 "TOTAL": o["total"]} for o in page], "total": len(rows)})
        if path.endswith("/orders.do") and request.method == "POST":
            return self._create_order(json.loads(request.content))
        if path.endswith("/order.do"):
            o = next((x for x in self.orders if x["no"] == q.get("orderNo")), None)
            if o is None:
                return httpx.Response(200, text='<?xml version="1.0" encoding="ISO-8859-1"?><error code="404">Order not found</error>',
                                      headers={"content-type": "application/xml"})
            lines = "".join(f'<line n="{i}" sku="{l["sku"]}" qty="{l["qty"]}" price="10.00"/>' for i, l in enumerate(o["lines"], 1))
            xml = (f'<?xml version="1.0" encoding="ISO-8859-1"?><order no="{o["no"]}"><customer id="{o["cust"]}"><name>John Smith</name></customer>'
                   f'<date>11/12/2026 10:00:00</date><status code="{o["status"]}">X</status><total>{o["total"]}</total><lines>{lines}</lines></order>')
            return httpx.Response(200, text=xml, headers={"content-type": "application/xml"})
        if path.endswith("/order-status.do"):
            o = next((x for x in self.orders if x["no"] == q.get("orderNo")), None)
            if o is None:
                return httpx.Response(200, text="ERR:NO_SUCH_ORDER")
            to = int(q["status"])
            if (o["status"], to) in {(0, 1), (1, 2), (2, 3), (0, 9), (1, 9)}:
                o["status"] = to
                return httpx.Response(200, text="OK")
            return httpx.Response(200, text="ERR:INVALID_TRANSITION")
        return httpx.Response(404, text="not found")

    def _create_order(self, body: dict) -> httpx.Response:
        total = 0.0
        for line in body["lines"]:
            sku = line["sku"].strip().upper()
            if sku not in self.stock:
                return httpx.Response(200, json={"ok": False, "errors": [f"UNKNOWN_SKU:{line['sku']}"]})
            if self.stock[sku] < int(line["qty"]):
                return httpx.Response(409, text=f"STOCK_SHORT:{line['sku']}")
            total += 10.0 * int(line["qty"])
        for line in body["lines"]:
            self.stock[line["sku"].strip().upper()] -= int(line["qty"])
        order = {"no": f"ORD-{len(self.orders) + 1:06d}", "cust": body["custNo"], "status": 0,
                 "total": f"{total:.2f}", "lines": body["lines"]}
        self.orders.append(order)
        if self.post_commit_500:
            return httpx.Response(500, text="<html>Apache Tomcat/5.5.23 - Error report</html>")
        return httpx.Response(200, json={"ok": True, "orderNo": order["no"], "total": order["total"]})
