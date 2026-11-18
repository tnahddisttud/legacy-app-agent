package com.codebasics.legacyshop;

import jakarta.inject.Inject;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.Response;

import java.util.List;
import java.util.Map;

@Path("/legacy")
public class InventoryResource {
    @Inject
    Db db;

    /** CSV with CRLF line endings. Duplicate SKUs produce duplicate rows. */
    @GET
    @Path("/inventory.do")
    public Response inventory(@QueryParam("sku") String sku) {
        List<Map<String, Object>> rows;
        if (sku == null || sku.isBlank()) {
            rows = db.query("SELECT PROD_ID, SKU, QTY_ON_HAND FROM PRODUCTS ORDER BY PROD_ID");
        } else {
            rows = db.query("SELECT PROD_ID, SKU, QTY_ON_HAND FROM PRODUCTS WHERE UPPER(TRIM(SKU)) = ? ORDER BY PROD_ID",
                sku.trim().toUpperCase());
        }
        StringBuilder sb = new StringBuilder("SKU,QTY,WH\r\n");
        for (Map<String, Object> r : rows) {
            int id = ((Number) r.get("PROD_ID")).intValue();
            sb.append(r.get("SKU")).append(',').append(r.get("QTY_ON_HAND"))
                .append(",WH-").append((char) ('A' + id % 3)).append("\r\n");
        }
        return R.csv(sb.toString());
    }
}
