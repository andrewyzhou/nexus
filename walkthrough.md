# Task 4: Database & REST API – Walkthrough

## What Was Built

A full PostgreSQL + Node.js/Express backend for the Nexus Graph Platform.

## Project Structure

```
Alex_Nexus_Task_4_Database/
├── docker-compose.yml       → PostgreSQL 16 container
├── .env                     → DB URL & port config
├── package.json             → Dependencies + npm scripts
├── db/
│   ├── schema.sql           → companies + relationships tables + 9 indexes
│   └── seed.js              → 48 S&P 500-like companies + 106 relationships
├── src/
│   ├── index.js             → Express server
│   ├── db.js                → pg connection pool
│   └── routes/companies.js  → All 3 GET endpoints
└── tests/
    └── api.test.js          → 21 Jest + Supertest tests
```

## Database

### Schema

**`companies`** – 4 indexes covering `ticker`, `sector`, `size`, `market_cap_b`

**`relationships`** – Unique constraint on `(source_id, target_id, type)` prevents duplicate edges; 5 indexes covering `source_id`, `target_id`, `type`, and compound combinations for fast graph traversal

### Seeded Data

| Metric | Value |
|---|---|
| Companies | 48 |
| Sectors covered | 10 |
| Relationships | 106 |
| Relationship types | supplier, partner, competitor, investor |

## API Endpoints

| Endpoint | Filters Supported |
|---|---|
| `GET /companies` | `?sector=`, `?size=` |
| `GET /companies/:id` | — |
| `GET /companies/:id/neighbors` | `?type=`, `?size=` |

`/neighbors` returns `{ nodes: [...], edges: [...] }` — the origin company is always included in `nodes` with `is_origin: true`.

## Test Results

```
PASS  tests/api.test.js

  GET /health
    ✓ returns 200 with status ok

  GET /companies
    ✓ returns 200 and a list of companies
    ✓ each company has required fields
    ✓ filters by sector
    ✓ filters by size=large
    ✓ filters by size=mid
    ✓ combines sector and size filters
    ✓ returns empty array for a non-existent sector

  GET /companies/:id
    ✓ returns 200 and company data for a valid id
    ✓ returns 404 for a non-existent id
    ✓ returns 400 for a non-numeric id

  GET /companies/:id/neighbors
    ✓ returns 200 with { nodes, edges } structure
    ✓ includes the origin node in nodes
    ✓ each node has required fields
    ✓ each edge has required fields
    ✓ filters edges by type=partner
    ✓ filters edges by type=competitor
    ✓ filters neighbor nodes by size=large
    ✓ returns 404 for a non-existent company
    ✓ returns 400 for a non-numeric id

  Unknown routes
    ✓ returns 404 for unknown routes

Tests:  21 passed, 21 total   Time: 0.649 s
```

## To Re-run

```bash
# Start Postgres (if not running)
npm run db:up

# Seed (first time setup or after db:reset)
npm run seed

# Run tests
npm test

# Start API server
npm start
```
