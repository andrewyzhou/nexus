"""
Live demo seed — populates the database from real prescraped data, no mocks,
no slow yfinance round-trips.

Sources:
  - scraper/data.json              : 4788 tickers prescraped via scraper/scraper.py
  - ticker_track.json              : ticker -> investment-track mapping (from S3)
  - task5/SeleniumAI_Task5/...     : per-ticker relationship JSONs from the AI team

Run:
    python backend/db/seed_demo.py

Total runtime: ~5–15 seconds for the full 4788-ticker load.
"""
import json
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
SCRAPER_DATA = REPO_ROOT / "scraper" / "data.json"


def row_from_scraper(entry: dict) -> tuple | None:
    ticker = entry.get("ticker")
    if not ticker:
        return None
    name = entry.get("companyName") or ticker
    return (
        ticker,
        name,
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


def seed_companies_from_scraper(cursor) -> int:
    if not SCRAPER_DATA.exists():
        raise SystemExit(
            f"scraper/data.json missing at {SCRAPER_DATA}\n"
            "Run scraper/scraper.py first or pull the file from the data branch."
        )

    print(f"Loading {SCRAPER_DATA.relative_to(REPO_ROOT)}...")
    with SCRAPER_DATA.open() as f:
        entries = json.load(f)
    print(f"  parsed {len(entries)} ticker records")

    rows = [r for r in (row_from_scraper(e) for e in entries) if r]
    print(f"  inserting {len(rows)} rows...")
    psycopg2.extras.execute_values(cursor, INSERT_SQL, rows, page_size=500)
    return len(rows)


def main() -> None:
    print("== Nexus live seed (scraper data) ==")
    init_db()

    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    create_tracks_tables(cursor)

    inserted = seed_companies_from_scraper(cursor)
    conn.commit()
    print(f"Companies seeded: {inserted}")

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
