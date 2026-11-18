package com.codebasics.legacyshop;

import io.quarkus.runtime.StartupEvent;
import jakarta.enterprise.event.Observes;
import jakarta.inject.Singleton;
import org.eclipse.microprofile.config.inject.ConfigProperty;
import org.jboss.logging.Logger;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.locks.ReentrantLock;

/** Plain JDBC + SQLite. One connection per call, one global write lock. Very 2009. */
@Singleton
public class Db {
    private static final Logger LOG = Logger.getLogger(Db.class);

    @ConfigProperty(name = "shop.db.path")
    String path;

    /** SQLite hates concurrent writers, so every mutation takes this lock. */
    final ReentrantLock writeLock = new ReentrantLock();

    void onStart(@Observes StartupEvent ev) throws Exception {
        Class.forName("org.sqlite.JDBC");
        Path p = Path.of(path).toAbsolutePath();
        Files.createDirectories(p.getParent());
        try (Connection c = open(); Statement st = c.createStatement()) {
            st.execute("PRAGMA journal_mode=WAL");
            for (String ddl : Seeder.SCHEMA) st.execute(ddl);
        }
        try (Connection c = open()) {
            long n = ((Number) queryOn(c, "SELECT COUNT(*) AS n FROM PRODUCTS").get(0).get("n")).longValue();
            if (n == 0) {
                LOG.info("Empty database, seeding dirty legacy data...");
                Seeder.seed(c);
                LOG.info("Seeded.");
            }
        }
        LOG.infof("ShopMaster 2.1 ready. DB at %s", p);
    }

    Connection open() throws SQLException {
        Connection c = DriverManager.getConnection("jdbc:sqlite:" + path);
        try (Statement s = c.createStatement()) {
            s.execute("PRAGMA busy_timeout=5000");
        }
        return c;
    }

    List<Map<String, Object>> query(String sql, Object... params) {
        try (Connection c = open()) {
            return queryOn(c, sql, params);
        } catch (SQLException e) {
            throw new RuntimeException(e);
        }
    }

    static List<Map<String, Object>> queryOn(Connection c, String sql, Object... params) throws SQLException {
        try (PreparedStatement ps = c.prepareStatement(sql)) {
            for (int i = 0; i < params.length; i++) ps.setObject(i + 1, params[i]);
            try (ResultSet rs = ps.executeQuery()) {
                ResultSetMetaData md = rs.getMetaData();
                List<Map<String, Object>> out = new ArrayList<>();
                while (rs.next()) {
                    Map<String, Object> row = new LinkedHashMap<>();
                    for (int i = 1; i <= md.getColumnCount(); i++) row.put(md.getColumnLabel(i), rs.getObject(i));
                    out.add(row);
                }
                return out;
            }
        }
    }

    static int updateOn(Connection c, String sql, Object... params) throws SQLException {
        try (PreparedStatement ps = c.prepareStatement(sql)) {
            for (int i = 0; i < params.length; i++) ps.setObject(i + 1, params[i]);
            return ps.executeUpdate();
        }
    }
}
