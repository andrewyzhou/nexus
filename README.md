# Nexus

> Interactive graph visualization platform for **iPick.ai** — explore relationships between thousands of public companies (competitors, suppliers, partners, investors) grouped by investment track, with live Yahoo Finance data and per-stock / per-track detail pages.

This README is the canonical onboarding doc. If you're picking this up cold, read it top to bottom — every command, file, and gotcha you need is in here.

---

## Setup and Running the app

**Note**: Make sure **Docker** is installed and running on your machine before proceeding, as the database runs inside a local Postgres container.

| Tool                       | Version                         | Why                                                                            |
| -------------------------- | ------------------------------- | ------------------------------------------------------------------------------ |
| **Python**           | 3.9+                            | Backend + scraper.`from __future__ import annotations` is used so 3.9 works. |
| **pip**              | recent                          | Install Python deps                                                            |
| **Docker Desktop**   | any recent                      | Runs the Postgres container                                                    |
| **A modern browser** | Chrome / Firefox / Safari 2024+ | The frontend uses ES2020 syntax                                                |

**You do NOT need:** Node, npm, a bundler, an API key, a Yahoo Finance subscription, or anything paid.

### Dependencies

```bash
git clone https://github.com/andrewyzhou/nexus.git
cd nexus

# 1) Python deps
python3 -m pip install -r backend/requirements.txt
python3 -m pip install -r scraper/requirements.txt

# 2) Postgres in Docker
docker compose -f backend/docker-compose.yml up -d
```

### Execution Steps

1. **Download relationship data**
   Download `supplier.json` and `subsidiary.json` data from the Slack channel or this [Google Drive link](https://drive.google.com/drive/folders/1smHj5mKg8s3eJ_vG9IkWizbdMU4uJmOZ?usp=drive_link).
   *(Note: only people in the project have access to this drive link).*
2. **Place the files**
   Place the downloaded JSON files into their respective folders:

   - `sec_pipeline/subsidiary/subsidiary.json`
   - `sec_pipeline/supplier/supplier.json`
3. **Seed database**
   Run the seed script located in `backend/db` to populate the database:

   ```bash
   python3 backend/db/seed_prod.py
   ```

   **Seeding Details:** This script pulls live market data via Yahoo Finance for ~4,300 tickers and maps out the corporate relationships from your SEC JSON files. **This process should take around 60 seconds.**
   *(Optional: If you want a fast iteration loop for testing, cap the run to the first 200 records: `NEXUS_SEED_LIMIT=200 python3 backend/db/seed_prod.py`)*
4. **Run frontend**
   Open a new terminal and start the frontend static server:

   ```bash
   cd frontend && python3 -m http.server 8000
   ```
5. **Run backend**
   Open a separate terminal and run the backend Flask API:

   ```bash
   python3 backend/main.py
   ```

   *(Flask serves on `http://localhost:5001`)*

---

### About `python3` vs `python`

If you're using conda/anaconda, `python` and `python3` may resolve to **different interpreters** with different installed packages. The fix is always:

```bash
python3 -m pip install <pkg>     # install with the same interpreter you'll run
python3 backend/main.py          # run with that same interpreter
```

Or use a venv:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt -r scraper/requirements.txt
```

Then open **http://localhost:8000** in your browser:

- On first visit the graph starts **empty** (all tracks hidden — opt-in design). Your filter state persists in `localStorage` across sessions.
- Click any investment track's toggle button in the left sidebar to add its companies to the graph.
- Click `ALL` / `CLEAR` above the track list for bulk toggle.
- Expand any company row with the chevron `▾` to see its competitors/suppliers with per-entry +/✕ buttons.
- Click any graph node to open the right-side detail panel; click the stock link for the full **stock detail page** (`stock.html?ticker=<TICKER>`).
- Click a track name to open its **detail page** (`track.html?slug=<slug>`).
- Theme toggle (`◐`) is in the header — defaults to light, persists in `localStorage`.

### Sanity checks

```bash
# 1. Backend up?
curl -s http://localhost:5001/graph | python3 -c "import sys,json; d=json.load(sys.stdin); print('nodes:',len(d['nodes']),'edges:',len(d['edges']),'tracks:',len(d['tracks']))"

# 2. Live yfinance pull working?
curl -s http://localhost:5001/companies/NVDA/live | python3 -m json.tool | head -20

# 3. News endpoint?
curl -s 'http://localhost:5001/companies/NVDA/news?limit=3' | python3 -m json.tool | head -20

# 4. Tracks index
curl -s http://localhost:5001/tracks | python3 -c "import sys,json; ts=json.load(sys.stdin); print(len(ts),'tracks; top by size:'); [print(' ',t['company_count'],t['slug']) for t in sorted(ts,key=lambda x:-x['company_count'])[:10]]"
```

---

## Table of contents

1. [Setup and Running the app](#setup-and-running-the-app)
2. [What this project is](#what-this-project-is)
3. [Architecture overview](#architecture-overview)
4. [Repository layout](#repository-layout)
5. [Prerequisites](#prerequisites)
6. [The data pipeline](#the-data-pipeline)
7. [REST API reference](#rest-api-reference)
8. [Frontend pages](#frontend-pages)
9. [Database schema](#database-schema)
10. [Testing Suite](#testing-suite)
11. [Common dev tasks](#common-dev-tasks)
12. [Troubleshooting](#troubleshooting)
13. [Known gaps & roadmap](#known-gaps--roadmap)
14. [Contributing & branching](#contributing--branching)
15. [Quick reference card](#quick-reference-card)

---

## What this project is

Nexus is a three-tier app:

| Tier               | Tech                                                                | What it does                                                                             |
| ------------------ | ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| **Data**     | Postgres 16 (Docker) + Yahoo Finance scraper + AI team JSON outputs | Holds ~4000 companies, their relationships, and investment-track tags                    |
| **Backend**  | Python / Flask                                                      | REST API serving the graph, per-stock detail (live yfinance), per-track detail, and news |
| **Frontend** | Vanilla HTML/CSS/JS + D3.js v7 (no build step)                      | Force-directed graph, sortable track pages, stock detail pages, light/dark theme         |

**No build step. No bundler. No framework.** You can edit any frontend file and refresh the browser. The whole stack runs locally with one Postgres container plus two Python processes.

---

## Architecture overview

```
┌─────────────────────┐         ┌──────────────────────────┐
│  Browser            │  HTTP   │  Flask backend           │
│  - index.html       │ ──────► │  backend/main.py :5001   │
│  - track.html       │         │  - /graph                │
│  - stock.html       │         │  - /tracks, /tracks/:slug│
│  D3 force graph     │         │  - /companies/:t/live    │
└─────────────────────┘         │  - /companies/:t/news    │
                                └────────┬─────────────────┘
                                         │
                            ┌────────────┴────────────┐
                            ▼                         ▼
                  ┌─────────────────┐       ┌──────────────────────┐
                  │  Postgres :5433 │       │  Yahoo Finance       │
                  │  corporate_data │       │  (live, no API key)  │
                  │  Docker         │       │  via yfinance        │
                  └────────▲────────┘       └──────────────────────┘
                           │
                           │ seed
                  ┌────────┴──────────────┐
                  │ backend/db/seed_prod  │
                  │  • ticker_track.json  │  (S3-sourced ticker → track map)
                  │  • scraper.StockScraper bulk-fetch
                  │  • task5/.../*.json   │  (AI team relationships)
                  └───────────────────────┘
```

**Two interesting design choices:**

1. **The seed talks to live Yahoo on every run.** `seed_prod.py` calls `scraper.StockScraper.get_bulk()` directly so the DB always reflects current prices/market caps. ~60 seconds for the full ~4300-ticker universe.
2. **The frontend renders only the visible subset of nodes.** With 4000+ companies in the universe, force-simulating all of them in D3 was unworkable. `renderGraph()` rebuilds the SVG from scratch every time the user toggles a track filter, keeping the simulation tractable (typically 1–50 nodes per render).

---

## Repository layout

```
nexus/
├── README.md                          ← you are here
├── ticker_track.json                  ← master ticker → investment-track map (4342 entries)
│
├── backend/                           ← Flask REST API
│   ├── main.py                        ← all routes live here
│   ├── config.py                      ← DATABASE_URL (env-overridable)
│   ├── docker-compose.yml             ← Postgres 16 on port 5433
│   ├── requirements.txt               ← Python deps
│   ├── tests/
│   │   └── test_api.py
│   └── db/
│       ├── init.py                    ← schema (companies, relationships, tracks, indexes)
│       ├── seed.py                    ← legacy: full S&P 500 via yfinance one-by-one
│       ├── seed_prod.py               ← canonical live seed (USE THIS)
│       └── seed_supplier_subsidary.py ← ingest task5/SeleniumAI_Task5/final_json/*.json
│
├── frontend/                          ← Static site, no build tool
│   ├── index.html                     ← graph view
│   ├── track.html                     ← per-track detail page
│   ├── stock.html                     ← per-stock detail page
│   ├── main.js                        ← D3 graph + sidebar logic
│   ├── track.js                       ← track detail page logic
│   ├── stock.js                       ← stock detail page logic
│   ├── theme.js                       ← light/dark mode toggle (defaults to light)
│   ├── style.css                      ← shared design tokens (CSS variables)
│   ├── track.css                      ← track + stock page layout
│   ├── theme.css                      ← light theme overrides
│   ├── ipick-logo.png                 ← header logo
│   └── data/mock.json                 ← demo fallback when API is unreachable
│
├── scraper/                           ← Yahoo Finance bulk scraper
│   ├── scraper.py                     ← StockScraper class (curl_cffi + async)
│   ├── basket_stocks.py               ← curated demo basket
│   ├── basket_tickers.txt
│   ├── preprocess.py
│   ├── data/                          ← cached ticker snapshots
│   ├── tickers/                       ← raw ticker universe files
│   └── requirements.txt
│
├── ai/                                ← AI team scripts (news, relationship extraction)
│   ├── news.py
│   ├── requirements.txt
│   ├── pipeline/                      ← news scrapers and brief generators
│   │   ├── news_scraper.py
│   │   ├── news_summarizer.py
│   │   ├── generate_news_tooltips.py
│   │   ├── geopolitical_brief.py
│   │   ├── suppliers.json
│   │   └── .env.example               ← API keys (Gemini, etc.)
│   ├── processed/
│   └── raw/
│
└── task5/SeleniumAI_Task5/            ← AI team Task 5 deliverables
    ├── README.md
    └── final_json/                    ← per-ticker relationship JSONs (consumed by seed_supplier_subsidary.py)
        ├── NVDA.json   AMZN.json   GOOGL.json
        ├── META.json   MSFT.json   TSM.json
```

---

## Prerequisites

| Tool                       | Version                         | Why                                                                            |
| -------------------------- | ------------------------------- | ------------------------------------------------------------------------------ |
| **Python**           | 3.9+                            | Backend + scraper.`from __future__ import annotations` is used so 3.9 works. |
| **pip**              | recent                          | Install Python deps                                                            |
| **Docker Desktop**   | any recent                      | Runs the Postgres container                                                    |
| **A modern browser** | Chrome / Firefox / Safari 2024+ | The frontend uses ES2020 syntax                                                |

**You do NOT need:** Node, npm, a bundler, an API key, a Yahoo Finance subscription, or anything paid.

---

## The data pipeline

```
ticker_track.json        ──┐
                            │
sec_pipeline/.../*.json   ──┤  seed_prod.py   ──►  Postgres (companies, relationships, tracks)
                            │       │                          │
scraper.StockScraper      ─┘       │                          │
(live Yahoo Finance)               │                          ▼
                                   │                    backend/main.py
                                   ▼                          │
                        seed_supplier_subsidary.py            ▼
                        (called by seed_prod.py)    /graph, /tracks/<slug>, etc.
```

### `ticker_track.json`

- Source: `s3://ipickai-storage/metadata/ticker_track.json`
- Shape: `{ "TICKER": "Investment Track Name", ... }`
- ~4342 entries
- Re-pull when iPick updates the track taxonomy. The seeder reads from this on every run.

### `scraper/scraper.py` — `StockScraper`

- Pulls live Yahoo Finance via `curl_cffi` (TLS fingerprinting to dodge rate limits)
- `get(ticker)` for one stock, `get_bulk(tickers, on_progress=...)` for many (~80 stocks/sec)
- Returns dicts with `ticker`, `companyName`, `price`, `marketCap`, `trailingPE`, `sector`, `industry`, ~50 fields total
- Used by both `seed_prod.py` (bulk seed) and `main.py` (`/companies/<ticker>/live` endpoint, single fetch)

### `sec_pipeline/` Outputs

- AI team's SEC parsing deliverables (Exhibit 21.1 for subsidiaries, 10-K text for suppliers).
- Output files: `subsidiary.json` and `supplier.json`.
- Hand-curated mappings between primary company nodes and their relationships.
- The DB schema normalizes the free-form `relationship` field to one of `competitor / supplier / ownership / partnership`.

### Seeding flow (inside `seed_prod.py`)

1. `init_db()` — create tables + indexes (idempotent)
2. Build the ticker universe = `ticker_track.json` keys ∪ task5 anchor tickers
3. `StockScraper.get_bulk(tickers)` — live Yahoo fetch
4. Bulk INSERT via `psycopg2.extras.execute_values` (single round-trip for thousands of rows)
5. `load_investment_tracks()` — create track rows + link companies via `company_tracks`
6. `seed_supplier_subsidary.seed_relationships()` — ingest task5 JSONs into the `relationships` table

**Re-running is safe.** Every INSERT uses `ON CONFLICT ... DO UPDATE` so you can rerun the seed any time to refresh prices.

---

## REST API reference

All endpoints live on `http://localhost:5001`. CORS is wide open (`flask-cors`).

| Method | Path                                                                   | Returns                                                                         | Notes                                                                                                                                            |
| ------ | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| GET    | `/graph`                                                             | `{ tracks, nodes, edges }`                                                    | Full graph payload for D3. Each node has a `tracks: [slug, ...]` array. Competitor edges are auto-generated for all companies sharing a track. |
| GET    | `/companies?limit=N`                                                 | `[{ticker, name, price}]`                                                     | Default limit 500.                                                                                                                               |
| GET    | `/companies/<ticker>`                                                | DB-backed company detail                                                        | Full row + linked investment track.                                                                                                              |
| GET    | `/companies/<ticker>/live`                                           | **Fresh** Yahoo Finance pull                                              | Bypasses Postgres entirely. Powers `stock.html`.                                                                                               |
| GET    | `/companies/<ticker>/neighbors?type=&min_weight=&max_weight=&limit=` | `{ nodes, edges }`                                                            | Used by the sidebar dropdowns to load supplier/subsidiary relationships.                                                                         |
| GET    | `/companies/<ticker>/news?limit=N`                                   | News items via `yfinance.Ticker.news`                                         | Title, link, publisher, summary, timestamp. Default limit 8.                                                                                     |
| GET    | `/tracks`                                                            | `[{slug, name, color, company_count}]`                                        | Sorted by company count desc.                                                                                                                    |
| GET    | `/tracks/<slug>`                                                     | `{ name, slug, color, description, market_leader, companies, company_count }` | Powers `track.html`. Companies sorted by market cap.                                                                                           |
| GET    | `/tracks/<slug>/news?companies=N&per=M`                              | Aggregated news for top-N companies in the track                                | Default 5 companies × 3 items each.                                                                                                             |
| GET    | `/investment_tracks`                                                 | Legacy track listing                                                            | Kept for compat with the original task 4 routes.                                                                                                 |
| GET    | `/investment_tracks/<id>/companies`                                  | Legacy                                                                          | Kept for compat.                                                                                                                                 |

### Slug generation

Track names get slugified for URL use:

```python
def slugify(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")
```

So `"Payment - Restaurant & Hotels"` → `"payment---restaurant---hotels"`. **Backend and frontend must use the exact same slugifier**, otherwise track-page links 404.

---

## Frontend pages

### `index.html` — main graph

#### Left sidebar

- **Search** — fuzzy search by ticker or track name; filters both the Companies list and Investment Tracks list in real time.
- **Companies** — scrollable list of every company in the graph universe. Pinned (currently on-graph) companies sort to the top, alphabetically within each group.
  - Click the **chevron `▾`** on any row to expand a dropdown showing that company's related companies (competitors, suppliers, etc.) fetched live from `/companies/<ticker>/neighbors`.
  - Each connection entry has a **green `+` button** (add to graph) or **red `✕` button** (remove from graph), depending on whether that company is currently visible. Clicking toggles its presence on the canvas.
  - The row-level toggle button works the same way: green `+` to pin, red `✕` to unpin.
  - Toggling updates the list **in-place** — existing DOM nodes are reordered, not rebuilt — so open dropdowns stay open and there's no flicker.
  - **ALL** / **CLEAR** buttons above the list bulk-add or bulk-remove all companies.
- **Investment Tracks** — one row per track. Each track has:
  - A **toggle button** (`+` / `✕`) to show or hide that entire track's member companies on the graph.
  - A **chevron** to expand a dropdown listing every company in the track, each with its own `+`/`✕` button for individual control.
  - **ALL** / **CLEAR** buttons above the list.

#### Graph canvas (center)

- **Hover** a node — a tooltip appears showing the company's ticker and name.
- **Click a node** — opens the right-side detail panel for that company. Click the same node again, or click the blank canvas, to close the panel.
- **Scroll** to zoom in/out; **drag** the canvas to pan.
- **Double-click the canvas** to reset zoom to the default view.
- **Parallel edges** — when two companies share more than one relationship type (e.g. both competitor and supplier), each edge renders as an offset quadratic bezier curve so both are visible and don't overlap.
- **Edge color legend** (bottom-left of the canvas):
  - 🔴 Red — Competitor
  - 🟡 Yellow — Supplier
  - 🔵 Blue — Subsidiary

#### Right detail panel

Opens when you click any graph node or company row. Contains (top to bottom):

1. **Ticker badge** — styled pill with the stock ticker symbol.
2. **Company name** and **sector**.
3. **"Open full stock page →"** link — navigates to `stock.html?ticker=<TICKER>`.
4. **Add/Remove button** — green **`+ Add to graph`** if the company isn't currently visible; red **`✕ Remove from graph`** if it is. Clicking toggles it and updates the graph immediately.
5. **Stat cards** — Market cap and current price. Price and market cap are fetched live (async) from `/companies/<ticker>/live` after the panel opens, so they update from static DB values to fresh Yahoo Finance data within a second or two.
6. **Investment track badge** — clickable pill showing the company's track. Clicking navigates to `track.html?slug=<slug>`.
7. **About** — company description text pulled from the DB.
8. **Connections** — list of related companies with:
   - **Role label** (Competitor, Supplier of, Customer of, Parent of, Subsidiary of)
   - **Green `+` / Red `✕` button** per entry — same add/remove logic as the sidebar dropdowns
   - Clicking the **company name** in a connection entry focuses the panel on that company
   - After the initial connections load, the panel asynchronously fetches additional subsidiary and supplier relationships from `/companies/<ticker>/neighbors` and appends them

#### Header

- **iPick.ai logo** — links to `https://ipick.ai` in a new tab.
- **Theme toggle `◐`** — switches between light and dark mode.

**Key implementation note:** the graph re-renders from scratch every time you toggle a track filter. See `renderGraph()` in `main.js`. This is necessary because the universe is too large to keep all 4200 nodes simulated at once.

---

### `track.html` — investment track detail

URL: `track.html?slug=<track-slug>`

- Hero section: track name, description, **Market Leader** pill (`Leader: TICKER ($XB)`).
- **Sortable companies table** — sort dropdown with options: Market Cap, Ticker, Name, Price, P/E Ratio. Clicking a different sort key re-sorts the table instantly (client-side).
- Each company row links to its `stock.html` page.
- **News feed** — aggregated news via `/tracks/<slug>/news`. Each item shows headline, publisher, date, summary, and a ticker label indicating which company the article is about.

---

### `stock.html` — stock detail

URL: `stock.html?ticker=<TICKER>`

All data comes from `/companies/<ticker>/live` (fresh Yahoo Finance pull on every page load) and `/companies/<ticker>/news`.

- **Hero**: company name, sector, current price shown as `$X.XX (Y.YY%)` with the percent change from the previous close, market cap, and P/E ratio.
- **Stats grid**: only non-null values are shown. Possible stats: Open, Previous Close, Day High, Day Low, 52-Week Range, Volume, EPS, Forward P/E, Dividend Yield, Beta, Employees, Website (as a clickable link). Empty or unavailable fields are hidden entirely rather than shown as dashes.
- **News feed** — per-company news via `/companies/<ticker>/news`. Each item: headline (linked), publisher, date, and summary text. All content is HTML-escaped to prevent injection.

### Theme system

- `theme.js` reads/writes `localStorage["nexus-theme"]`, defaults to `light`
- `theme.css` defines `html[data-theme="light"]` overrides for the CSS variables in `style.css`
- Toggle button: `<button id="theme-toggle">` works on any page that includes `theme.js`

---

## Database schema

Defined in [`backend/db/init.py`](backend/db/init.py).

```sql
companies (
  id SERIAL PRIMARY KEY,
  ticker TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  exchange TEXT, country TEXT, sector TEXT, industry TEXT, currency TEXT,
  price REAL, market_cap BIGINT, enterprise_value BIGINT,
  pe_ratio REAL, eps REAL, employees INTEGER,
  website TEXT, description TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)

relationships (
  id SERIAL PRIMARY KEY,
  source_ticker TEXT REFERENCES companies(ticker),
  target_ticker TEXT REFERENCES companies(ticker),
  relationship_type TEXT NOT NULL,           -- competitor | supplier | investor | partnership
  weight REAL DEFAULT 1.0,
  metadata TEXT,                             -- JSON string: {evidence, source, raw_relationship, name}
  UNIQUE (source_ticker, target_ticker, relationship_type)
)

investment_tracks (
  id SERIAL PRIMARY KEY,
  name TEXT UNIQUE NOT NULL,
  description TEXT                           -- currently null; populate when AI team writes blurbs
)

company_tracks (
  track_id INTEGER REFERENCES investment_tracks(id) ON DELETE CASCADE,
  company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
  UNIQUE (track_id, company_id)
)
```

Plus 10 indexes on `ticker`, `sector`, `industry`, relationship endpoints, and the `company_tracks` join columns.

### Connecting to the DB directly

```bash
docker exec -it $(docker ps -qf name=db) psql -U nexus -d corporate_data
```

or with the Postgres client on your host:

```bash
psql postgresql://nexus:nexus@localhost:5433/corporate_data
```

---

## Testing Suite

The Nexus backend is equipped with a `pytest` suite ensuring business logic fidelity alongside pipeline stability. The suite evaluates edge cases securely via dynamically generated database schemas (`test_schema`) utilizing fixtures so that your main database tables remain undisturbed.

### Running the tests

1. **Prerequisites**
   Ensure you have installed the testing packages. They are included in the requirements, but you can explicitly ensure they are present by running:
   ```bash
   cd backend
   pip install pytest pytest-mock
   ```

2. **Database Container**
   Ensure your Docker Postgres database (`localhost:5433`) is running so the fixture system can spin up `test_schema`.

3. **Execution**
   To execute the entire test suite, run:
   ```bash
   cd backend
   python3 -m pytest testing/ -vv
   ```

### Test Coverage

**1. `test_logic.py` (Unit Tests)**
- **Slugification (`test_slugify`)**: Ensures track and company names follow strict URL-safe text normalization (e.g. converting `Ad agency - big 4` -> `ad-agency---big-4`).
- **Data Safeties (`test_scraper_parse_*`)**: Validates that `StockScraper._parse` yields expected defaults rather than crashing when Yahoo Finance returns missing fields or partial dictionary payloads.

**2. `test_api.py` (Integration Tests)**
- **Graph Algorithm (`test_graph_implicit_edges`)**: Evaluates the `/graph` API behavior by mocking multiple companies under a unified track and asserting that implicit competitor edges properly materialize between sibling nodes.
- **Cache Bypassing (`test_live_data_bypasses_cache`)**: Directly mocks `yfinance.Ticker` beneath `StockScraper` to guarantee that the proxy endpoint `/companies/<ticker>/live` correctly streams requested ticker features while circumventing the database caching protocol.
- **Pipeline Integrity (`test_pipeline_integrity`)**: Executes an automated pipeline check iterating over AI extraction deliverables targeting `/task5/SeleniumAI_Task5/final_json/`. Every extracted `related_stocks` entry is forcibly matched against `ticker_track.json` to prevent unrecognized companies from entering the final graph ecosystem, providing an instant failsafe against data rot.

## Common dev tasks
### Add a new ticker to the graph

1. Add it to `ticker_track.json` with the right track name (or update from S3)
2. Re-run `python3 backend/db/seed_prod.py`

### Add a new investment track

1. Add `"NEWTKR": "My New Track"` entries to `ticker_track.json`
2. Re-run the seeder. The track row is auto-created.
3. (Optional) populate the description: `UPDATE investment_tracks SET description = '...' WHERE name = 'My New Track';`

### Add new relationships

1. Drop a JSON file in `task5/SeleniumAI_Task5/final_json/` matching the schema above
2. Re-run `python3 backend/db/seed_prod.py` (it calls `seed_supplier_subsidary.py` internally)

### Restart the backend after editing `main.py`

Flask debug mode auto-reloads top-level files most of the time, but **always restart manually** after editing helper modules — Python's import cache will hold the old version. `Ctrl+C` then `python3 backend/main.py` again.

### Wipe the DB and start fresh

```bash
docker compose -f backend/docker-compose.yml down -v   # -v drops the volume
docker compose -f backend/docker-compose.yml up -d
python3 backend/db/seed_prod.py
```

---

## Troubleshooting

| Symptom                                               | Cause                                                                                   | Fix                                                                                                                  |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `ModuleNotFoundError: psycopg2`                     | `pip` and `python` are different interpreters (conda vs system)                     | `python3 -m pip install <pkg>` — always use `python3 -m pip`                                                    |
| `ModuleNotFoundError: flask_cors`                   | Same interpreter mismatch                                                               | Check which python you're running with `which python3`; install deps with that exact binary                        |
| `No module named 'dotenv'`                          | Importing `scraper.scraper` pulls in a module that needs `python-dotenv`            | `python3 -m pip install python-dotenv beautifulsoup4`                                                              |
| Header shows `demo` not `live`                    | Backend isn't running,`/graph` errored, or CORS blocked                               | Check `curl http://localhost:5001/graph`; check browser devtools Network tab                                       |
| Clicking a track shows nothing                        | (a) Backend not restarted after SQL change, (b)`company_tracks` empty, (c) wrong slug | Restart backend; re-run `seed_prod.py`; verify with `curl http://localhost:5001/tracks`                          |
| Company dropdown shows no suppliers/subsidiaries      | `/companies/<ticker>/neighbors` returning empty                                       | Those relationships only exist for the 6 task5 anchor tickers — add more JSONs to `task5/final_json/`             |
| `seed_prod.py` only seeds a few companies           | yfinance rate-limited or many tickers don't exist                                       | Check the per-batch progress output; re-run; consider raising `batch_pause` in `scraper.StockScraper.get_bulk()` |
| `WARN: Found orphan containers` from docker compose | Old containers from a previous compose project name                                     | Harmless; clean with `docker rm -f backend-backend-1 backend-postgres-1`                                           |
| Postgres connection refused                           | Container not up, or another postgres on 5433                                           | `docker ps`; if collision, change the host port in `backend/docker-compose.yml`                                  |

---

## Known gaps & roadmap

- ❌ **Stock chart** on the stock page — needs a `/companies/<ticker>/history?range=1mo` endpoint wrapping `yf.Ticker(t).history()` plus a Chart.js or D3 line chart in `stock.html`.
- ❌ **Better news with citations** — current news is `yfinance.Ticker.news` (free, fast, but thin). Tracker calls out **Tavily** and **Firecrawl** as upgrade paths. The AI team owns this.
- ❌ **Per-track descriptions** — `investment_tracks.description` column exists but is null. Either AI team writes them or generate via LLM at seed time.
- 🟡 **Relationship coverage is thin** — supplier/subsidiary edges only exist for 6 anchor tickers (NVDA, AMZN, GOOGL, META, MSFT, TSM). Competitor edges are auto-generated for all track-mates. Add more `task5/final_json/*.json` files to improve this.
- 🟡 **`relationships` metadata** is JSON-encoded as a TEXT column — fine for now, but consider migrating to JSONB if you need to query inside it.
- 🟡 **AI pipeline scripts** in `ai/pipeline/` (news scrapers, brief generator) are not wired into the Flask backend — they're standalone batch tools. The backend uses `yfinance.Ticker.news` directly for per-request news.
- 🟡 **`seed_supplier_subsidary.py` filename** has a typo ("subsidary") — harmless but worth fixing if you rename anything nearby.

---

## Contributing & branching

- `main` — production / demo branch

**For new work:**

1. Branch off `main`: `git checkout -b yourname/feature-foo`
2. Keep commit messages short and imperative: `Add /history endpoint`, `Fix sidebar flicker on toggle`
3. Open a PR against `main`

---

## Quick reference card

```bash
# Setup (once)
python3 -m pip install -r backend/requirements.txt -r scraper/requirements.txt
docker compose -f backend/docker-compose.yml up -d

# Seed (anytime — pulls fresh Yahoo data)
python3 backend/db/seed_prod.py

# Run
python3 backend/main.py                              # terminal 1
cd frontend && python3 -m http.server 8000           # terminal 2

# Open
http://localhost:8000          # graph
http://localhost:8000/track.html?slug=<slug>
http://localhost:8000/stock.html?ticker=<TICKER>

# Inspect
curl http://localhost:5001/graph
curl http://localhost:5001/tracks
curl http://localhost:5001/companies/NVDA/live
curl http://localhost:5001/companies/NVDA/news
docker exec -it $(docker ps -qf name=db) psql -U nexus -d corporate_data
```
