package com.codebasics.legacyshop;

import jakarta.inject.Inject;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Path("/legacy")
public class ProductResource {
    @Inject
    Db db;

    /**
     * List: lowercase keys, raw dirty values, 1-based "pg" + "sz" (silently capped at 25).
     * "cat" is an exact, case-sensitive match against the dirty category column.
     */
    @GET
    @Path("/products.do")
    @Produces(MediaType.APPLICATION_JSON)
    public Map<String, Object> list(@QueryParam("pg") String pg, @QueryParam("sz") String sz,
                                    @QueryParam("cat") String cat, @QueryParam("q") String q) {
        int page = Math.max(1, R.lenientInt(pg, 1));
        int size = R.lenientInt(sz, 10);
        if (size <= 0) size = 10;
        if (size > 25) size = 25;

        StringBuilder where = new StringBuilder(" WHERE 1=1");
        List<Object> args = new ArrayList<>();
        if (cat != null && !cat.isEmpty()) {
            where.append(" AND CATEGORY = ?");
            args.add(cat);
        }
        if (q != null && !q.isEmpty()) {
            where.append(" AND PROD_NAME LIKE ?");
            args.add("%" + q + "%");
        }
        long cnt = ((Number) db.query("SELECT COUNT(*) AS n FROM PRODUCTS" + where, args.toArray())
            .get(0).get("n")).longValue();

        List<Object> a2 = new ArrayList<>(args);
        a2.add(size);
        a2.add((page - 1) * size);
        List<Map<String, Object>> rows = db.query(
            "SELECT PROD_ID AS prod_id, SKU AS sku, PROD_NAME AS name, PRICE AS price, CATEGORY AS cat, "
                + "IN_STOCK AS in_stock, LAST_UPD AS last_upd FROM PRODUCTS" + where
                + " ORDER BY PROD_ID LIMIT ? OFFSET ?", a2.toArray());

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("rows", rows);
        result.put("cnt", cnt);
        result.put("pg", page);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("result", result);
        out.put("ts", Instant.now().getEpochSecond());
        return out;
    }

    /** Detail: UPPER_CASE keys, price normalised to cents (or null) plus the raw string. Different shape from list! */
    @GET
    @Path("/product/{id}")
    public Response detail(@PathParam("id") String id) {
        long pid;
        try {
            pid = Long.parseLong(id.trim());
        } catch (NumberFormatException e) {
            return R.text(400, "bad id");
        }
        List<Map<String, Object>> rows = db.query("SELECT * FROM PRODUCTS WHERE PROD_ID = ?", pid);
        if (rows.isEmpty()) return R.text(404, "no such item");
        Map<String, Object> p = rows.get(0);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("PROD_ID", p.get("PROD_ID"));
        out.put("SKU", p.get("SKU"));
        out.put("PROD_NAME", p.get("PROD_NAME"));
        out.put("DESCR", p.get("DESCR"));
        out.put("PRICE_CENTS", Money.parseCents(R.str(p.get("PRICE"))));
        out.put("PRICE_RAW", p.get("PRICE"));
        out.put("CATEGORY", p.get("CATEGORY"));
        out.put("IN_STOCK", p.get("IN_STOCK"));
        out.put("QTY_ON_HAND", p.get("QTY_ON_HAND"));
        out.put("LAST_UPD", p.get("LAST_UPD"));
        out.put("WEIGHT", p.get("WEIGHT"));
        out.put("DISCONTINUED", p.get("DISCONTINUED"));
        return R.json(200, out);
    }
}
