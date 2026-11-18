package com.codebasics.legacyshop;

import jakarta.ws.rs.WebApplicationException;
import jakarta.ws.rs.core.Response;
import jakarta.ws.rs.ext.ExceptionMapper;
import jakarta.ws.rs.ext.Provider;
import org.jboss.logging.Logger;

@Provider
public class LegacyExceptionMapper implements ExceptionMapper<Exception> {
    private static final Logger LOG = Logger.getLogger(LegacyExceptionMapper.class);

    @Override
    public Response toResponse(Exception e) {
        if (e instanceof WebApplicationException w) return w.getResponse();
        LOG.error("Unhandled", e);
        return R.html(500, "<html><head><title>Apache Tomcat/5.5.23 - Error report</title></head><body>"
            + "<h1>HTTP Status 500 - </h1><pre>java.lang.RuntimeException: " + R.esc(String.valueOf(e.getMessage()))
            + "</pre></body></html>");
    }
}
