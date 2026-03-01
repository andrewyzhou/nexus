-- ============================================================
-- TABLES
-- ============================================================

CREATE TABLE companies (
    id            SERIAL PRIMARY KEY,
    ticker        VARCHAR(10)    UNIQUE NOT NULL,
    name          VARCHAR(255)   NOT NULL,
    industry      VARCHAR(100)   NOT NULL,
    sector        VARCHAR(100),
    country       VARCHAR(100)   NOT NULL,
    currency      CHAR(3)        NOT NULL,
    stock_price   NUMERIC(12, 2),
    market_cap    BIGINT,
    employees     INT,
    founded_year  INT,
    created_at    TIMESTAMPTZ    DEFAULT NOW()
);

CREATE TABLE relationships (
    id                SERIAL PRIMARY KEY,
    company_a_id      INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    company_b_id      INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    relationship_type VARCHAR(50) NOT NULL,  -- e.g. 'supplier', 'competitor', 'partner', 'subsidiary', 'investor'
    direction         VARCHAR(10) DEFAULT 'undirected', -- 'a_to_b', 'b_to_a', 'undirected'
    strength          NUMERIC(3, 2),         -- 0.00 to 1.00, optional weight
    description       TEXT,
    since_year        INT,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT no_self_relationship CHECK (company_a_id <> company_b_id)
);


-- ============================================================
-- DUMMY DATA: COMPANIES
-- ============================================================

INSERT INTO companies (ticker, name, industry, sector, country, currency, stock_price, market_cap, employees, founded_year) VALUES
('AAPL',  'Apple Inc.',                  'Consumer Electronics',  'Technology',      'USA',     'USD', 189.50,  2950000000000, 164000, 1976),
('MSFT',  'Microsoft Corporation',       'Software',              'Technology',      'USA',     'USD', 415.20,  3080000000000, 221000, 1975),
('TSLA',  'Tesla Inc.',                  'Electric Vehicles',     'Automotive',      'USA',     'USD', 245.00,   780000000000,  140000, 2003),
('NVDA',  'NVIDIA Corporation',          'Semiconductors',        'Technology',      'USA',     'USD', 875.40,  2160000000000,  29600, 1993),
('AMZN',  'Amazon.com Inc.',             'E-Commerce',            'Consumer',        'USA',     'USD', 185.30,  1920000000000,  1525000, 1994),
('GOOGL', 'Alphabet Inc.',               'Internet Services',     'Technology',      'USA',     'USD', 175.60,  2200000000000,  182000, 1998),
('BABA',  'Alibaba Group',               'E-Commerce',            'Consumer',        'China',   'CNY', 78.20,   200000000000,  235000, 1999),
('TSMC',  'Taiwan Semiconductor',        'Semiconductors',        'Technology',      'Taiwan',  'TWD', 142.00,   740000000000,   73000, 1987),
('SMSN',  'Samsung Electronics',         'Consumer Electronics',  'Technology',      'Korea',   'KRW', 58.40,   350000000000,  270000, 1969),
('INTC',  'Intel Corporation',           'Semiconductors',        'Technology',      'USA',     'USD', 35.10,   148000000000,  124800, 1968),
('AMD',   'Advanced Micro Devices',      'Semiconductors',        'Technology',      'USA',     'USD', 168.90,   273000000000,  26000, 1969),
('SONY',  'Sony Group Corporation',      'Consumer Electronics',  'Technology',      'Japan',   'JPY', 87.30,   108000000000,  113000, 1946),
('FORD',  'Ford Motor Company',          'Automobiles',           'Automotive',      'USA',     'USD', 12.40,    49000000000,  177000, 1903),
('GM',    'General Motors',              'Automobiles',           'Automotive',      'USA',     'USD', 46.80,    53000000000,  163000, 1908),
('PANASONIC', 'Panasonic Holdings',      'Electronics',           'Technology',      'Japan',   'JPY', 9.80,     14000000000,  233000, 1918);


-- ============================================================
-- DUMMY DATA: RELATIONSHIPS
-- ============================================================

INSERT INTO relationships (company_a_id, company_b_id, relationship_type, direction, strength, description, since_year) VALUES
-- Supplier relationships
(8,  1,  'supplier',    'a_to_b', 0.95, 'TSMC manufactures chips for Apple (A-series, M-series)',       2010),
(8,  4,  'supplier',    'a_to_b', 0.98, 'TSMC is primary manufacturer for NVIDIA GPUs',                 2005),
(8,  11, 'supplier',    'a_to_b', 0.90, 'TSMC manufactures AMD processors and GPUs',                    2009),
(9,  1,  'supplier',    'a_to_b', 0.70, 'Samsung supplies OLED displays and memory chips to Apple',     2012),
(15, 3,  'supplier',    'a_to_b', 0.80, 'Panasonic supplies battery cells for Tesla vehicles',          2010),

-- Competitor relationships
(1,  9,  'competitor',  'undirected', 0.85, 'Compete in smartphones, tablets, and consumer electronics', NULL),
(1,  12, 'competitor',  'undirected', 0.60, 'Compete in consumer electronics and entertainment',         NULL),
(3,  13, 'competitor',  'undirected', 0.75, 'Compete in electric and traditional vehicle markets',       NULL),
(3,  14, 'competitor',  'undirected', 0.70, 'Compete in electric and traditional vehicle markets',       NULL),
(13, 14, 'competitor',  'undirected', 0.95, 'Direct competitors in the US automotive market',            NULL),
(4,  10, 'competitor',  'undirected', 0.80, 'Compete in datacenter and PC GPU/CPU markets',              NULL),
(4,  11, 'competitor',  'undirected', 0.85, 'Compete in GPU and datacenter chip markets',                NULL),
(10, 11, 'competitor',  'undirected', 0.90, 'Direct competitors in CPU and semiconductor markets',       NULL),
(5,  7,  'competitor',  'undirected', 0.80, 'Compete in global e-commerce markets',                      NULL),

-- Partner relationships
(2,  1,  'partner',     'undirected', 0.60, 'Microsoft Office and services on Apple platforms',          1997),
(4,  2,  'partner',     'a_to_b', 0.90, 'NVIDIA GPUs power Microsoft Azure AI infrastructure',          2019),
(3,  2,  'partner',     'undirected', 0.55, 'Azure cloud services used by Tesla for data workloads',     2020),
(5,  2,  'partner',     'undirected', 0.65, 'Amazon uses Azure for some hybrid cloud workloads',         2021),

-- Investor relationships
(2,  3,  'investor',    'a_to_b', 0.40, 'Microsoft explored EV software investment in Tesla',            2021),

-- Subsidiary / acquisition relationships
(6,  5,  'competitor',  'undirected', 0.70, 'Compete in cloud (AWS vs GCP) and advertising markets',    NULL);


-- ============================================================
-- INDEXES
-- ============================================================

-- Companies: common filter columns
CREATE INDEX idx_companies_industry    ON companies (industry);
CREATE INDEX idx_companies_sector      ON companies (sector);
CREATE INDEX idx_companies_country     ON companies (country);
CREATE INDEX idx_companies_currency    ON companies (currency);
CREATE INDEX idx_companies_stock_price ON companies (stock_price);
CREATE INDEX idx_companies_market_cap  ON companies (market_cap);

-- Relationships: look up all edges for a given company
CREATE INDEX idx_relationships_company_a      ON relationships (company_a_id);
CREATE INDEX idx_relationships_company_b      ON relationships (company_b_id);

-- Relationships: filter by type
CREATE INDEX idx_relationships_type           ON relationships (relationship_type);

-- Relationships: combined index for graph traversal queries
CREATE INDEX idx_relationships_a_type         ON relationships (company_a_id, relationship_type);
CREATE INDEX idx_relationships_b_type         ON relationships (company_b_id, relationship_type);