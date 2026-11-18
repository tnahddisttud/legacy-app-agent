package com.codebasics.legacyshop;

import jakarta.inject.Singleton;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/** One shared service account, one live session at a time. Logging in again kills the old token. */
@Singleton
public class AuthStore {
    public record Session(String token, String user, long expiresAtEpochSec) {}

    @ConfigProperty(name = "shop.auth.user")
    String user;
    @ConfigProperty(name = "shop.auth.password")
    String password;
    @ConfigProperty(name = "shop.auth.token-ttl-sec")
    long ttlSec;

    private final Map<String, Session> sessions = new ConcurrentHashMap<>();

    public synchronized Session login(String u, String p) {
        if (u == null || p == null || !user.equals(u) || !password.equals(p)) return null;
        sessions.values().removeIf(s -> s.user().equals(u));
        Session s = new Session(UUID.randomUUID().toString().replace("-", "").toUpperCase(), u,
            Instant.now().getEpochSecond() + ttlSec);
        sessions.put(s.token(), s);
        return s;
    }

    public Session find(String token) {
        return sessions.get(token);
    }
}
