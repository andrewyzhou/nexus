/**
 * src/routes/companies.js
 * Route handlers for all /companies endpoints.
 */

const express = require("express");
const router = express.Router();
const pool = require("../db");

// ----------------------------------------------------------------
// Helper: build a safe WHERE clause from optional filter params
// ----------------------------------------------------------------
function buildFilters(allowed, query) {
    const conditions = [];
    const values = [];

    for (const [key, col] of Object.entries(allowed)) {
        if (query[key] !== undefined && query[key] !== "") {
            values.push(query[key]);
            conditions.push(`${col} = $${values.length}`);
        }
    }

    return {
        where: conditions.length ? "WHERE " + conditions.join(" AND ") : "",
        values,
    };
}

// ----------------------------------------------------------------
// GET /companies
// Returns all starting (S&P 500-like) companies.
// Query params:
//   sector  – exact match, e.g. "Technology"
//   size    – "large" | "mid" | "small"
// ----------------------------------------------------------------
router.get("/", async (req, res) => {
    try {
        const { where, values } = buildFilters(
            { sector: "sector", size: "size" },
            req.query
        );

        const sql = `
      SELECT
        id, ticker, name, sector, industry,
        currency, current_price, market_cap_b, size, country, created_at
      FROM companies
      ${where}
      ORDER BY market_cap_b DESC
    `;

        const { rows } = await pool.query(sql, values);
        res.json({ count: rows.length, companies: rows });
    } catch (err) {
        console.error("GET /companies error:", err.message);
        res.status(500).json({ error: "Internal server error" });
    }
});

// ----------------------------------------------------------------
// GET /companies/:id
// Returns metadata for a single company.
// ----------------------------------------------------------------
router.get("/:id", async (req, res) => {
    const id = parseInt(req.params.id, 10);
    if (isNaN(id)) return res.status(400).json({ error: "Invalid id" });

    try {
        const { rows } = await pool.query(
            `SELECT
         id, ticker, name, sector, industry,
         currency, current_price, market_cap_b, size, country, created_at
       FROM companies
       WHERE id = $1`,
            [id]
        );

        if (rows.length === 0) {
            return res.status(404).json({ error: `Company with id ${id} not found` });
        }

        res.json(rows[0]);
    } catch (err) {
        console.error(`GET /companies/${id} error:`, err.message);
        res.status(500).json({ error: "Internal server error" });
    }
});

// ----------------------------------------------------------------
// GET /companies/:id/neighbors
// Returns graph expansion data: { nodes, edges }
// Query params:
//   type  – relationship type: "supplier" | "partner" | "competitor" | "investor"
//   size  – filter neighbor companies by size: "large" | "mid" | "small"
// ----------------------------------------------------------------
router.get("/:id/neighbors", async (req, res) => {
    const id = parseInt(req.params.id, 10);
    if (isNaN(id)) return res.status(400).json({ error: "Invalid id" });

    try {
        // --- Verify the company exists ---
        const exists = await pool.query("SELECT id FROM companies WHERE id = $1", [id]);
        if (exists.rows.length === 0) {
            return res.status(404).json({ error: `Company with id ${id} not found` });
        }

        // --- Build dynamic filter conditions ---
        const conditions = [];
        const values = [id];

        if (req.query.type) {
            values.push(req.query.type);
            conditions.push(`r.type = $${values.length}`);
        }

        if (req.query.size) {
            values.push(req.query.size);
            conditions.push(`neighbor.size = $${values.length}`);
        }

        const extraWhere = conditions.length ? "AND " + conditions.join(" AND ") : "";

        // Fetch all edges where our company is source OR target,
        // joining neighbor company data for filtering and embedding in nodes.
        const edgeSql = `
      SELECT
        r.id        AS edge_id,
        r.source_id,
        r.target_id,
        r.type,
        r.weight,
        neighbor.id           AS neighbor_id,
        neighbor.ticker       AS neighbor_ticker,
        neighbor.name         AS neighbor_name,
        neighbor.sector       AS neighbor_sector,
        neighbor.industry     AS neighbor_industry,
        neighbor.currency     AS neighbor_currency,
        neighbor.current_price AS neighbor_price,
        neighbor.market_cap_b AS neighbor_mcap,
        neighbor.size         AS neighbor_size,
        neighbor.country      AS neighbor_country
      FROM relationships r
      JOIN companies neighbor
        ON neighbor.id = CASE
             WHEN r.source_id = $1 THEN r.target_id
             ELSE r.source_id
           END
      WHERE (r.source_id = $1 OR r.target_id = $1)
        ${extraWhere}
      ORDER BY r.weight DESC
    `;

        const { rows } = await pool.query(edgeSql, values);

        // --- Build unique nodes set (includes the origin node) ---
        const nodeMap = new Map();

        // Add the origin company itself
        const origin = exists.rows[0];
        // Fetch full data for origin
        const originFull = await pool.query(
            `SELECT id, ticker, name, sector, industry, currency,
              current_price, market_cap_b, size, country
       FROM companies WHERE id = $1`,
            [id]
        );
        if (originFull.rows.length > 0) {
            const o = originFull.rows[0];
            nodeMap.set(o.id, {
                id: o.id,
                ticker: o.ticker,
                name: o.name,
                sector: o.sector,
                industry: o.industry,
                currency: o.currency,
                current_price: o.current_price,
                market_cap_b: o.market_cap_b,
                size: o.size,
                country: o.country,
                is_origin: true,
            });
        }

        const edges = [];

        for (const row of rows) {
            // Add neighbor node
            if (!nodeMap.has(row.neighbor_id)) {
                nodeMap.set(row.neighbor_id, {
                    id: row.neighbor_id,
                    ticker: row.neighbor_ticker,
                    name: row.neighbor_name,
                    sector: row.neighbor_sector,
                    industry: row.neighbor_industry,
                    currency: row.neighbor_currency,
                    current_price: row.neighbor_price,
                    market_cap_b: row.neighbor_mcap,
                    size: row.neighbor_size,
                    country: row.neighbor_country,
                    is_origin: false,
                });
            }

            edges.push({
                id: row.edge_id,
                source: row.source_id,
                target: row.target_id,
                type: row.type,
                weight: row.weight,
            });
        }

        res.json({
            nodes: Array.from(nodeMap.values()),
            edges,
        });
    } catch (err) {
        console.error(`GET /companies/${id}/neighbors error:`, err.message);
        res.status(500).json({ error: "Internal server error" });
    }
});

module.exports = router;
