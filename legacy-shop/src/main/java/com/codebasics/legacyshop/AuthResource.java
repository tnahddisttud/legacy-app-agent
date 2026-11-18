package com.codebasics.legacyshop;

import jakarta.inject.Inject;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.FormParam;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

@Path("/legacy")
public class AuthResource {
    @Inject
    AuthStore auth;

    /** Unauthenticated liveness check. */
    @GET
    @Path("/ping.do")
    public Response ping() {
        return R.text(200, "PONG");
    }

    /**
     * Form-encoded login. Always HTTP 200. Body is pipe-delimited text:
     *   OK|<token>|<expiryEpochSeconds>   or   FAIL|<REASON>
     */
    @POST
    @Path("/login.do")
    @Consumes(MediaType.APPLICATION_FORM_URLENCODED)
    public Response login(@FormParam("u") String u, @FormParam("p") String p) {
        if (u == null || p == null) return R.text(200, "FAIL|MISSING_FIELDS");
        AuthStore.Session s = auth.login(u, p);
        if (s == null) return R.text(200, "FAIL|BAD_CREDENTIALS");
        return R.text(200, "OK|" + s.token() + "|" + s.expiresAtEpochSec());
    }
}
