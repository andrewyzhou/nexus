-- ============================================================
-- Nexus Graph Platform – Database Schema
-- ============================================================

-- Enable extension for uuid support (optional, using SERIAL PKs)
-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ------------------------------------------------------------
-- companies
-- One row per S&P 500 company (or equivalent starting node)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS companies (
    id             SERIAL PRIMARY KEY,
    ticker         VARCHAR(10)     NOT NULL UNIQUE,
    name           TEXT            NOT NULL,
    sector         TEXT            NOT NULL,
    industry       TEXT            NOT NULL,
    currency       VARCHAR(5)      NOT NULL DEFAULT 'USD',
    current_price  NUMERIC(12, 2)  NOT NULL,
    market_cap_b   NUMERIC(12, 2)  NOT NULL,   -- market cap in billions USD
    size           TEXT            NOT NULL,    -- 'large' | 'mid' | 'small'
    country        VARCHAR(50)     NOT NULL DEFAULT 'USA',
    created_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- Indexes for common filter patterns
CREATE INDEX IF NOT EXISTS idx_companies_sector       ON companies (sector);
CREATE INDEX IF NOT EXISTS idx_companies_size         ON companies (size);
CREATE INDEX IF NOT EXISTS idx_companies_market_cap   ON companies (market_cap_b DESC);
CREATE INDEX IF NOT EXISTS idx_companies_ticker       ON companies (ticker);

-- ------------------------------------------------------------
-- relationships
-- One row per directed edge between two companies
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS relationships (
    id          SERIAL PRIMARY KEY,
    source_id   INT             NOT NULL REFERENCES companies (id) ON DELETE CASCADE,
    target_id   INT             NOT NULL REFERENCES companies (id) ON DELETE CASCADE,
    type        TEXT            NOT NULL,   -- 'supplier' | 'partner' | 'competitor' | 'investor'
    weight      NUMERIC(5, 2)   NOT NULL DEFAULT 1.0,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- Prevent exact duplicate directed edges
    CONSTRAINT uq_relationship UNIQUE (source_id, target_id, type)
);

-- Indexes for graph traversal and filtering
CREATE INDEX IF NOT EXISTS idx_rel_source      ON relationships (source_id);
CREATE INDEX IF NOT EXISTS idx_rel_target      ON relationships (target_id);
CREATE INDEX IF NOT EXISTS idx_rel_type        ON relationships (type);
CREATE INDEX IF NOT EXISTS idx_rel_source_type ON relationships (source_id, type);
CREATE INDEX IF NOT EXISTS idx_rel_target_type ON relationships (target_id, type);
