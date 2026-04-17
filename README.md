# Nexus

> Interactive graph visualization platform for **iPick.ai** — explore relationships between thousands of public companies (competitors, suppliers, partners, investors) grouped by investment track, with live Yahoo Finance data and per-stock / per-track detail pages.

This README is the canonical onboarding doc. If you're picking this up cold, read it top to bottom — every command, file, and gotcha you need is in here.

---

## Table of contents

1. [What this project is](#what-this-project-is)
2. [Architecture overview](#architecture-overview)
3. [Repository layout](#repository-layout)
4. [Prerequisites](#prerequisites)
5. [First-time setup](#first-time-setup)
6. [Running the app](#running-the-app)
7. [The data pipeline](#the-data-pipeline)
8. [REST API reference](#rest-api-reference)
9. [Frontend pages](#frontend-pages)
10. [Database schema](#database-schema)
11. [Common dev tasks](#common-dev-tasks)
12. [Troubleshooting](#troubleshooting)
13. [Known gaps & roadmap](#known-gaps--roadmap)
14. [Contributing & branching](#contributing--branching)

---

## What this project is

Nexus is a three-tier app:

| Tier | Tech | What it does |
|---|---|---|
| **Data** | Postgres 16 (Docker) + Yahoo Finance scraper + AI team JSON outputs | Holds ~4000 companies, their relationships, and investment-track tags |
| **Backend** | Python / Flask | REST API serving the graph, per-stock detail (live yfinance), per-track detail, and news |
| **Frontend** | Vanilla HTML/CSS/JS + D3.js v7 (no build step) | Force-directed graph, sortable track pages, stock detail pages, light/dark theme |

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
                  │  Docker         │       │  via curl_cffi       │
                  └────────▲────────┘       └──────────────────────┘
                           │
                           │ seed
                  ┌────────┴──────────────┐
                  │ backend/db/seed_demo  │
                  │  • ticker_track.json  │  (S3-sourced ticker → track map)
                  │  • scraper.StockScraper bulk-fetch
                  │  • task5/.../*.json   │  (AI team relationships)
                  └───────────────────────┘
```

**Two interesting design choices:**

1. **The seed talks to live Yahoo on every run.** The pre-scraped `scraper/data.json` snapshot exists as a fallback but we don't use it — `seed_demo.py` calls `scraper.StockScraper.get_bulk()` directly so the DB always reflects current prices/market caps. ~60 seconds for the full ~4300-ticker universe.
2. **The frontend renders only the visible subset of nodes.** With 4000+ companies in the universe, force-simulating all of them in D3 was unworkable. `renderGraph()` rebuilds the SVG from scratch every time the user toggles a track filter, keeping the simulation tractable (typically 1–50 nodes per render).

---

## Repository layout

```
nexus/
├── README.md                          ← you are here
├── ticker_track.json                  ← master ticker → investment-track map (4342 entries)
├── project_tracker.txt                ← plain-text export of the team's project tracker doc
│
├── backend/                           ← Flask REST API
│   ├── main.py                        ← all routes live here (~430 LOC)
│   ├── config.py                      ← DATABASE_URL (env-overridable)
│   ├── docker-compose.yml             ← Postgres 16 on port 5433
│   ├── requirements.txt               ← Python deps
│   └── db/
│       ├── init.py                    ← schema (companies, relationships, tracks, indexes)
│       ├── seed.py                    ← legacy: full S&P 500 via yfinance one-by-one
│       ├── seed_demo.py               ← canonical live seed (USE THIS)
│       └── seed_supplier_subsidary.py ← ingest task5/SeleniumAI_Task5/final_json/*.json
│
├── frontend/                          ← Static site, no build tool
│   ├── index.html                     ← graph view
│   ├── track.html                     ← per-track detail page
│   ├── stock.html                     ← per-stock detail page
│   ├── main.js                        ← D3 graph + sidebar
│   ├── track.js                       ← track detail page logic
│   ├── stock.js                       ← stock detail page logic
│   ├── theme.js                       ← light/dark mode toggle (default light)
│   ├── style.css                      ← shared design tokens (CSS variables)
│   ├── track.css                      ← track + stock page layout
│   ├── theme.css                      ← light theme overrides
│   └── data/mock.json                 ← demo fallback when API is unreachable
│
├── scraper/                           ← Yahoo Finance bulk scraper
│   ├── scraper.py                     ← StockScraper class (curl_cffi + async)
│   ├── ten_k_fetch.py                 ← SEC EDGAR 10-K fetcher (used by scraper.py)
│   ├── data.json                      ← cached snapshot (4788 tickers, ~13MB) — fallback only
│   ├── all_tickers.txt                ← raw ticker universe
│   ├── basket_stocks.py               ← curated demo basket
│   ├── basket_tickers.txt
│   ├── preprocess.py
│   └── requirements.txt
│
├── ai/                                ← AI team scripts (relationship extraction, news)
│   ├── pipeline/                      ← Selenium news scrapers, geopolitical brief generator
│   ├── geopolitical_brief.{ipynb,json,txt}
│   └── supplier_extraction.py
│
├── task5/SeleniumAI_Task5/            ← AI team Task 5 deliverables
│   ├── final_json/                    ← per-ticker relationship JSONs (consumed by seed_relationships.py)
│   │   ├── NVDA.json   AMZN.json   GOOGL.json
│   │   ├── META.json   MSFT.json   TSM.json
│   ├── selenium_nexus.ipynb           ← scraping notebook
│   └── gen_notebook.py
│
└── ai/pipeline/.env.example           ← API keys for the AI pipeline (Gemini, etc.)
```

---

## Prerequisites

| Tool | Version | Why |
|---|---|---|
| **Python** | 3.9+ | Backend + scraper. `from __future__ import annotations` is used so 3.9 works. |
| **pip** | recent | Install Python deps |
| **Docker Desktop** | any recent | Runs the Postgres container |
| **A modern browser** | Chrome / Firefox / Safari 2024+ | The frontend uses `:has()` selector and ES2020 syntax |

**You do NOT need:** Node, npm, a bundler, an API key, a Yahoo Finance subscription, or anything paid.

---

## First-time setup

```bash
git clone https://github.com/andrewyzhou/nexus.git
cd nexus

# 1) Python deps
python3 -m pip install -r backend/requirements.txt
python3 -m pip install -r scraper/requirements.txt

# 2) Postgres in Docker
docker compose -f backend/docker-compose.yml up -d
# this starts a postgres:16 container on host port 5433
# database: corporate_data, user: nexus, password: nexus

# 3) Seed the database (LIVE Yahoo Finance pull, ~60s)
python3 backend/db/seed_demo.py

# Optional: cap to first N tickers for a fast iteration loop
NEXUS_SEED_LIMIT=200 python3 backend/db/seed_demo.py
```

When `seed_demo.py` finishes you should see something like:
```
Companies seeded: 4200
Linking tracks from ticker_track.json...
  tracks=1122  links=4199  unmatched=143
Seeding relationships from task5 JSONs...
Relationships upserted: 30  (skipped 0 unseen tickers)

Done. Backend is ready to serve live data.
```

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

---

## Running the app

You need **two terminals** (three if you want to keep `seed_demo.py` runs separate):

**Terminal 1 — backend:**
```bash
python3 backend/main.py
# Flask serves on http://localhost:5001
```

**Terminal 2 — frontend (any static server):**
```bash
cd frontend && python3 -m http.server 8000
# open http://localhost:8000
```

Then open **http://localhost:8000** in your browser:

- The graph starts **empty** (all tracks hidden by default — opt-in design).
- Click any investment track in the left sidebar to render its companies.
- Click `ALL` / `NONE` above the track list for bulk toggle.
- Click the `→` arrow on a track row to open its **detail page** (`track.html?slug=<slug>`).
- Click any node to open the right-side panel; click "Open full stock page →" for the **stock detail page** (`stock.html?ticker=<TICKER>`).
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

## The data pipeline

```
ticker_track.json        ──┐
                            │
task5/final_json/*        ──┤  seed_demo.py   ──►  Postgres (companies, relationships, tracks)
                            │       │                          │
scraper.StockScraper      ─┘       │                          │
(live Yahoo Finance)               │                          ▼
                                   │                    backend/main.py
                                   ▼                          │
                        seed_supplier_subsidary.py            ▼
                        (called by seed_demo.py)    /graph, /tracks/<slug>, etc.
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
- Used by both `seed_demo.py` (bulk seed) and `main.py` (`/companies/<ticker>/live` endpoint, single fetch)

### `task5/SeleniumAI_Task5/final_json/*.json`
- AI team's hand-curated relationship dataset
- Currently 6 anchor tickers (NVDA, AMZN, GOOGL, META, MSFT, TSM), 30 edges total
- Schema:
  ```json
  {
    "ticker": "NVDA",
    "name": "NVIDIA Corporation",
    "related_stocks": [
      {"ticker": "MSFT", "relationship": "Competitor", "evidence": "...", "source": "SEC-10K"}
    ]
  }
  ```
- Add more files here to grow the relationship graph; `seed_relationships.py` ingests all of them and normalizes the free-form `relationship` field to one of `competitor / supplier / investor / partnership`.

### Seeding flow (inside `seed_demo.py`)

1. `init_db()` — create tables + indexes (idempotent)
2. Build the ticker universe = `ticker_track.json` keys ∪ task5 anchor tickers
3. `StockScraper.get_bulk(tickers)` — live Yahoo fetch
4. Bulk INSERT via `psycopg2.extras.execute_values` (single round-trip for thousands of rows)
5. `load_investment_tracks()` — create track rows + link companies via `company_tracks`
6. `seed_relationships()` — ingest task5 JSONs into the `relationships` table

**Re-running is safe.** Every INSERT uses `ON CONFLICT ... DO UPDATE` so you can rerun the seed any time to refresh prices.

---

## REST API reference

All endpoints live on `http://localhost:5001`. CORS is wide open (`flask-cors`).

| Method | Path | Returns | Notes |
|---|---|---|---|
| GET | `/graph` | `{ tracks, nodes, edges }` | Full graph payload for D3. Each node has a `tracks: [slug, ...]` array. |
| GET | `/companies?limit=N` | `[{ticker, name, price}]` | Default limit 500 (was 20 originally). |
| GET | `/companies/<ticker>` | DB-backed company detail | Full row + linked investment track. |
| GET | `/companies/<ticker>/live` | **Fresh** Yahoo Finance pull | Bypasses Postgres entirely. Powers `stock.html`. |
| GET | `/companies/<ticker>/neighbors?type=&min_weight=&max_weight=&limit=` | `{ nodes, edges }` | Filtered graph expansion from one node. |
| GET | `/companies/<ticker>/news?limit=N` | News items via `yfinance.Ticker.news` | Title, link, publisher, summary, timestamp. |
| GET | `/tracks` | `[{slug, name, color, company_count}]` | Sorted by company count desc. |
| GET | `/tracks/<slug>` | `{ name, slug, color, description, market_leader, companies, company_count }` | Powers `track.html`. Companies sorted by market cap. |
| GET | `/tracks/<slug>/news?companies=N&per=M` | Aggregated news for top-N companies in the track | Default 5 companies × 3 items each. |
| GET | `/investment_tracks` | Legacy track listing | Kept for compat with the original task 4 routes. |
| GET | `/investment_tracks/<id>/companies` | Legacy | Kept for compat. |

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
- Left sidebar:
  - **Search** — fuzzy search by ticker or track name
  - **Companies** — scrollable list of all companies; pinned (on-graph) ones sorted to the top. Each row has a chevron to expand a dropdown showing that company's competitors, suppliers, etc. with per-entry +/✕ buttons. Toggling a row updates in-place — no full list rebuild, so open dropdowns stay open.
  - **Investment Tracks** — each track has a chevron dropdown listing its member companies and a toggle button to show/hide the whole track on the graph
  - **Edge legend** — bottom-left of the canvas
- Center: D3 force-directed graph. Parallel edges (same pair of nodes, different relationship type) render as offset quadratic bezier curves so both are visible.
- Right (on click): node detail panel with market cap, price, track badge, connections, link to full stock page
- Header: iPick.ai link, theme toggle

**Key implementation note:** the graph re-renders from scratch every time you toggle a track filter. See `renderGraph()` in `main.js`. This is necessary because the universe is too large to keep all 4200 nodes simulated at once.

### `track.html` — investment track detail
- URL: `track.html?slug=<track-slug>`
- Hero with name, description, market leader pill
- Sortable companies table (market cap / ticker / name / price / P/E)
- Live news feed via `/tracks/<slug>/news`

### `stock.html` — stock detail
- URL: `stock.html?ticker=<TICKER>`
- Hero with name, sector, price, market cap, P/E
- Stats grid: open/close/high/low/52w range/volume/EPS/forward P/E/dividend yield/beta/employees/website
- Live news feed via `/companies/<ticker>/news`
- All numbers come from `/companies/<ticker>/live` (fresh Yahoo Finance pull on every page load)

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

## Common dev tasks

### Add a new ticker to the graph
1. Add it to `ticker_track.json` with the right track name (or update from S3)
2. Re-run `python3 backend/db/seed_demo.py`

### Add a new investment track
1. Add `"NEWTKR": "My New Track"` entries to `ticker_track.json`
2. Re-run the seeder. The track row is auto-created.
3. (Optional) populate the description: `UPDATE investment_tracks SET description = '...' WHERE name = 'My New Track';`

### Add new relationships
1. Drop a JSON file in `task5/SeleniumAI_Task5/final_json/` matching the schema above
2. Re-run `python3 backend/db/seed_demo.py` (it calls `seed_supplier_subsidary.py` internally)

### Restart the backend after editing `main.py`
Flask debug mode auto-reloads top-level files most of the time, but **always restart manually** after editing helper modules — Python's import cache will hold the old version. `Ctrl+C` then `python3 backend/main.py` again.

### Wipe the DB and start fresh
```bash
docker compose -f backend/docker-compose.yml down -v   # -v drops the volume
docker compose -f backend/docker-compose.yml up -d
python3 backend/db/seed_demo.py
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: psycopg2` | `pip` and `python` are different interpreters (conda vs system) | `python3 -m pip install <pkg>` — always use `python3 -m pip` |
| `TypeError: unsupported operand type(s) for \|: 'type' and 'NoneType'` | Python 3.9 doesn't support `X \| Y` annotations | The `from __future__ import annotations` line at the top of the file should fix it; if you see it on a new file, add that import |
| `No module named 'dotenv'` | Importing `scraper.scraper` pulls in `ten_k_fetch` which needs `python-dotenv` | `python3 -m pip install python-dotenv beautifulsoup4` |
| Header badge says `demo` not `live` | Backend isn't running, `/graph` errored, or CORS blocked | Check `curl http://localhost:5001/graph`; check the browser devtools Network tab |
| Clicking a track shows nothing | (a) Backend not restarted after `/graph` SQL change, (b) `company_tracks` empty, (c) wrong slug | Restart backend; re-run `seed_demo.py`; verify with `curl http://localhost:5001/tracks` |
| Hover tooltip appears over empty space | Pre-fix bug where hidden nodes captured pointer events | Pull latest — `applyVisibility()` now disables pointer events |
| Track or stock page won't scroll | Pre-fix bug — `style.css` had `html, body { overflow: hidden }` | Pull latest — `track.css` overrides it for `.track-body` pages |
| `seed_demo.py` only seeds a few companies | yfinance rate-limited or many tickers don't exist | Check the per-batch progress output; re-run; consider raising `batch_pause` in `scraper.StockScraper.get_bulk()` |
| `WARN: Found orphan containers` from docker compose | Old containers from a previous compose project name | Harmless; clean with `docker rm -f backend-backend-1 backend-postgres-1` |
| Postgres connection refused | Container not up, or another postgres on 5433 | `docker ps`; if collision, change the host port in `backend/docker-compose.yml` |

---

## Known gaps & roadmap

These were called out in **Meeting 8 (4/6)** and the ongoing tracker:

- ❌ **Stock chart** on the stock page — needs a `/companies/<ticker>/history?range=1mo` endpoint wrapping `yf.Ticker(t).history()` plus a Chart.js or D3 line chart in `stock.html`. Probably the next thing to build.
- ❌ **Better news with citations** — current news is `yfinance.Ticker.news` (free, fast, but thin). Tracker calls out **Tavily** and **Firecrawl** as upgrade paths. The AI team owns this.
- ❌ **Per-track descriptions** — `investment_tracks.description` column exists but is null. Either AI team writes them or generate via LLM at seed time.
- ❌ **Logo / graphic design** — design task, not code.
- 🟡 **Multi-track companies in `relationships` metadata** — JSON-encoded as text, fine for now, but consider migrating to JSONB if you need to query inside it.
- 🟡 **`scraper/data.json`** (13MB snapshot) is no longer used by the live seed path. Keep as fallback or delete in a cleanup PR.
- 🟡 **Selenium news scraper** at `ai/pipeline/news_scraper.py` is unused — Flask uses `yfinance.Ticker.news` instead because Selenium is too heavy for per-request endpoints. Keep around for batch jobs.
- 🟡 **`seed_supplier_subsidary.py` filename** has a typo ("subsidary") — harmless but worth fixing if you rename anything nearby.

---

## Contributing & branching

Original branch hygiene from earlier in the project:
- `main` — production / demo branch (everything is merged here now)
- `*/task4` — individual Task 4 submissions (historical, all superseded)
- `backend`, `frontend`, `ai` — historical feature branches (all merged into main)

**For new work going forward:**
1. Branch off `main`: `git checkout -b yourname/feature-foo`
2. Use **conventional commits**: `feat(backend): ...`, `fix(frontend): ...`, `chore: ...`
3. Open a PR against `main`
4. Squash-merge once reviewed

### Commit message style

```
feat(backend): add /companies/:ticker/history endpoint

- Wraps yfinance.Ticker(t).history(period=range)
- Caches in-memory for 60s to dodge yfinance rate limits
- Used by the new stock chart on stock.html
```

Stick to imperative mood ("add", "fix", "remove"), keep the subject under ~70 chars, and explain *why* in the body when it isn't obvious from the diff.

---

## Quick reference card

```bash
# Setup (once)
python3 -m pip install -r backend/requirements.txt -r scraper/requirements.txt
docker compose -f backend/docker-compose.yml up -d

# Seed (anytime — pulls fresh Yahoo data)
python3 backend/db/seed_demo.py

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

---

**Questions?** Check `project_tracker.txt` for meeting notes and the team's task assignments. The design doc and Linear-style task tracker are linked from there.
