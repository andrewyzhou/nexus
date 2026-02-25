/**
 * tests/api.test.js
 * Jest + Supertest integration tests for the Nexus Graph API.
 *
 * Prerequisites:
 *   - Docker PostgreSQL running (`docker compose up -d`)
 *   - DB seeded (`node db/seed.js`)
 *   - DATABASE_URL set via .env
 */

const request = require("supertest");
const app = require("../src/index");
const pool = require("../src/db");

// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────
let firstCompanyId;

beforeAll(async () => {
    // Grab the id of the first company (highest market cap) for neighbour tests
    const { rows } = await pool.query(
        "SELECT id FROM companies ORDER BY market_cap_b DESC LIMIT 1"
    );
    if (rows.length === 0) throw new Error("No companies found – run db/seed.js first");
    firstCompanyId = rows[0].id;
});

afterAll(async () => {
    await pool.end();
});

// ─────────────────────────────────────────────────────────────
// Health Check
// ─────────────────────────────────────────────────────────────
describe("GET /health", () => {
    it("returns 200 with status ok", async () => {
        const res = await request(app).get("/health");
        expect(res.status).toBe(200);
        expect(res.body).toMatchObject({ status: "ok" });
    });
});

// ─────────────────────────────────────────────────────────────
// GET /companies
// ─────────────────────────────────────────────────────────────
describe("GET /companies", () => {
    it("returns 200 and a list of companies", async () => {
        const res = await request(app).get("/companies");
        expect(res.status).toBe(200);
        expect(res.body).toHaveProperty("count");
        expect(res.body).toHaveProperty("companies");
        expect(Array.isArray(res.body.companies)).toBe(true);
        expect(res.body.companies.length).toBeGreaterThan(0);
        expect(res.body.count).toBe(res.body.companies.length);
    });

    it("each company has required fields", async () => {
        const res = await request(app).get("/companies");
        const company = res.body.companies[0];
        expect(company).toHaveProperty("id");
        expect(company).toHaveProperty("ticker");
        expect(company).toHaveProperty("name");
        expect(company).toHaveProperty("sector");
        expect(company).toHaveProperty("industry");
        expect(company).toHaveProperty("currency");
        expect(company).toHaveProperty("current_price");
        expect(company).toHaveProperty("market_cap_b");
        expect(company).toHaveProperty("size");
        expect(company).toHaveProperty("country");
    });

    it("filters by sector", async () => {
        const sector = "Technology";
        const res = await request(app).get(`/companies?sector=${sector}`);
        expect(res.status).toBe(200);
        expect(res.body.companies.length).toBeGreaterThan(0);
        for (const c of res.body.companies) {
            expect(c.sector).toBe(sector);
        }
    });

    it("filters by size=large", async () => {
        const res = await request(app).get("/companies?size=large");
        expect(res.status).toBe(200);
        expect(res.body.companies.length).toBeGreaterThan(0);
        for (const c of res.body.companies) {
            expect(c.size).toBe("large");
        }
    });

    it("filters by size=mid", async () => {
        const res = await request(app).get("/companies?size=mid");
        expect(res.status).toBe(200);
        for (const c of res.body.companies) {
            expect(c.size).toBe("mid");
        }
    });

    it("combines sector and size filters", async () => {
        const res = await request(app).get("/companies?sector=Energy&size=large");
        expect(res.status).toBe(200);
        for (const c of res.body.companies) {
            expect(c.sector).toBe("Energy");
            expect(c.size).toBe("large");
        }
    });

    it("returns empty array for a non-existent sector", async () => {
        const res = await request(app).get("/companies?sector=GhostSector");
        expect(res.status).toBe(200);
        expect(res.body.companies).toHaveLength(0);
        expect(res.body.count).toBe(0);
    });
});

// ─────────────────────────────────────────────────────────────
// GET /companies/:id
// ─────────────────────────────────────────────────────────────
describe("GET /companies/:id", () => {
    it("returns 200 and company data for a valid id", async () => {
        const res = await request(app).get(`/companies/${firstCompanyId}`);
        expect(res.status).toBe(200);
        expect(res.body).toHaveProperty("id", firstCompanyId);
        expect(res.body).toHaveProperty("ticker");
        expect(res.body).toHaveProperty("name");
    });

    it("returns 404 for a non-existent id", async () => {
        const res = await request(app).get("/companies/999999");
        expect(res.status).toBe(404);
        expect(res.body).toHaveProperty("error");
    });

    it("returns 400 for a non-numeric id", async () => {
        const res = await request(app).get("/companies/abc");
        expect(res.status).toBe(400);
        expect(res.body).toHaveProperty("error");
    });
});

// ─────────────────────────────────────────────────────────────
// GET /companies/:id/neighbors
// ─────────────────────────────────────────────────────────────
describe("GET /companies/:id/neighbors", () => {
    it("returns 200 with { nodes, edges } structure", async () => {
        const res = await request(app).get(`/companies/${firstCompanyId}/neighbors`);
        expect(res.status).toBe(200);
        expect(res.body).toHaveProperty("nodes");
        expect(res.body).toHaveProperty("edges");
        expect(Array.isArray(res.body.nodes)).toBe(true);
        expect(Array.isArray(res.body.edges)).toBe(true);
    });

    it("includes the origin node in nodes", async () => {
        const res = await request(app).get(`/companies/${firstCompanyId}/neighbors`);
        expect(res.status).toBe(200);
        const origin = res.body.nodes.find((n) => n.id === firstCompanyId);
        expect(origin).toBeDefined();
        expect(origin.is_origin).toBe(true);
    });

    it("each node has required fields", async () => {
        const res = await request(app).get(`/companies/${firstCompanyId}/neighbors`);
        for (const node of res.body.nodes) {
            expect(node).toHaveProperty("id");
            expect(node).toHaveProperty("ticker");
            expect(node).toHaveProperty("name");
            expect(node).toHaveProperty("sector");
            expect(node).toHaveProperty("size");
        }
    });

    it("each edge has required fields", async () => {
        const res = await request(app).get(`/companies/${firstCompanyId}/neighbors`);
        for (const edge of res.body.edges) {
            expect(edge).toHaveProperty("id");
            expect(edge).toHaveProperty("source");
            expect(edge).toHaveProperty("target");
            expect(edge).toHaveProperty("type");
            expect(edge).toHaveProperty("weight");
        }
    });

    it("filters edges by type=partner", async () => {
        const res = await request(app).get(
            `/companies/${firstCompanyId}/neighbors?type=partner`
        );
        expect(res.status).toBe(200);
        for (const edge of res.body.edges) {
            expect(edge.type).toBe("partner");
        }
    });

    it("filters edges by type=competitor", async () => {
        const res = await request(app).get(
            `/companies/${firstCompanyId}/neighbors?type=competitor`
        );
        expect(res.status).toBe(200);
        for (const edge of res.body.edges) {
            expect(edge.type).toBe("competitor");
        }
    });

    it("filters neighbor nodes by size=large", async () => {
        const res = await request(app).get(
            `/companies/${firstCompanyId}/neighbors?size=large`
        );
        expect(res.status).toBe(200);
        // All non-origin neighbor nodes must be large
        const neighbors = res.body.nodes.filter((n) => !n.is_origin);
        for (const n of neighbors) {
            expect(n.size).toBe("large");
        }
    });

    it("returns 404 for a non-existent company", async () => {
        const res = await request(app).get("/companies/999999/neighbors");
        expect(res.status).toBe(404);
        expect(res.body).toHaveProperty("error");
    });

    it("returns 400 for a non-numeric id", async () => {
        const res = await request(app).get("/companies/abc/neighbors");
        expect(res.status).toBe(400);
        expect(res.body).toHaveProperty("error");
    });
});

// ─────────────────────────────────────────────────────────────
// 404 Route
// ─────────────────────────────────────────────────────────────
describe("Unknown routes", () => {
    it("returns 404 for unknown routes", async () => {
        const res = await request(app).get("/unknown-route");
        expect(res.status).toBe(404);
    });
});
