# ShopMaster 2.1 — a deliberately ugly legacy e-commerce API

Workshop target for **"Connect Your Agent To a Messy Enterprise App"**.
Quarkus + plain JDBC + SQLite.
## Run it

```bash
docker compose up --build        # http://localhost:8080/legacy/ping.do -> PONG
docker compose down -v           # wipe the DB volume and reseed next time
./scripts/smoke.sh               # guided tour with curl
```

Without Docker: `mvn quarkus:dev` (needs Java 21 + Maven). DB goes to `./data/shop.db`.

Credentials: `svc_agent` / `Winter2009!` (override with `SHOP_USER` / `SHOP_PASS`).

## Endpoints (all under `/legacy`)

| Endpoint | What it does | Response format |
|---|---|---|
| `GET  /ping.do` | liveness, no auth | text `PONG` |
| `POST /login.do` (form `u`, `p`) | get a session token | text `OK|<token>|<expiryEpoch>` or `FAIL|<REASON>`, always HTTP 200 |
| `GET  /products.do?pg&sz&cat&q` | list products | JSON `{result:{rows,cnt,pg},ts}`, lowercase keys |
| `GET  /product/{id}` | product detail | JSON, UPPER_CASE keys, `PRICE_CENTS` + `PRICE_RAW` |
| `GET  /customers.do?email&cust&page&limit` | find customers | bare JSON array, `Content-Type: text/html` |
| `GET  /inventory.do?sku` | stock levels | CSV, CRLF |
| `GET  /orders.do?custNo&status&start&count` | list orders | JSON `{orders,total}` |
| `GET  /order.do?orderNo` | order detail | **XML**; missing order = HTTP 200 `<error>` |
| `POST /orders.do` (JSON body) | create order | JSON `{ok,orderNo,total}` |
| `GET or POST /order-status.do?orderNo&status` | change status | text `OK` / `ERR:<CODE>`, always 200 |

Everything except `ping.do` and `login.do` needs the header **`X-SM-Session: <token>`** (not `Authorization`).

## The mess catalogue (answer key for the workshop)

**Auth**
- Token in custom header `X-SM-Session`; login returns pipe-delimited text, even failures are HTTP 200.
- Token lives 5 min (`SHOP_TOKEN_TTL_SEC`). One live session per account: logging in again kills the old token.
- Three different auth failures: missing header → `401` HTML; unknown/superseded token → `403` text `Access Denied`; expired → `401` JSON `{"err":"session expired","code":1002}`.

**Rate limits and flakiness**
- 15 requests / 10 s per token (`SHOP_RATE_MAX`, `SHOP_RATE_WINDOW_SEC`). Over the limit: `503` text, wait time in non-standard `X-Retry-After-Ms`.
- Random latency up to 250 ms and 5 % random `500` Tomcat-style HTML stack-trace pages (`SHOP_CHAOS_*`; set to `0` for a calm demo). Chaos hits *before* the handler, so retries are safe.

**Inconsistent data**
- Prices are text: `19.99`, `$24.50`, `1,299.00`, `12.50 ` (trailing space), `N/A`.
- `IN_STOCK`: `Y N 1 0 true yes no ""` or null, and ~25 % disagree with `QTY_ON_HAND`.
- Dates: ISO, `MM/dd/yyyy`, `dd-MMM-yyyy`, epoch-seconds string, and `MM/dd/yyyy HH:mm:ss` on new orders.
- Categories: casing, trailing spaces, `home-garden` vs `Home & Garden`, null. `cat=` filter is exact and case-sensitive.
- Duplicate SKU (`SKU-1004`), mixed-case SKUs, trailing spaces. SKU lookups elsewhere are trimmed + case-insensitive.
- Customers: names as `"SMITH, JOHN"` in `fname`, 6 phone formats, uppercase/padded/`n/a` emails, `active` as `Y 1 N 0 null` (null = active), ZIP as a number that loses leading zeros.
- Order status is an undocumented int: 0 NEW, 1 PAID, 2 SHIPPED, 3 DELIVERED, 9 CANCELLED, 7 HOLD (never use).

**Inconsistent API design**
- Four pagination styles: `pg/sz` (1-based, cap 25), `page/limit` (0-based, cap 20), `start/count` (offset, cap 50), none (inventory). Caps are silent.
- Key naming differs between list and detail, and between endpoints (`Email`, `cust_no`, `CUST_NO` as string vs number).
- Four formats: JSON, XML, CSV, pipe-delimited text.
- Validation failures are HTTP 200 `{ok:false,errors:[...]}`; out of stock is HTTP 409 text `STOCK_SHORT:<sku>`.
- `order-status.do` mutates over **GET** (a nasty trap for read-only tool annotations).
- `POST /orders.do` has no idempotency key; `IN_STOCK` flag is never updated by orders, only `QTY_ON_HAND`.

## Config knobs

| Env var | Default |
|---|---|
| `SHOP_USER` / `SHOP_PASS` | `svc_agent` / `Winter2009!` |
| `SHOP_TOKEN_TTL_SEC` | `300` |
| `SHOP_RATE_MAX` / `SHOP_RATE_WINDOW_SEC` | `15` / `10` |
| `SHOP_CHAOS_ERROR_RATE` | `0.05` |
| `SHOP_CHAOS_MAX_LATENCY_MS` | `250` |
| `SHOP_CHAOS_POST_COMMIT_ERROR_RATE` | `0` (try `0.3`: `POST /orders.do` saves the order, then answers 500) |
| `SHOP_DB_PATH` | `./data/shop.db` (`/data/shop.db` in Docker) |

## Layout

```
src/main/java/com/codebasics/legacyshop/
  LegacyFilter.java     auth + rate limit + chaos (each failure in a different format)
  AuthResource / ProductResource / CustomerResource / OrderResource / InventoryResource
  Db.java, Seeder.java  plain JDBC + deterministic dirty seed data (Random(42))
```
