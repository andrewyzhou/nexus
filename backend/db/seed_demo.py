"""
Live demo seed — pulls fresh data from Yahoo Finance every run.

Sources:
  - ticker_track.json              : ticker -> investment-track mapping (the
                                     universe of tickers we care about)
  - scraper/scraper.py             : StockScraper.get_bulk(...) — live Yahoo
                                     Finance fetch at ~80 stocks/sec
  - task5/SeleniumAI_Task5/...     : per-ticker relationship JSONs from the
                                     AI team

Run:
    python backend/db/seed_demo.py
    NEXUS_SEED_LIMIT=200 python backend/db/seed_demo.py   # cap for fast demo

Total runtime: ~60s for the full ~4300 tickers, ~5s for a 200-ticker cap.
"""
import json
import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATABASE_URL
from db.init import init_db
from db.seed import (
    TRACKS_PATH,
    create_tracks_tables,
    load_investment_tracks,
    safe_float,
    safe_int,
)
from db.seed_relationships import seed_relationships

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scraper"))
from scraper import StockScraper  # noqa: E402

AI_JSON_DIR = REPO_ROOT / "task5" / "SeleniumAI_Task5" / "final_json"


def collect_universe() -> list[str]:
    """Tickers we want priced: ticker_track.json keys + AI anchors, deduped."""
    tickers: set[str] = set()
    if TRACKS_PATH.exists():
        try:
            with TRACKS_PATH.open() as f:
                tickers.update(json.load(f).keys())
        except Exception as e:
            print(f"  ! could not parse {TRACKS_PATH}: {e}")
    if AI_JSON_DIR.exists():
        for path in AI_JSON_DIR.glob("*.json"):
            try:
                doc = json.loads(path.read_text())
            except Exception:
                continue
            if doc.get("ticker"):
                tickers.add(doc["ticker"])
            for rel in doc.get("related_stocks", []):
                if rel.get("ticker"):
                    tickers.add(rel["ticker"])
    return sorted(tickers)


def row_from_yahoo(entry: dict) -> tuple | None:
    ticker = entry.get("ticker")
    if not ticker:
        return None
    return (
        ticker,
        entry.get("companyName") or ticker,
        entry.get("exchange"),
        entry.get("industry") or "Unknown",
        entry.get("sector") or None,
        entry.get("country") or "Unknown",
        entry.get("currency") or "USD",
        safe_float(entry.get("price")),
        safe_int(entry.get("marketCap")),
        safe_int(entry.get("enterpriseValue")),
        safe_float(entry.get("trailingPE")),
        safe_float(entry.get("trailingEPS")),
        safe_int(entry.get("fullTimeEmployees")),
        entry.get("website") or None,
        entry.get("description") or None,
    )


INSERT_SQL = """
INSERT INTO companies (
    ticker, name, exchange, industry, sector, country, currency,
    price, market_cap, enterprise_value, pe_ratio, eps,
    employees, website, description
)
VALUES %s
ON CONFLICT (ticker) DO UPDATE SET
    name = EXCLUDED.name,
    exchange = EXCLUDED.exchange,
    industry = EXCLUDED.industry,
    sector = EXCLUDED.sector,
    country = EXCLUDED.country,
    currency = EXCLUDED.currency,
    price = EXCLUDED.price,
    market_cap = EXCLUDED.market_cap,
    enterprise_value = EXCLUDED.enterprise_value,
    pe_ratio = EXCLUDED.pe_ratio,
    eps = EXCLUDED.eps,
    employees = EXCLUDED.employees,
    website = EXCLUDED.website,
    description = EXCLUDED.description
"""


def main() -> None:
    print("== Nexus live seed (Yahoo Finance, fresh fetch) ==")
    init_db()

    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    create_tracks_tables(cursor)

    tickers = collect_universe()
    cap = int(os.getenv("NEXUS_SEED_LIMIT", "0")) or None
    if cap and len(tickers) > cap:
        print(f"NEXUS_SEED_LIMIT={cap} — capping {len(tickers)} → {cap}")
        tickers = tickers[:cap]

    print(f"Fetching {len(tickers)} tickers from Yahoo Finance (live)...")
    scraper = StockScraper()

    def progress(done, total, batch_num, total_batches, ok, fail):
        print(f"  batch {batch_num}/{total_batches}: {ok} ok, {fail} failed  ({done}/{total} total)")

    results = scraper.get_bulk(tickers, on_progress=progress)
    print(f"  fetched {len(results)} / {len(tickers)} tickers")

    rows = [r for r in (row_from_yahoo(e) for e in results) if r]
    print(f"  inserting {len(rows)} company rows...")
    psycopg2.extras.execute_values(cursor, INSERT_SQL, rows, page_size=500)
    conn.commit()

    print(f"Linking tracks from {TRACKS_PATH.name}...")
    unique, linked, missing = load_investment_tracks(cursor)
    conn.commit()
    print(f"  tracks={unique}  links={linked}  unmatched={missing}")

    print("Seeding relationships from task5 JSONs...")
    seed_relationships(conn=conn)

    conn.close()
    print("\nDone. Backend is ready to serve live data.")


if __name__ == "__main__":
    main()
