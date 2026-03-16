import psycopg2
from config import DATABASE_URL

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS companies (
    id SERIAL PRIMARY KEY,
    ticker TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    exchange TEXT,
    country TEXT,
    sector TEXT,
    industry TEXT,
    currency TEXT,
    price REAL,
    market_cap BIGINT,
    enterprise_value BIGINT,
    pe_ratio REAL,
    eps REAL,
    employees INTEGER,
    website TEXT,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_RELATIONSHIPS_TABLE = """
CREATE TABLE IF NOT EXISTS relationships (
    id SERIAL PRIMARY KEY,
    source_ticker TEXT NOT NULL,
    target_ticker TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_ticker) REFERENCES companies(ticker),
    FOREIGN KEY (target_ticker) REFERENCES companies(ticker),
    UNIQUE (source_ticker, target_ticker, relationship_type)
);
"""

CREATE_TRACKS_TABLE = """
CREATE TABLE IF NOT EXISTS investment_tracks (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    description TEXT
);
"""

CREATE_COMPANY_TRACKS_TABLE = """
CREATE TABLE IF NOT EXISTS company_tracks (
    track_id INTEGER NOT NULL REFERENCES investment_tracks(id) ON DELETE CASCADE,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    UNIQUE (track_id, company_id)
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_companies_ticker ON companies(ticker);",
    "CREATE INDEX IF NOT EXISTS idx_companies_sector ON companies(sector);",
    "CREATE INDEX IF NOT EXISTS idx_companies_industry ON companies(industry);",
    "CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships(source_ticker);",
    "CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships(target_ticker);",
    "CREATE INDEX IF NOT EXISTS idx_rel_type ON relationships(relationship_type);",
    "CREATE INDEX IF NOT EXISTS idx_rel_source_type ON relationships(source_ticker, relationship_type);",
    "CREATE INDEX IF NOT EXISTS idx_rel_target_type ON relationships(target_ticker, relationship_type);",
    "CREATE INDEX IF NOT EXISTS idx_company_tracks_track ON company_tracks(track_id);",
    "CREATE INDEX IF NOT EXISTS idx_company_tracks_company ON company_tracks(company_id);",
]

def init_db():
    print("Initializing database...")

    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    cursor.execute(CREATE_TABLE)
    cursor.execute(CREATE_RELATIONSHIPS_TABLE)
    cursor.execute(CREATE_TRACKS_TABLE)
    cursor.execute(CREATE_COMPANY_TRACKS_TABLE)

    for index_sql in CREATE_INDEXES:
        cursor.execute(index_sql)

    conn.commit()
    conn.close()

    print("Database initialized successfully.")

if __name__ == "__main__":
    init_db()
