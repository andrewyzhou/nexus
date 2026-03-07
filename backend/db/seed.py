import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "corporate_data.db"
DATA_PATH = Path(__file__).resolve().parents[2] / "scraper" / "data.json"

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

    conn.commit()
    conn.close()

    print("Database seeded successfully.")

if __name__ == "__main__":
    seed()