CREATE TABLE companies (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) UNIQUE NOT NULL,
    name VARCHAR(255),
    sector VARCHAR(100),
    size VARCHAR(20),
    current_price NUMERIC(10,2)
);

CREATE TABLE relationships (
    id SERIAL PRIMARY KEY,
    company_a_id INT REFERENCES companies(id),
    company_b_id INT REFERENCES companies(id),
    type VARCHAR(50)
);

CREATE INDEX idx_sector ON companies(sector);
CREATE INDEX idx_size ON companies(size);
CREATE INDEX idx_rel_type ON relationships(type);

INSERT INTO companies (ticker, name, sector, size, current_price) VALUES
('AAPL',  'Apple',              'Technology',  'large', 189.50),
('MSFT',  'Microsoft',          'Technology',  'large', 375.20),
('GOOGL', 'Alphabet',           'Technology',  'large', 140.30),
('AMZN',  'Amazon',             'Technology',  'large', 178.90),
('JPM',   'JPMorgan',           'Financials',  'large', 165.80),
('BAC',   'Bank of America',    'Financials',  'large',  33.20),
('JNJ',   'Johnson & Johnson',  'Healthcare',  'large', 160.20),
('PFE',   'Pfizer',             'Healthcare',  'large',  28.50),
('XOM',   'ExxonMobil',         'Energy',      'large', 110.20),
('CVX',   'Chevron',            'Energy',      'large', 152.40);

INSERT INTO relationships (company_a_id, company_b_id, type) VALUES
(1, 2, 'competitor'),
(1, 3, 'competitor'),
(2, 3, 'competitor'),
(1, 4, 'competitor'),
(5, 6, 'competitor'),
(7, 8, 'competitor'),
(9, 10, 'competitor'),
(1, 4, 'partner'),
(2, 4, 'partner');