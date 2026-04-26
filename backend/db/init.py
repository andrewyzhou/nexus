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

CREATE_ARTICLE_BODIES_TABLE = """
CREATE TABLE IF NOT EXISTS article_bodies (
    url         TEXT PRIMARY KEY,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    body        TEXT,
    status      TEXT NOT NULL
);
"""

CREATE_NEWS_SUMMARIES_TABLE = """
CREATE TABLE IF NOT EXISTS news_summaries (
    ticker         TEXT NOT NULL,
    articles_hash  TEXT NOT NULL,
    generated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    headline       TEXT NOT NULL,
    bullets        JSONB NOT NULL,
    sources        JSONB NOT NULL,
    model          TEXT NOT NULL,
    PRIMARY KEY (ticker, articles_hash)
);
"""

# item_type: 'company' | 'track'
# item_id:   ticker (lowercased) for company, slug for track
# label:     display label captured at write time so we can render the row
#            without joining back to companies/investment_tracks
CREATE_USER_RECENT_VIEWS_TABLE = """
CREATE TABLE IF NOT EXISTS user_recent_views (
    firebase_uid  TEXT NOT NULL,
    item_type     TEXT NOT NULL,
    item_id       TEXT NOT NULL,
    label         TEXT NOT NULL,
    viewed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (firebase_uid, item_type, item_id)
);
"""

CREATE_USER_SAVED_ITEMS_TABLE = """
CREATE TABLE IF NOT EXISTS user_saved_items (
    firebase_uid  TEXT NOT NULL,
    item_type     TEXT NOT NULL,
    item_id       TEXT NOT NULL,
    label         TEXT NOT NULL,
    saved_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (firebase_uid, item_type, item_id)
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
    "CREATE INDEX IF NOT EXISTS idx_article_bodies_fetched ON article_bodies(fetched_at);",
    "CREATE INDEX IF NOT EXISTS idx_news_summaries_ticker_time ON news_summaries(ticker, generated_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_recent_views_user_time ON user_recent_views(firebase_uid, viewed_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_saved_items_user_time ON user_saved_items(firebase_uid, saved_at DESC);",
]

def init_db():
    print("Initializing database...")

    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    cursor.execute(CREATE_TABLE)
    cursor.execute(CREATE_RELATIONSHIPS_TABLE)
    cursor.execute(CREATE_TRACKS_TABLE)
    cursor.execute(CREATE_COMPANY_TRACKS_TABLE)
    cursor.execute(CREATE_ARTICLE_BODIES_TABLE)
    cursor.execute(CREATE_NEWS_SUMMARIES_TABLE)
    cursor.execute(CREATE_USER_RECENT_VIEWS_TABLE)
    cursor.execute(CREATE_USER_SAVED_ITEMS_TABLE)

    for index_sql in CREATE_INDEXES:
        cursor.execute(index_sql)

    conn.commit()
    conn.close()

    print("Database initialized successfully.")

if __name__ == "__main__":
    init_db()
