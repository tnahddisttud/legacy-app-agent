package com.codebasics.legacyshop;

import java.math.BigDecimal;
import java.math.RoundingMode;

final class Money {
    private Money() {}

    /** "19.99", "$24.50", " 1,299.00 " -> cents. Returns null for junk like "N/A" or "". */
    static Integer parseCents(String raw) {
        if (raw == null) return null;
        String s = raw.replace("$", "").replace(",", "").trim();
        if (s.isEmpty()) return null;
        try {
            return new BigDecimal(s).setScale(2, RoundingMode.HALF_UP).movePointRight(2).intValueExact();
        } catch (ArithmeticException | NumberFormatException e) {
            return null;
        }
    }

    static String fmt(long cents) {
        return String.format("%d.%02d", cents / 100, cents % 100);
    }
}
