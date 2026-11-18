package com.codebasics.legacyshop;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.inject.Inject;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.Response;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Path("/legacy")
public class CustomerResource {
    @Inject
    Db db;
    @Inject
    ObjectMapper mapper;

    /**
     * Returns a bare JSON array, but with Content-Type: text/html.
     * Pagination here is 0-based "page" + "limit" (max 20) -- a third style across the API.
     */
    @GET
    @Path("/customers.do")
    public Response list(@QueryParam("email") String email, @QueryParam("cust") String cust,
                         @QueryParam("page") String page, @QueryParam("limit") String limit) throws Exception {
        int pg = Math.max(0, R.lenientInt(page, 0));
        int lim = R.lenientInt(limit, 10);
        if (lim <= 0) lim = 10;
        if (lim > 20) lim = 20;

        StringBuilder where = new StringBuilder(" WHERE 1=1");
        List<Object> args = new ArrayList<>();
        if (email != null && !email.isBlank()) {
            where.append(" AND LOWER(TRIM(EMAIL)) = LOWER(TRIM(?))");
            args.add(email);
        }
        if (cust != null && !cust.isBlank()) {
            where.append(" AND CUST_NO = ?");
            try {
                args.add(Long.parseLong(cust.trim()));
            } catch (NumberFormatException e) {
                args.add(-1L);
            }
        }
        args.add(lim);
        args.add(pg * lim);
        List<Map<String, Object>> rows = db.query("SELECT * FROM CUSTOMERS" + where
            + " ORDER BY CUST_NO LIMIT ? OFFSET ?", args.toArray());

        List<Map<String, Object>> out = new ArrayList<>();
        for (Map<String, Object> r : rows) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("cust_no", r.get("CUST_NO"));
            m.put("fname", r.get("FNAME"));
            m.put("lname", r.get("LNAME"));
            m.put("Email", r.get("EMAIL"));   // capital E, on purpose
            m.put("Phone", r.get("PHONE"));   // capital P, on purpose
            m.put("active", r.get("ACTIVE"));
            m.put("created", r.get("CREATED"));
            m.put("addr1", r.get("ADDR1"));
            m.put("city", r.get("CITY"));
            m.put("state", r.get("STATE"));
            String zip = R.str(r.get("ZIP"));
            m.put("zip", zip != null && zip.matches("\\d+") ? (Object) Integer.valueOf(zip) : zip);
            m.put("notes", r.get("NOTES"));
            out.add(m);
        }
        return Response.ok(mapper.writeValueAsString(out)).type("text/html;charset=ISO-8859-1").build();
    }
}
