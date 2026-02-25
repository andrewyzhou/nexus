# Nexus Graph Platform – Task 4: Database & REST API

PostgreSQL + Node.js/Express backend for the Nexus Graph Platform.

## Architecture

```
Alex_Nexus_Task_4_Database/
├── docker-compose.yml       # PostgreSQL 16 container
├── .env                     # DB connection string & port
├── package.json
├── db/
│   ├── schema.sql           # Tables + indexes (auto-run on first Docker start)
│   └── seed.js              # 50 companies + ~150 relationships
├── src/
│   ├── index.js             # Express entry point
│   ├── db.js                # pg connection pool
│   └── routes/
│       └── companies.js     # All 3 GET endpoints
└── tests/
    └── api.test.js          # Jest + Supertest integration tests
```

## Quick Start

### 1. Start PostgreSQL (Docker required)

```bash
docker compose up -d
```

The schema (`db/schema.sql`) is applied automatically on the first start.

### 2. Install dependencies

```bash
npm install
```

### 3. Seed the database

```bash
npm run seed
# or: node db/seed.js
```

### 4. Start the API server

```bash
npm start
# Development (auto-reload):
npm run dev
```

Server starts on **http://localhost:3000**

---

## API Endpoints

### `GET /companies`
Returns all S&P 500-like companies, ordered by market cap (descending).

**Query Parameters**

| Param | Type | Example | Description |
|---|---|---|---|
| `sector` | string | `Technology` | Filter by sector (exact match) |
| `size` | string | `large`, `mid`, `small` | Filter by company size |

**Example**
```
GET /companies?sector=Technology&size=large
```

**Response**
```json
{
  "count": 4,
  "companies": [
    {
      "id": 1,
      "ticker": "MSFT",
      "name": "Microsoft Corporation",
      "sector": "Technology",
      "industry": "Software",
      "currency": "USD",
      "current_price": "415.20",
      "market_cap_b": "3080.00",
      "size": "large",
      "country": "USA",
      "created_at": "..."
    }
  ]
}
```

---

### `GET /companies/:id`
Returns metadata for a single company.

**Example**
```
GET /companies/1
```

**Response**: Single company object (same shape as above, without wrapper).

**Errors**: `404` if not found, `400` if id is non-numeric.

---

### `GET /companies/:id/neighbors`
Returns graph expansion data for a company.

**Query Parameters**

| Param | Type | Example | Description |
|---|---|---|---|
| `type` | string | `supplier`, `partner`, `competitor`, `investor` | Filter by relationship type |
| `size` | string | `large`, `mid`, `small` | Filter neighbors by size |

**Example**
```
GET /companies/1/neighbors?type=partner&size=large
```

**Response**
```json
{
  "nodes": [
    {
      "id": 1,
      "ticker": "MSFT",
      "name": "Microsoft Corporation",
      "sector": "Technology",
      "size": "large",
      "is_origin": true,
      ...
    },
    {
      "id": 3,
      "ticker": "NVDA",
      "name": "NVIDIA Corporation",
      "is_origin": false,
      ...
    }
  ],
  "edges": [
    {
      "id": 5,
      "source": 1,
      "target": 3,
      "type": "partner",
      "weight": "0.95"
    }
  ]
}
```

---

## Database Schema

### `companies`
| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | |
| `ticker` | VARCHAR(10) UNIQUE | e.g. `AAPL` |
| `name` | TEXT | |
| `sector` | TEXT | e.g. `Technology` |
| `industry` | TEXT | |
| `currency` | VARCHAR(5) | default `USD` |
| `current_price` | NUMERIC(12,2) | |
| `market_cap_b` | NUMERIC(12,2) | Market cap in billions |
| `size` | TEXT | `large` / `mid` / `small` |
| `country` | VARCHAR(50) | |
| `created_at` | TIMESTAMPTZ | |

**Indexes**: `ticker`, `sector`, `size`, `market_cap_b`

### `relationships`
| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | |
| `source_id` | INT FK | References companies |
| `target_id` | INT FK | References companies |
| `type` | TEXT | `supplier` / `partner` / `competitor` / `investor` |
| `weight` | NUMERIC(5,2) | Edge strength |
| `created_at` | TIMESTAMPTZ | |

**Indexes**: `source_id`, `target_id`, `type`, `(source_id, type)`, `(target_id, type)`  
**Constraint**: `UNIQUE(source_id, target_id, type)` – no duplicate directed edges.

---

## Running Tests

```bash
npm test
```

Requires Docker PostgreSQL to be running and data seeded.

The test suite covers:
- `GET /companies` – list, sector filter, size filter, combined filter
- `GET /companies/:id` – 200, 400, 404
- `GET /companies/:id/neighbors` – shape, filters, 400/404
- Unknown route 404

---

## Useful Commands

```bash
npm run db:up      # Start PostgreSQL container
npm run db:down    # Stop container
npm run db:reset   # Wipe volume and restart (fresh DB)
npm run seed       # Populate tables
npm start          # Run API
npm test           # Run tests
```

### Stopping the API Server

If you started the server with `npm start` or `node src/index.js` and need to kill it
from a **different terminal window** (or if `Ctrl+C` isn't available), run:

```bash
kill $(lsof -ti:3000)
```

**How it works:**

| Part | What it does |
|---|---|
| `lsof -ti:3000` | Lists all processes using port 3000, outputting only their PIDs (`-t` = terse, numbers only) |
| `$(...)` | Command substitution — runs the inner command and passes its output as an argument |
| `kill` | Sends `SIGTERM` (graceful shutdown signal) to each PID returned |

So the full command translates to: *"find the process ID of whatever is listening on port 3000, then kill it."*

---

## Live Demo

A recorded browser walkthrough of all API endpoints is available in `media/api_live_demo.webp`.
