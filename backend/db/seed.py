import json
import psycopg2
from pathlib import Path
import yfinance as yf
import pandas as pd
import requests
from io import StringIO
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATABASE_URL

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACKS_CANDIDATES = [
    REPO_ROOT / "ticker_track.json",
    REPO_ROOT / "investment_tracks.json",
    REPO_ROOT / "frontend" / "investment_tracks.json",
]
TRACKS_PATH = next((p for p in TRACKS_CANDIDATES if p.exists()), TRACKS_CANDIDATES[0])

import os
SEED_LIMIT = int(os.getenv("NEXUS_SEED_LIMIT", "0")) or None  # 0 / unset = no cap


def safe_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def create_tracks_tables(cursor):
    """Create tracks tables if they don't exist yet (idempotent)."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS investment_tracks (
            id          SERIAL PRIMARY KEY,
            name        TEXT UNIQUE NOT NULL,
            description TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS company_tracks (
            track_id    INTEGER NOT NULL REFERENCES investment_tracks(id) ON DELETE CASCADE,
            company_id  INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            UNIQUE(track_id, company_id)
        )
    """)
    print("Tracks tables ready")


def seed():
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    # Ensure tracks tables exist before we need them
    create_tracks_tables(cursor)

    # Fetch full S&P 500 ticker list from Wikipedia
    print("Fetching S&P 500 ticker list from Wikipedia...")
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        html = requests.get(url, headers=headers).text
        tickers = pd.read_html(StringIO(html))[0]["Symbol"].tolist()
        tickers = [t.replace(".", "-") for t in tickers]
        print(f"Found {len(tickers)} tickers")
    except Exception as e:
        print(f"Failed to fetch from Wikipedia: {e} — falling back to hardcoded list")
        tickers = [...]

    if SEED_LIMIT and len(tickers) > SEED_LIMIT:
        tickers = tickers[:SEED_LIMIT]
        print(f"NEXUS_SEED_LIMIT={SEED_LIMIT} — capping to first {len(tickers)} tickers")

    print(f"Fetching data for {len(tickers)} companies from Yahoo Finance...\n")

    success_count = 0
    error_count = 0

    for i, ticker in enumerate(tickers, 1):
        try:
            info = yf.Ticker(ticker).info

            # NOT NULL columns get a fallback so we never crash on missing data
            industry = info.get("industry") or "Unknown"
            country  = info.get("country")  or "Unknown"
            currency = info.get("currency") or "USD"
            name     = info.get("longName") or info.get("shortName") or ticker

            cursor.execute("""
                INSERT INTO companies (
                    ticker, name, exchange, industry, sector, country, currency,
                    price, market_cap, enterprise_value, pe_ratio, eps,
                    employees, website, description
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker) DO UPDATE SET
                    name             = EXCLUDED.name,
                    exchange         = EXCLUDED.exchange,
                    industry         = EXCLUDED.industry,
                    sector           = EXCLUDED.sector,
                    country          = EXCLUDED.country,
                    currency         = EXCLUDED.currency,
                    price            = EXCLUDED.price,
                    market_cap       = EXCLUDED.market_cap,
                    enterprise_value = EXCLUDED.enterprise_value,
                    pe_ratio         = EXCLUDED.pe_ratio,
                    eps              = EXCLUDED.eps,
                    employees        = EXCLUDED.employees,
                    website          = EXCLUDED.website,
                    description      = EXCLUDED.description
            """, (
                ticker,
                name,
                info.get("exchange"),
                industry,
                info.get("sector"),
                country,
                currency,
                safe_float(info.get("currentPrice")),
                safe_int(info.get("marketCap")),
                safe_int(info.get("enterpriseValue")),
                safe_float(info.get("trailingPE")),
                safe_float(info.get("trailingEps")),
                safe_int(info.get("fullTimeEmployees")),
                info.get("website"),
                info.get("longBusinessSummary"),
            ))

            success_count += 1
            print(f"[{i}/{len(tickers)}] ✓ {ticker} — {name}")

        except Exception as e:
            error_count += 1
            print(f"[{i}/{len(tickers)}] ✗ Skipping {ticker}: {e}")

    print(f"\nCompanies done — {success_count} seeded, {error_count} skipped\n")

    unique_track_count, linked_count, skipped_count = load_investment_tracks(cursor)

    conn.commit()
    conn.close()

    print("\n" + "=" * 50)
    print("SEED COMPLETE")
    print("=" * 50)
    print(f"  Companies seeded:       {success_count}")
    print(f"  Companies skipped:      {error_count}")
    print(f"  Unique tracks inserted: {unique_track_count}")
    print(f"  Company-track links:    {linked_count}")
    print(f"  Tickers not in DB:      {skipped_count}")
    print("=" * 50)


def load_investment_tracks(cursor):
    try:
        with open(TRACKS_PATH) as f:
            ticker_tracks = json.load(f)
    except FileNotFoundError:
        print(f"Warning: investment_tracks.json not found at {TRACKS_PATH}. Skipping.")
        return 0, 0, 0
    except json.JSONDecodeError as e:
        print(f"Warning: Could not parse investment_tracks.json: {e}. Skipping.")
        return 0, 0, 0

    print(f"Loaded {len(ticker_tracks)} ticker-track mappings")

    unique_tracks = set(ticker_tracks.values())
    track_ids = {}

    for track_name in unique_tracks:
        cursor.execute(
            "INSERT INTO investment_tracks (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            (track_name,)
        )
        cursor.execute(
            "SELECT id FROM investment_tracks WHERE name = %s",
            (track_name,)
        )
        track_ids[track_name] = cursor.fetchone()[0]

    print(f"Inserted {len(unique_tracks)} unique tracks")

    linked = 0
    skipped_missing = 0

    for ticker, track_name in ticker_tracks.items():
        cursor.execute("SELECT id FROM companies WHERE ticker = %s", (ticker,))
        row = cursor.fetchone()

        if row is None:
            print(f"  Skipping missing ticker: {ticker}")
            skipped_missing += 1
            continue

        cursor.execute("""
            INSERT INTO company_tracks (track_id, company_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
        """, (track_ids[track_name], row[0]))
        linked += 1

    print(f"Linked {linked} companies to tracks ({skipped_missing} tickers not found)")
    return len(unique_tracks), linked, skipped_missing


if __name__ == "__main__":
    seed()
