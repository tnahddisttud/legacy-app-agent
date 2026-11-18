package com.codebasics.legacyshop;

import java.sql.Connection;
import java.sql.SQLException;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.Locale;
import java.util.Random;

/** Generates deliberately inconsistent data. Seeded Random => same mess every time. */
final class Seeder {
    private Seeder() {}

    static final String[] SCHEMA = {
        "CREATE TABLE IF NOT EXISTS PRODUCTS(PROD_ID INTEGER PRIMARY KEY, SKU TEXT, PROD_NAME TEXT, DESCR TEXT, PRICE TEXT, "
            + "CATEGORY TEXT, IN_STOCK TEXT, QTY_ON_HAND INTEGER, LAST_UPD TEXT, WEIGHT TEXT, DISCONTINUED TEXT)",
        "CREATE TABLE IF NOT EXISTS CUSTOMERS(CUST_NO INTEGER PRIMARY KEY, FNAME TEXT, LNAME TEXT, EMAIL TEXT, PHONE TEXT, "
            + "ACTIVE TEXT, CREATED TEXT, ADDR1 TEXT, CITY TEXT, STATE TEXT, ZIP TEXT, NOTES TEXT)",
        "CREATE TABLE IF NOT EXISTS ORDERS(ORDER_NO TEXT PRIMARY KEY, CUST_NO INTEGER, ORDER_DATE TEXT, STATUS INTEGER, "
            + "TOTAL TEXT, NOTES TEXT)",
        "CREATE TABLE IF NOT EXISTS ORDER_LINES(ORDER_NO TEXT, LINE_NO INTEGER, SKU TEXT, QTY TEXT, UNIT_PRICE TEXT)"
    };

    private static final String[] NAMES = {
        "Wireless Mouse", "USB-C Cable 2m", "Mechanical Keyboard", "27in Monitor", "Desk Lamp", "Garden Hose 25ft",
        "Cordless Drill", "Yoga Mat", "Water Bottle 1L", "Board Game: Space Traders", "Brick Set City 500pc",
        "Running Shoes", "Coffee Maker", "Blender Pro 900", "Bluetooth Speaker", "Notebook A5 (3-pack)",
        "Backpack 30L", "Phone Case", "Webcam 1080p", "Office Chair"
    };
    private static final String[] CATS = {
        "Electronics", "Electronics", "Electronics", "Electronics", "Home & Garden", "Home & Garden",
        "Tools", "Sports", "Sports", "Toys", "Toys", "Sports", "Kitchen", "Kitchen", "Electronics",
        "Office", "Office", "Electronics", "Electronics", "Office"
    };
    private static final String[] SUFFIX = {"", " - v2", " (Black)", " (White)", " XL", " Deluxe"};
    private static final String[] FIRST = {"John", "Maria", "Wei", "Aisha", "Carlos", "Priya", "Liam", "Sofia", "Noah",
        "Emma", "Raj", "Hana", "Omar", "Olivia", "Ethan"};
    private static final String[] LAST = {"Smith", "Garcia", "Chen", "Khan", "Lopez", "Patel", "OBrien", "Rossi", "Kim",
        "Nguyen", "Johnson", "Tanaka", "Haddad", "Brown", "Silva"};
    private static final String[] STREETS = {"Main St", "Oak Ave", "Maple Dr", "Elm St", "Park Blvd"};
    private static final String[][] TOWNS = {
        {"Boston", "MA", "02134"}, {"Austin", "TX", "78701"}, {"Seattle", "WA", "98101"},
        {"Newark", "NJ", "07102"}, {"Denver", "CO", "80202"}, {"Portland", "ME", "04101"}
    };

    static final int PRODUCTS = 60;
    static final int CUSTOMERS = 30;
    static final int ORDERS = 40;

    static void seed(Connection c) throws SQLException {
        Random r = new Random(42);
        c.setAutoCommit(false);
        int[] cents = new int[PRODUCTS];
        String[] skus = new String[PRODUCTS];

        for (int i = 0; i < PRODUCTS; i++) {
            int base = i % 20;
            String name = NAMES[base] + (i < 20 ? "" : SUFFIX[1 + r.nextInt(SUFFIX.length - 1)]);
            String sku = "SKU-" + (1001 + i);
            if (i == 47) sku = "SKU-1004"; // duplicate SKU on purpose
            int k = r.nextInt(10);
            if (k == 0) sku = sku.toLowerCase();
            else if (k == 1) sku = sku + " ";
            String price = dirtyPrice(r, 499 + r.nextInt(40000));
            Integer parsed = Money.parseCents(price);
            cents[i] = parsed == null ? -1 : parsed;
            skus[i] = sku.trim().toUpperCase();

            int qty = r.nextInt(5) == 0 ? 0 : 5 + r.nextInt(80);
            boolean flag = qty > 0;
            if (r.nextInt(4) == 0) flag = !flag; // 25% of flags disagree with reality
            String[] yes = {"Y", "1", "true", "yes", "Y", "Y"};
            String[] no = {"N", "0", "false", "no", "N", "N", ""};
            String inStock = flag ? yes[r.nextInt(yes.length)] : no[r.nextInt(no.length)];

            String descr;
            switch (r.nextInt(4)) {
                case 0: descr = "<b>" + name + "</b><br>Great value!\r\nCall 1-800-SHOPMSTR"; break;
                case 1: descr = null; break;
                default: descr = name + " - quality guaranteed.";
            }
            String[] weights = {"1.2kg", "500 g", "2.5 lb", null};
            String disc = r.nextInt(12) == 0 ? "Y" : null;
            LocalDate d = LocalDate.of(2019, 1, 1).plusDays(r.nextInt(2000));

            Db.updateOn(c, "INSERT INTO PRODUCTS VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                i + 1, sku, name, descr, price, dirtyCat(r, CATS[base]), inStock, qty,
                dirtyDate(r, d), weights[r.nextInt(weights.length)], disc);
        }

        for (int i = 0; i < CUSTOMERS; i++) {
            String f = FIRST[i % 15];
            String l = LAST[(i * 7 + 3) % 15];
            String fname = f, lname = l;
            int k = r.nextInt(10);
            if (k == 0) { fname = f.toUpperCase(); lname = l.toUpperCase(); }
            else if (k == 1) { fname = l + ", " + f; lname = null; }

            String email = (f + "." + l).toLowerCase() + i + "@example.com";
            switch (r.nextInt(10)) {
                case 6: case 7: email = email.toUpperCase(); break;
                case 8: email = "  " + email + " "; break;
                case 9: email = (i % 2 == 0) ? null : "n/a"; break;
                default: break;
            }
            int n = 1000 + r.nextInt(9000);
            String[] phones = {
                String.format("(555) 010-%04d", n), String.format("555.010.%04d", n), String.format("555010%04d", n),
                String.format("+1 555 010 %04d", n), String.format("555-010-%04d", n), null
            };
            String[] actives = {"Y", "Y", "Y", "Y", "Y", "1", "1", "N", "0", null};
            String[] town = TOWNS[r.nextInt(TOWNS.length)];
            String zip = r.nextBoolean() ? String.valueOf(Integer.parseInt(town[2])) : town[2]; // leading zeros lost
            String[] notes = {null, null, "VIP", "DO NOT CALL", "see acct #" + (100 + i)};

            Db.updateOn(c, "INSERT INTO CUSTOMERS VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                i + 1, fname, lname, email, phones[r.nextInt(phones.length)], actives[r.nextInt(actives.length)],
                dirtyDate(r, LocalDate.of(2015, 1, 1).plusDays(r.nextInt(3000))),
                (100 + r.nextInt(900)) + " " + STREETS[r.nextInt(STREETS.length)],
                town[0], town[1], zip, notes[r.nextInt(notes.length)]);
        }

        int[] statuses = {0, 1, 1, 2, 2, 3, 3, 3, 9};
        for (int o = 0; o < ORDERS; o++) {
            String orderNo = String.format("ORD-%06d", o + 1);
            int nLines = 1 + r.nextInt(3);
            long total = 0;
            int lineNo = 0;
            java.util.List<Object[]> lines = new java.util.ArrayList<>();
            for (int j = 0; j < nLines; j++) {
                int idx = r.nextInt(PRODUCTS);
                if (cents[idx] < 0) continue;
                int qty = 1 + r.nextInt(3);
                total += (long) cents[idx] * qty;
                lines.add(new Object[]{orderNo, ++lineNo, skus[idx], String.valueOf(qty), Money.fmt(cents[idx])});
            }
            if (lines.isEmpty()) continue;
            String totalStr = r.nextInt(5) == 0 ? Money.fmt(total) + "00" : Money.fmt(total);
            int status = (o == 17) ? 7 : statuses[r.nextInt(statuses.length)]; // 7 = "HOLD (do not use)"
            Db.updateOn(c, "INSERT INTO ORDERS VALUES (?,?,?,?,?,?)", orderNo, 1 + r.nextInt(CUSTOMERS),
                dirtyDate(r, LocalDate.of(2023, 1, 1).plusDays(r.nextInt(700))), status, totalStr, null);
            for (Object[] line : lines) Db.updateOn(c, "INSERT INTO ORDER_LINES VALUES (?,?,?,?,?)", line);
        }
        c.commit();
        c.setAutoCommit(true);
    }

    private static String dirtyPrice(Random r, int cents) {
        double v = cents / 100.0;
        switch (r.nextInt(10)) {
            case 0: return String.format(Locale.US, "$%.2f", v);
            case 1: return String.format(Locale.US, "%,.2f", v);
            case 2: return String.format(Locale.US, "%.2f ", v);
            case 3: return r.nextInt(3) == 0 ? "N/A" : String.format(Locale.US, "%.2f", v);
            default: return String.format(Locale.US, "%.2f", v);
        }
    }

    private static String dirtyCat(Random r, String c) {
        int k = r.nextInt(10);
        if (k < 5) return c;
        if (k <= 6) return c.toLowerCase();
        if (k == 7) return c.toUpperCase() + " ";
        if (k == 8) return null;
        return c.replace(" & ", "-").toLowerCase();
    }

    private static String dirtyDate(Random r, LocalDate d) {
        switch (r.nextInt(4)) {
            case 0: return d.toString();
            case 1: return d.format(DateTimeFormatter.ofPattern("MM/dd/yyyy"));
            case 2: return d.format(DateTimeFormatter.ofPattern("dd-MMM-yyyy", Locale.US));
            default: return String.valueOf(d.atStartOfDay(ZoneOffset.UTC).toEpochSecond());
        }
    }
}
