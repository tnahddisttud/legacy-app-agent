package com.codebasics.legacyshop;

import jakarta.annotation.Priority;
import jakarta.inject.Inject;
import jakarta.ws.rs.Priorities;
import jakarta.ws.rs.container.ContainerRequestContext;
import jakarta.ws.rs.container.ContainerRequestFilter;
import jakarta.ws.rs.container.ContainerResponseContext;
import jakarta.ws.rs.container.ContainerResponseFilter;
import jakarta.ws.rs.core.Response;
import jakarta.ws.rs.ext.Provider;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;

/**
 * Auth + rate limit + chaos, all in one filter, each failure in a DIFFERENT format.
 * Token travels in the non-standard X-SM-Session header (no "Bearer", no Authorization).
 */
@Provider
@Priority(Priorities.AUTHENTICATION)
public class LegacyFilter implements ContainerRequestFilter, ContainerResponseFilter {
    public static final String SESSION_HEADER = "X-SM-Session";

    private static final String TOMCAT_500 =
        "<html><head><title>Apache Tomcat/5.5.23 - Error report</title></head><body>"
        + "<h1>HTTP Status 500 - </h1><hr/><p><b>exception</b></p><pre>java.lang.NullPointerException\n"
        + "\tcom.shopmaster.dao.OrderDAO.load(OrderDAO.java:212)\n"
        + "\tcom.shopmaster.web.FrontController.doGet(FrontController.java:88)\n"
        + "\tjavax.servlet.http.HttpServlet.service(HttpServlet.java:690)</pre>"
        + "<hr/><h3>Apache Tomcat/5.5.23</h3></body></html>";

    @Inject
    AuthStore auth;
    @Inject
    RateLimiter limiter;

    @ConfigProperty(name = "shop.chaos.error-rate")
    double errorRate;
    @ConfigProperty(name = "shop.chaos.max-latency-ms")
    int maxLatencyMs;

    @Override
    public void filter(ContainerRequestContext ctx) {
        String path = ctx.getUriInfo().getPath();
        if (path.endsWith("/ping.do")) return;

        String key = "login";
        if (!path.endsWith("/login.do")) {
            String token = ctx.getHeaderString(SESSION_HEADER);
            if (token == null || token.isBlank()) {
                // Missing header -> HTML page
                ctx.abortWith(R.html(401, "<html><body><h1>Login required</h1></body></html>"));
                return;
            }
            AuthStore.Session s = auth.find(token.trim());
            if (s == null) {
                // Unknown / superseded token -> plain text 403
                ctx.abortWith(R.text(403, "Access Denied"));
                return;
            }
            if (s.expiresAtEpochSec() < System.currentTimeMillis() / 1000) {
                // Expired token -> JSON with a magic code
                ctx.abortWith(R.json(401, Map.of("err", "session expired", "code", 1002)));
                return;
            }
            key = s.token();
        }

        long waitMs = limiter.check(key);
        if (waitMs > 0) {
            // Non-standard retry header, plain text body, 503 instead of 429
            ctx.abortWith(Response.status(503).type("text/plain")
                .header("X-Retry-After-Ms", waitMs)
                .entity("Server busy. Try again later.").build());
            return;
        }

        ThreadLocalRandom rnd = ThreadLocalRandom.current();
        if (maxLatencyMs > 0) {
            try {
                Thread.sleep(rnd.nextInt(maxLatencyMs + 1));
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
        if (errorRate > 0 && rnd.nextDouble() < errorRate) {
            ctx.abortWith(R.html(500, TOMCAT_500));
        }
    }

    @Override
    public void filter(ContainerRequestContext req, ContainerResponseContext res) {
        res.getHeaders().putSingle("Server", "ShopMaster/2.1 (Apache-Coyote/1.1)");
        res.getHeaders().putSingle("X-Powered-By", "JSP/2.0");
        res.getHeaders().putSingle("Pragma", "no-cache");
    }
}
