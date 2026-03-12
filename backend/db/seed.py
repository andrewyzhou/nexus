import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "corporate_data.db"
DATA_PATH = Path(__file__).resolve().parents[2] / "scraper" / "data.json"
TRACKS_PATH = Path(__file__).resolve().parents[2] / "investment_tracks.json"

def seed():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    with open(DATA_PATH) as f:
        companies = json.load(f)

    print(f"Loaded {len(companies)} companies from JSON")

    for c in companies:
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
            c.get("ticker"),
            c.get("companyName"),
            c.get("exchange"),
            c.get("country"),
            c.get("sector"),
            c.get("industry"),
            c.get("currency"),
            c.get("price"),
            c.get("marketCap"),
            c.get("enterpriseValue"),
            c.get("trailingPE"),
            c.get("trailingEPS"),
            c.get("fullTimeEmployees"),
            c.get("website"),
            c.get("description")
        ))
    
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