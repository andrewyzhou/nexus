/**
 * src/db.js
 * Shared pg connection pool – import this everywhere instead of
 * creating multiple pools.
 */

require("dotenv").config();
const { Pool } = require("pg");

const pool = new Pool({
    connectionString: process.env.DATABASE_URL,
    // Keep a small pool; adjust for production load
    max: 10,
    idleTimeoutMillis: 30_000,
    connectionTimeoutMillis: 5_000,
});

pool.on("error", (err) => {
    console.error("Unexpected pg pool error:", err.message);
});

module.exports = pool;
