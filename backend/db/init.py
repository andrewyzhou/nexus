import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "corporate_data.db"

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    exchange TEXT,
    country TEXT,
    sector TEXT,
    industry TEXT,
    currency TEXT,
    price REAL,
    market_cap INTEGER,
    enterprise_value INTEGER,
    pe_ratio REAL,
    eps REAL,
    employees INTEGER,
    website TEXT,
    description TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_companies_ticker ON companies(ticker);",
    "CREATE INDEX IF NOT EXISTS idx_companies_sector ON companies(sector);",
    "CREATE INDEX IF NOT EXISTS idx_companies_industry ON companies(industry);",
]

def init_db():
    print("Initializing database...")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(CREATE_TABLE)

    for index_sql in CREATE_INDEXES:
        cursor.execute(index_sql)

    conn.commit()
    conn.close()

    print("Database initialized successfully.")

if __name__ == "__main__":
    init_db()