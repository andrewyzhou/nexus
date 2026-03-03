# Task 6a — Backend Team (6 people)

Build the real data pipeline: scrape S&P 500 company data and seed it into the database.

| | |
|---|---|
| **Prerequisites** | Tasks 4-5 complete (DB schema + REST API with dummy data working) |
| **Depends on** | Task 6b (AI team) for `edges.json` — but scraper + DB work can proceed in parallel |
| **Produces** | `scraper/data/processed/nodes.json` (consumed by AI team for edge generation) |
| **Consumes** | `scraper/data/processed/edges.json` (produced by AI team) |

## Team Split

| Sub-team | People | Focus |
|----------|--------|-------|
| Scraper | 3 | Yahoo Finance scraper + data cleaning |
| DB/API | 3 | Schema refinement, seed script, API endpoints |

---

## Scraper Sub-team (3 people)

**Goal:** Build a Yahoo Finance scraper that collects metadata for all S&P 500 companies and outputs clean, normalized JSON.

**Files to create/modify:**

| File | Purpose |
|------|---------|
| `scraper/tickers/sp500.txt` | One ticker per line, ~500 tickers |
| `scraper/scraper.py` | Main scraper (replace existing stub) |
| `scraper/data/raw/<ticker>.json` | Raw per-company JSON (one file per ticker) |
| `scraper/data/processed/nodes.json` | Cleaned/normalized array of all companies |

### Step 1: Ticker List

Create `scraper/tickers/sp500.txt` with all current S&P 500 tickers, one per line. Source: Wikipedia S&P 500 list or any reliable source. Alphabetically sorted.

```
AAPL
ABBV
ABT
...
```

### Step 2: Yahoo Finance Scraper (`scraper/scraper.py`)

Scrape the following fields for each ticker from Yahoo Finance:

| Field | Type | Example |
|-------|------|---------|
| `ticker` | string | `"AAPL"` |
| `name` | string | `"Apple Inc."` |
| `sector` | string | `"Technology"` |
| `industry` | string | `"Consumer Electronics"` |
| `market_cap` | number | `2890000000000` (raw USD) |
| `price` | number | `178.52` |
| `change_percent` | number | `-1.23` |
| `employees` | number | `164000` |
| `description` | string | Company business summary |
| `pe_ratio` | number | Trailing P/E ratio |
| `pb_ratio` | number | Price-to-book ratio |
| `ps_ratio` | number | Price-to-sales ratio |
| `beta` | number | Stock beta |
| `profit_margin` | number | As decimal (e.g. `0.25` for 25%) |
| `institutional_holdings` | number | As decimal (e.g. `0.60` for 60%) |
| `short_ratio` | number | Short interest ratio |
| `week52_change` | number | 52-week price change as decimal |

**Implementation requirements:**

- Use `requests` + `BeautifulSoup` or `yfinance` library
- Rate limiting: minimum 1-2 second delay between requests to avoid blocks
- Retry logic: retry failed requests up to 3 times with exponential backoff
- Handle missing data gracefully: use `null` for unavailable fields, never crash
- Save raw response per ticker to `scraper/data/raw/<TICKER>.json`
- Log progress (e.g. `"Scraped 47/503: AAPL — success"`)
- Support resuming: skip tickers that already have raw JSON files (unless `--force` flag)
- CLI usage: `python scraper.py [--force] [--ticker AAPL]`

### Step 3: Data Cleaning → `nodes.json`

After scraping, produce `scraper/data/processed/nodes.json`. This can be done in `scraper.py` as a post-processing step, or in `scraper/preprocess.py`.

**`nodes.json` format** — JSON array of objects:

```json
[
  {
    "id": "AAPL",
    "ticker": "AAPL",
    "name": "Apple Inc.",
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "market_cap": 2890000000000,
    "price": 178.52,
    "change_percent": -1.23,
    "employees": 164000,
    "description": "Apple Inc. designs, manufactures, and markets...",
    "financial_metrics": {
      "pe_ratio": 28.5,
      "pb_ratio": 45.2,
      "ps_ratio": 7.8,
      "beta": 1.29,
      "profit_margin": 0.253,
      "institutional_holdings": 0.604,
      "short_ratio": 1.45,
      "week52_change": 0.32
    }
  }
]
```

**Cleaning rules:**

- `id` = ticker (use ticker as the unique identifier)
- Numeric fields: convert strings like `"2.89T"` to raw numbers, strip commas/symbols
- Null handling: keep `null` for missing values, do not invent defaults
- Validate: `market_cap > 0`, `price > 0` (drop rows that fail basic sanity checks)
- Sort array alphabetically by ticker

### Step 4: Testing

- Test with a small set first (e.g. 5 tickers) before running full scrape
- Verify `nodes.json` is valid JSON and parseable
- Spot-check 5-10 companies against Yahoo Finance manually
- Ensure no ticker is duplicated in output

---

## DB/API Sub-team (3 people)

**Goal:** Refine the database schema, write the seed script, and update API endpoints to serve real data.

**Files to create/modify:**

| File | Purpose |
|------|---------|
| `backend/models/company.py` | Update SQLAlchemy model to match scraped fields |
| `backend/models/relationship.py` | Update relationship model |
| `backend/db/init.py` | Database initialization |
| `backend/db/seed.py` | Seed script (replace stub) |
| `backend/routes/companies.py` | Refine endpoints |
| `backend/routes/relationships.py` | Refine endpoints |
| `backend/routes/graph.py` | Refine graph endpoint |

### Step 1: Refine the Company Schema

Update `backend/models/company.py` to match the `nodes.json` structure:

**Table: `companies`**

| Column | Type | Notes |
|--------|------|-------|
| `id` | VARCHAR | PRIMARY KEY (= ticker) |
| `ticker` | VARCHAR | UNIQUE NOT NULL |
| `name` | VARCHAR | NOT NULL |
| `sector` | VARCHAR | |
| `industry` | VARCHAR | |
| `market_cap` | BIGINT | |
| `price` | FLOAT | |
| `change_percent` | FLOAT | |
| `employees` | INTEGER | |
| `description` | TEXT | |
| `pe_ratio` | FLOAT | |
| `pb_ratio` | FLOAT | |
| `ps_ratio` | FLOAT | |
| `beta` | FLOAT | |
| `profit_margin` | FLOAT | |
| `institutional_holdings` | FLOAT | |
| `short_ratio` | FLOAT | |
| `week52_change` | FLOAT | |
| `created_at` | TIMESTAMP | DEFAULT NOW() |
| `updated_at` | TIMESTAMP | DEFAULT NOW() |

### Step 2: Refine the Relationship/Edge Schema

Update `backend/models/relationship.py` to match `edges.json`:

**Table: `relationships`**

| Column | Type | Notes |
|--------|------|-------|
| `id` | SERIAL | PRIMARY KEY |
| `source_id` | VARCHAR | REFERENCES companies(id) |
| `target_id` | VARCHAR | REFERENCES companies(id) |
| `relationship_type` | VARCHAR | NOT NULL — one of: `"industry_peer"`, `"financial_similarity"`, `"nlp_similarity"`, `"llm_relationship"` |
| `weight` | FLOAT | 0.0 to 1.0 (strength of relationship) |
| `metadata` | JSONB | Extra info, e.g. `{"subtype": "competitor"}` |
| `created_at` | TIMESTAMP | DEFAULT NOW() |

UNIQUE constraint on `(source_id, target_id, relationship_type)`.

### Step 3: Investment Tracks (discuss with full team)

Design how to represent "investment tracks" — curated groupings of companies by theme (e.g. "AI Leaders", "Green Energy", "Dividend Kings").

**Option A: Separate table (recommended)**

```
Table: investment_tracks
  id          SERIAL PRIMARY KEY
  name        VARCHAR NOT NULL
  description TEXT
  created_at  TIMESTAMP

Table: track_companies (junction table)
  track_id    INTEGER REFERENCES investment_tracks(id)
  company_id  VARCHAR REFERENCES companies(id)
  PRIMARY KEY (track_id, company_id)
```

**Option B: Tags/labels column on companies table**

```
Add column: tracks VARCHAR[] (array of track names)
```

Recommend Option A for flexibility. Discuss with team and implement chosen approach.

### Step 4: Seed Script (`backend/db/seed.py`)

Write a script that:

1. Reads `scraper/data/processed/nodes.json`
2. Reads `scraper/data/processed/edges.json`
3. Creates/resets the database tables
4. Inserts all companies from `nodes.json`
5. Inserts all relationships from `edges.json`
6. Prints summary (e.g. `"Seeded 503 companies, 12847 relationships"`)

**Usage:** `python -m backend.db.seed [--drop-existing]`

**Handle:**

- Duplicate detection (upsert or skip)
- Foreign key validation (edge references must exist in companies)
- Transaction: roll back everything if seeding fails partway
- Missing files: clear error message if `nodes.json` or `edges.json` not found

### Step 5: Add Database Indexes

```sql
CREATE INDEX idx_companies_sector ON companies(sector);
CREATE INDEX idx_companies_industry ON companies(industry);
CREATE INDEX idx_companies_market_cap ON companies(market_cap);
CREATE INDEX idx_relationships_source ON relationships(source_id);
CREATE INDEX idx_relationships_target ON relationships(target_id);
CREATE INDEX idx_relationships_type ON relationships(relationship_type);
CREATE INDEX idx_relationships_source_type ON relationships(source_id, relationship_type);
```

### Step 6: Refine API Endpoints

Update the GET endpoints to work with real data:

**`GET /api/companies`**
- Returns list of all companies (paginated, default 50 per page)
- Query params: `?sector=Technology&industry=...&sort=market_cap&order=desc&page=1&limit=50`
- Response: `{ "companies": [...], "total": 503, "page": 1, "pages": 11 }`

**`GET /api/companies/:ticker`**
- Returns single company with all fields
- 404 if ticker not found
- Include related companies (top 5 by relationship weight) in response

**`GET /api/companies/:ticker/relationships`**
- Returns all relationships for a company
- Query params: `?type=industry_peer&min_weight=0.5&limit=20`
- Response: `{ "relationships": [...], "total": 47 }`

**`GET /api/graph`**
- Returns nodes + edges for the frontend graph visualization
- Query params: `?sector=Technology&min_weight=0.3&limit=100`
- Response: `{ "nodes": [...], "edges": [...] }`

---

## Pipeline Handoff (coordinate with AI team — Task 6b)

```
[Scraper team]                  [AI team]                    [DB/API team]
scraper/scraper.py        -->   ai/pipeline/               -->  backend/db/seed.py
     |                              |                              |
scraper/data/raw/*.json         (processes                   Reads both files,
     |                           nodes.json)                 seeds into PostgreSQL
scraper/data/processed/              |
     nodes.json           -->   scraper/data/processed/
                                     edges.json
```

**Timing:**

- Scraper team produces `nodes.json` FIRST
- AI team consumes `nodes.json` and produces `edges.json` (Task 6b)
- DB/API team seeds BOTH files once both exist
- DB/API team can work on schema + seed script structure in parallel while waiting

### `nodes.json` contract (what the AI team expects)

- Array of objects, each with: `id`, `ticker`, `name`, `sector`, `industry`, `market_cap`, `description`, and `financial_metrics` object
- `financial_metrics` must include: `pe_ratio`, `pb_ratio`, `ps_ratio`, `beta`, `profit_margin`, `institutional_holdings`, `short_ratio`, `week52_change`
- Null values are acceptable; AI team will handle missing data

### `edges.json` contract (what the DB team expects from AI)

- Array of objects, each with: `source_id`, `target_id`, `relationship_type`, `weight`, `metadata`
- `source_id` and `target_id` are tickers (must match company `id` in `nodes.json`)
- `relationship_type` is one of: `"industry_peer"`, `"financial_similarity"`, `"nlp_similarity"`, `"llm_relationship"`
- `weight` is float 0.0-1.0
- `metadata` is an object with extra info (e.g. `{"subtype": "competitor", "reason": "..."}`)

---

## Definition of Done

- [ ] `scraper/tickers/sp500.txt` exists with ~500 tickers
- [ ] `scraper/scraper.py` runs and scrapes all tickers from Yahoo Finance
- [ ] `scraper/data/raw/` contains per-ticker JSON files
- [ ] `scraper/data/processed/nodes.json` is valid, contains ~500 companies
- [ ] `backend/models/company.py` matches `nodes.json` fields
- [ ] `backend/models/relationship.py` matches `edges.json` fields
- [ ] `backend/db/seed.py` loads both JSON files into PostgreSQL
- [ ] Investment tracks schema designed and implemented
- [ ] Database indexes added for common queries
- [ ] `GET /api/companies` returns real paginated data
- [ ] `GET /api/companies/:ticker` returns real data with relationships
- [ ] `GET /api/companies/:ticker/relationships` returns filtered relationships
- [ ] `GET /api/graph` returns nodes + edges for visualization
- [ ] All endpoints tested manually with real data
