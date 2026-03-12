import json
import sqlite3
from pathlib import Path
import yfinance as yf

DB_PATH = Path(__file__).resolve().parent / "corporate_data.db"
TRACKS_PATH = Path(__file__).resolve().parents[2] / "investment_tracks.json"

def seed():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    tickers = [
    "AAPL","MSFT","GOOGL","AMZN","META","NVDA","TSLA","BRK-B",
    "AVGO","LLY","JPM","V","MA","UNH","XOM","HD","PG","COST"
    ]

    print(f"Fetching {len(tickers)} companies from Yahoo Finance")

    for ticker in tickers:

        try:
            info = yf.Ticker(ticker).info

            cursor.execute("""
            INSERT OR IGNORE INTO companies (
                ticker, name, exchange, country,
                sector, industry, currency, price,
                market_cap, enterprise_value,
                pe_ratio, eps, employees,
                website, description
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ticker,
                info.get("longName"),
                info.get("exchange"),
                info.get("country"),
                info.get("sector"),
                info.get("industry"),
                info.get("currency"),
                info.get("currentPrice"),
                info.get("marketCap"),
                info.get("enterpriseValue"),
                info.get("trailingPE"),
                info.get("trailingEps"),
                info.get("fullTimeEmployees"),
                info.get("website"),
                info.get("longBusinessSummary")
            ))

        except Exception as e:
            print(f"Skipping {ticker}: {e}")
        
    print("Companies inserted")

    load_investment_tracks(cursor)

    conn.commit()
    conn.close()

    print("Database seeded successfully.")


def load_investment_tracks(cursor):
    with open(TRACKS_PATH) as f:
        ticker_tracks = json.load(f)

    print(f"Loaded {len(ticker_tracks)} ticker-track mappings")

    unique_tracks = set(ticker_tracks.values())

    track_ids = {}

    for track_name in unique_tracks:
        cursor.execute(
            "INSERT OR IGNORE INTO investment_tracks (name) VALUES (?)",
            (track_name,)
        )

        cursor.execute(
            "SELECT id FROM investment_tracks WHERE name = ?",
            (track_name,)
        )

        track_id = cursor.fetchone()[0]
        track_ids[track_name] = track_id

    print(f"Inserted {len(unique_tracks)} unique tracks")

    for ticker, track_name in ticker_tracks.items():

        cursor.execute(
            "SELECT id FROM companies WHERE ticker = ?",
            (ticker,)
        )

        row = cursor.fetchone()

        if row is None:
            print(f"Skipping missing ticker: {ticker}")
            continue

        company_id = row[0]
        track_id = track_ids[track_name]

        cursor.execute("""
            INSERT OR IGNORE INTO company_tracks (track_id, company_id)
            VALUES (?, ?)
        """, (track_id, company_id))

if __name__ == "__main__":
    seed()