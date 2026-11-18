package com.codebasics.legacyshop;

import jakarta.inject.Singleton;
import org.eclipse.microprofile.config.inject.ConfigProperty;

import java.util.HashMap;
import java.util.Map;

/** Fixed-window limiter, keyed by session token. */
@Singleton
public class RateLimiter {
    @ConfigProperty(name = "shop.rate.max")
    int max;
    @ConfigProperty(name = "shop.rate.window-sec")
    int windowSec;

    private final Map<String, long[]> windows = new HashMap<>();

    /** @return 0 if allowed, otherwise milliseconds until the window resets. */
    public synchronized long check(String key) {
        long now = System.currentTimeMillis();
        long w = windowSec * 1000L;
        long[] b = windows.computeIfAbsent(key, k -> new long[]{now, 0});
        if (now - b[0] >= w) {
            b[0] = now;
            b[1] = 0;
        }
        if (b[1] >= max) return Math.max(1, b[0] + w - now);
        b[1]++;
        return 0;
    }
}
