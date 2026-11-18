#!/usr/bin/env bash
# Quick manual tour of the mess. Usage: ./scripts/smoke.sh   (app must be running)
BASE=${BASE:-http://localhost:8080/legacy}
set -u
echo "--- ping";  curl -s "$BASE/ping.do"; echo
echo "--- login (pipe-delimited text, HTTP 200 even on failure)"
RESP=$(curl -s -d 'u=svc_agent&p=Winter2009!' "$BASE/login.do"); echo "$RESP"
TOKEN=$(echo "$RESP" | cut -d'|' -f2)
H="X-SM-Session: $TOKEN"
echo "--- products page 1 (lowercase keys, dirty prices)";  curl -s -H "$H" "$BASE/products.do?pg=1&sz=3"; echo
echo "--- product detail (UPPERCASE keys, cents)";           curl -s -H "$H" "$BASE/product/1"; echo
echo "--- customers (JSON array served as text/html)";       curl -si -H "$H" "$BASE/customers.do?limit=2" | sed -n '1,/^\r$/p;$p'; echo
echo "--- inventory (CSV)";                                  curl -s -H "$H" "$BASE/inventory.do?sku=sku-1004"
echo "--- create order";  curl -s -H "$H" -X POST -d '{"custNo":"1","lines":[{"sku":"sku-1001","qty":"2"}]}' "$BASE/orders.do"; echo
echo "--- order detail (XML)";                               curl -s -H "$H" "$BASE/order.do?orderNo=ORD-000001"; echo
echo "--- no token -> HTML 401";                             curl -si "$BASE/products.do" | head -n 1
echo "--- bad token -> text 403";                            curl -si -H "X-SM-Session: nope" "$BASE/products.do" | head -n 1
echo "--- hammer to trigger 503 + X-Retry-After-Ms"
for i in $(seq 1 20); do curl -s -o /dev/null -w "%{http_code} " -H "$H" "$BASE/ping.do?x=$i" ; done; echo
for i in $(seq 1 20); do curl -s -o /dev/null -w "%{http_code} " -H "$H" "$BASE/inventory.do?sku=SKU-1001"; done; echo
