package com.codebasics.legacyshop;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

import java.sql.Connection;
import java.sql.SQLException;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ThreadLocalRandom;

import org.eclipse.microprofile.config.inject.ConfigProperty;

@Path("/legacy")
public class OrderResource {
    private static final Map<Integer, String> STATUS = Map.of(
        0, "NEW", 1, "PAID", 2, "SHIPPED", 3, "DELIVERED", 7, "HOLD", 9, "CANCELLED");

    @Inject
    Db db;
    @Inject
    ObjectMapper mapper;

    /** Chance that POST /orders.do saves the order and THEN answers 500 (the nasty duplicate-order trap). */
    @ConfigProperty(name = "shop.chaos.post-commit-error-rate")
    double postCommitErrorRate;

    record Line(String sku, int qty) {}

    // ------------------------------------------------------------------ create

    /**
     * Create an order. Validation problems come back as HTTP 200 {"ok":false,"errors":[...]}.
     * Out-of-stock is HTTP 409 plain text "STOCK_SHORT:<sku>". Success is 200 (not 201).
     * qty may be a number or a numeric string. Stock flag IN_STOCK is NOT updated (only QTY_ON_HAND).
     * There is no idempotency: retrying a timed-out POST creates a second order.
     */
    @POST
    @Path("/orders.do")
    @Consumes(MediaType.WILDCARD)
    public Response create(String raw) {
        JsonNode root;
        try {
            root = mapper.readTree(raw == null ? "" : raw);
        } catch (Exception e) {
            root = null;
        }
        if (root == null || !root.isObject()) return bad(List.of("BAD_JSON"));

        List<String> errors = new ArrayList<>();
        Long custNo = asLong(root.has("custNo") ? root.get("custNo") : root.get("cust_no"));
        if (custNo == null) errors.add("CUST_NO_REQUIRED");

        List<Line> lines = new ArrayList<>();
        JsonNode ln = root.get("lines");
        if (ln == null || !ln.isArray() || ln.isEmpty()) {
            errors.add("LINES_REQUIRED");
        } else {
            for (JsonNode l : ln) {
                String sku = l.hasNonNull("sku") ? l.get("sku").asText().trim() : "";
                Long q = asLong(l.get("qty"));
                if (sku.isEmpty()) errors.add("SKU_REQUIRED");
                else if (q == null || q <= 0 || q > 99) errors.add("BAD_QTY:" + sku);
                else lines.add(new Line(sku, q.intValue()));
            }
        }
        if (!errors.isEmpty()) return bad(errors);

        db.writeLock.lock();
        try (Connection c = db.open()) {
            c.setAutoCommit(false);
            List<Map<String, Object>> cust = Db.queryOn(c, "SELECT ACTIVE FROM CUSTOMERS WHERE CUST_NO = ?", custNo);
            if (cust.isEmpty()) return bad(List.of("CUST_NOT_FOUND"));
            String act = R.str(cust.get(0).get("ACTIVE"));
            if (act != null && Set.of("N", "0", "FALSE", "NO").contains(act.trim().toUpperCase())) {
                return bad(List.of("CUST_INACTIVE"));
            }

            long total = 0;
            List<Object[]> resolved = new ArrayList<>();
            for (Line l : lines) {
                List<Map<String, Object>> pr = Db.queryOn(c,
                    "SELECT PROD_ID, PRICE, QTY_ON_HAND, DISCONTINUED FROM PRODUCTS "
                        + "WHERE UPPER(TRIM(SKU)) = ? ORDER BY PROD_ID LIMIT 1", l.sku().toUpperCase());
                if (pr.isEmpty()) {
                    errors.add("UNKNOWN_SKU:" + l.sku());
                    continue;
                }
                Map<String, Object> p = pr.get(0);
                Integer cents = Money.parseCents(R.str(p.get("PRICE")));
                if ("Y".equalsIgnoreCase(R.str(p.get("DISCONTINUED")))) {
                    errors.add("DISCONTINUED:" + l.sku());
                } else if (cents == null) {
                    errors.add("NO_PRICE:" + l.sku());
                } else {
                    int have = ((Number) p.get("QTY_ON_HAND")).intValue();
                    if (have < l.qty()) {
                        c.rollback();
                        return R.text(409, "STOCK_SHORT:" + l.sku());
                    }
                    Db.updateOn(c, "UPDATE PRODUCTS SET QTY_ON_HAND = QTY_ON_HAND - ? WHERE PROD_ID = ?",
                        l.qty(), p.get("PROD_ID"));
                    total += (long) cents * l.qty();
                    resolved.add(new Object[]{l.sku(), l.qty(), cents});
                }
            }
            if (!errors.isEmpty()) {
                c.rollback();
                return bad(errors);
            }

            long next = ((Number) Db.queryOn(c,
                "SELECT COALESCE(MAX(CAST(SUBSTR(ORDER_NO,5) AS INTEGER)),0)+1 AS n FROM ORDERS")
                .get(0).get("n")).longValue();
            String orderNo = String.format("ORD-%06d", next);
            Db.updateOn(c, "INSERT INTO ORDERS VALUES (?,?,?,?,?,?)", orderNo, custNo,
                LocalDateTime.now().format(DateTimeFormatter.ofPattern("MM/dd/yyyy HH:mm:ss")), 0, Money.fmt(total), null);
            int n = 0;
            for (Object[] r : resolved) {
                Db.updateOn(c, "INSERT INTO ORDER_LINES VALUES (?,?,?,?,?)", orderNo, ++n, r[0],
                    String.valueOf(r[1]), Money.fmt((Integer) r[2]));
            }
            c.commit();

            if (postCommitErrorRate > 0 && ThreadLocalRandom.current().nextDouble() < postCommitErrorRate) {
                // The order IS saved, but the client is told the server crashed.
                return R.html(500, "<html><head><title>Apache Tomcat/5.5.23 - Error report</title></head><body>"
                    + "<h1>HTTP Status 500 - </h1><pre>java.net.SocketException: Broken pipe</pre></body></html>");
            }

            Map<String, Object> ok = new LinkedHashMap<>();
            ok.put("ok", true);
            ok.put("orderNo", orderNo);
            ok.put("total", Money.fmt(total)); // string, not number
            return R.json(200, ok);
        } catch (SQLException e) {
            throw new RuntimeException(e);
        } finally {
            db.writeLock.unlock();
        }
    }

    // ------------------------------------------------------------------ list

    /**
     * List orders. Offset pagination via "start" + "count" (max 50) -- a fourth style.
     * CUST_NO comes back as a STRING here but as a number elsewhere. STATUS is an undocumented int code.
     */
    @GET
    @Path("/orders.do")
    @Produces(MediaType.APPLICATION_JSON)
    public Map<String, Object> list(@QueryParam("custNo") String custNo, @QueryParam("status") String status,
                                    @QueryParam("start") String start, @QueryParam("count") String count) {
        int off = Math.max(0, R.lenientInt(start, 0));
        int cnt = R.lenientInt(count, 20);
        if (cnt <= 0) cnt = 20;
        if (cnt > 50) cnt = 50;

        StringBuilder where = new StringBuilder(" WHERE 1=1");
        List<Object> args = new ArrayList<>();
        if (custNo != null && !custNo.isBlank()) {
            where.append(" AND CUST_NO = ?");
            args.add((long) R.lenientInt(custNo, -1));
        }
        if (status != null && !status.isBlank()) {
            where.append(" AND STATUS = ?");
            args.add((long) R.lenientInt(status, -1));
        }
        long total = ((Number) db.query("SELECT COUNT(*) AS n FROM ORDERS" + where, args.toArray())
            .get(0).get("n")).longValue();
        List<Object> a2 = new ArrayList<>(args);
        a2.add(cnt);
        a2.add(off);
        List<Map<String, Object>> rows = db.query(
            "SELECT ORDER_NO, CAST(CUST_NO AS TEXT) AS CUST_NO, ORDER_DATE, STATUS, TOTAL FROM ORDERS" + where
                + " ORDER BY ORDER_NO LIMIT ? OFFSET ?", a2.toArray());

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("orders", rows);
        out.put("total", total);
        return out;
    }

    // ------------------------------------------------------------------ detail (XML!)

    /** Order detail as XML. A missing order is HTTP 200 with an <error> element. */
    @GET
    @Path("/order.do")
    public Response detail(@QueryParam("orderNo") String orderNo) {
        String no = orderNo == null ? "" : orderNo.trim().toUpperCase();
        List<Map<String, Object>> rows = db.query("SELECT * FROM ORDERS WHERE ORDER_NO = ?", no);
        if (rows.isEmpty()) {
            return R.xml("<?xml version=\"1.0\" encoding=\"ISO-8859-1\"?><error code=\"404\">Order not found</error>");
        }
        Map<String, Object> o = rows.get(0);
        List<Map<String, Object>> cust = db.query("SELECT FNAME, LNAME FROM CUSTOMERS WHERE CUST_NO = ?", o.get("CUST_NO"));
        String name = cust.isEmpty() ? "" : ((R.str(cust.get(0).get("FNAME")) == null ? "" : R.str(cust.get(0).get("FNAME")))
            + " " + (R.str(cust.get(0).get("LNAME")) == null ? "" : R.str(cust.get(0).get("LNAME")))).trim();
        int st = ((Number) o.get("STATUS")).intValue();

        StringBuilder x = new StringBuilder("<?xml version=\"1.0\" encoding=\"ISO-8859-1\"?>\n");
        x.append("<order no=\"").append(R.esc(no)).append("\">\n");
        x.append("  <customer id=\"").append(o.get("CUST_NO")).append("\"><name>").append(R.esc(name)).append("</name></customer>\n");
        x.append("  <date>").append(R.esc(R.str(o.get("ORDER_DATE")))).append("</date>\n");
        x.append("  <status code=\"").append(st).append("\">").append(STATUS.getOrDefault(st, "UNKNOWN")).append("</status>\n");
        x.append("  <total>").append(R.esc(R.str(o.get("TOTAL")))).append("</total>\n");
        x.append("  <lines>\n");
        for (Map<String, Object> l : db.query("SELECT * FROM ORDER_LINES WHERE ORDER_NO = ? ORDER BY LINE_NO", no)) {
            x.append("    <line n=\"").append(l.get("LINE_NO")).append("\" sku=\"").append(R.esc(R.str(l.get("SKU"))))
                .append("\" qty=\"").append(R.esc(R.str(l.get("QTY")))).append("\" price=\"")
                .append(R.esc(R.str(l.get("UNIT_PRICE")))).append("\"/>\n");
        }
        x.append("  </lines>\n</order>");
        return R.xml(x.toString());
    }

    // ------------------------------------------------------------------ status change (GET mutates!)

    /**
     * Change order status. Reachable via GET (mutating!) and POST. Always 200, text body "OK" or "ERR:<CODE>".
     * Allowed: 0->1, 1->2, 2->3, 0|1->9. Cancelling puts stock back.
     */
    @GET
    @Path("/order-status.do")
    public Response statusGet(@QueryParam("orderNo") String orderNo, @QueryParam("status") String status) {
        return changeStatus(orderNo, status);
    }

    @POST
    @Path("/order-status.do")
    public Response statusPost(@QueryParam("orderNo") String orderNo, @QueryParam("status") String status) {
        return changeStatus(orderNo, status);
    }

    private Response changeStatus(String orderNo, String status) {
        int to;
        try {
            to = Integer.parseInt(status.trim());
        } catch (Exception e) {
            return R.text(200, "ERR:BAD_STATUS");
        }
        String no = orderNo == null ? "" : orderNo.trim().toUpperCase();
        db.writeLock.lock();
        try (Connection c = db.open()) {
            c.setAutoCommit(false);
            List<Map<String, Object>> rows = Db.queryOn(c, "SELECT STATUS FROM ORDERS WHERE ORDER_NO = ?", no);
            if (rows.isEmpty()) return R.text(200, "ERR:NO_SUCH_ORDER");
            int from = ((Number) rows.get(0).get("STATUS")).intValue();
            boolean ok = (from == 0 && to == 1) || (from == 1 && to == 2) || (from == 2 && to == 3)
                || ((from == 0 || from == 1) && to == 9);
            if (!ok) return R.text(200, "ERR:INVALID_TRANSITION");

            Db.updateOn(c, "UPDATE ORDERS SET STATUS = ? WHERE ORDER_NO = ?", to, no);
            if (to == 9) {
                for (Map<String, Object> l : Db.queryOn(c, "SELECT SKU, QTY FROM ORDER_LINES WHERE ORDER_NO = ?", no)) {
                    Db.updateOn(c, "UPDATE PRODUCTS SET QTY_ON_HAND = QTY_ON_HAND + ? WHERE PROD_ID = "
                            + "(SELECT PROD_ID FROM PRODUCTS WHERE UPPER(TRIM(SKU)) = ? ORDER BY PROD_ID LIMIT 1)",
                        R.lenientInt(R.str(l.get("QTY")), 0), R.str(l.get("SKU")).trim().toUpperCase());
                }
            }
            c.commit();
            return R.text(200, "OK");
        } catch (SQLException e) {
            throw new RuntimeException(e);
        } finally {
            db.writeLock.unlock();
        }
    }

    // ------------------------------------------------------------------ helpers

    private static Response bad(List<String> errors) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("ok", false);
        m.put("errors", errors);
        return R.json(200, m); // HTTP 200 on failure
    }

    private static Long asLong(JsonNode n) {
        if (n == null || n.isNull()) return null;
        if (n.isNumber()) return n.asLong();
        if (n.isTextual()) {
            try {
                return Long.parseLong(n.asText().trim());
            } catch (NumberFormatException e) {
                return null;
            }
        }
        return null;
    }
}
