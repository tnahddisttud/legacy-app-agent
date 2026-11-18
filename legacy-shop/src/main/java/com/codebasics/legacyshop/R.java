package com.codebasics.legacyshop;

import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

/** Tiny response helpers. */
final class R {
    private R() {}

    static Response text(int status, String body) {
        return Response.status(status).type(MediaType.TEXT_PLAIN).entity(body).build();
    }

    static Response html(int status, String body) {
        return Response.status(status).type(MediaType.TEXT_HTML).entity(body).build();
    }

    static Response json(int status, Object body) {
        return Response.status(status).type(MediaType.APPLICATION_JSON).entity(body).build();
    }

    static Response xml(String body) {
        return Response.ok(body).type(MediaType.APPLICATION_XML).build();
    }

    static Response csv(String body) {
        return Response.ok(body).type("text/csv").build();
    }

    static int lenientInt(String s, int def) {
        if (s == null) return def;
        try {
            return Integer.parseInt(s.trim());
        } catch (NumberFormatException e) {
            return def;
        }
    }

    static String str(Object o) {
        return o == null ? null : o.toString();
    }

    static String esc(String s) {
        if (s == null) return "";
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;");
    }
}
