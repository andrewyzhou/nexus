DROP TABLE IF EXISTS companies;
DROP TABLE IF EXISTS relationships;

CREATE TABLE companies (
	unique_id uuid DEFAULT gen_random_uuid(),
	name text,
	ticker varchar,
    sector text,
	industries text[],
	currency char,
	current_price money,
	size_category varchar, -- between 10 and 200 B
    market_cap_billions integer,
	PRIMARY KEY (unique_id)
);

CREATE INDEX name_index ON companies(name);
CREATE INDEX currency_index ON companies(currency);

CREATE TABLE relationships (
	id uuid DEFAULT gen_random_uuid(),
	company_1_ticker varchar,
    company_2_ticker varchar,
	type text,
	is_directional boolean,
	PRIMARY KEY (id)
);

CREATE INDEX type_index ON relationships(type);
CREATE INDEX directional_index ON relationships(is_directional);

INSERT INTO companies (name, ticker, sector, industries, currency, current_price, size_category, market_cap_billions) VALUES (
	'Apple',
    'AAPL',
    'Technology',
    ARRAY ['Consumer Electronics'],
    '$',
    272.14,
    'BIG',
    4000
);

INSERT INTO companies (name, ticker, sector, industries, currency, current_price, size_category, market_cap_billions) VALUES (
	'Google',
    'GOOG',
    'Communication Services',
    ARRAY ['Internet Content & Information'],
    '$',
    310.92,
    'BIG',
    3761
);

INSERT INTO companies (name, ticker, sector, industries, currency, current_price, size_category, market_cap_billions) VALUES (
	'Johnson & Johnson',
    'JNJ',
    'Healthcare',
    ARRAY ['Drug Manufacturers - General'],
    '$',
    246.28,
    'BIG',
    594
);

INSERT INTO companies (name, ticker, sector, industries, currency, current_price, size_category, market_cap_billions) VALUES (
	'Duke Energy Corporation',
    'DUK',
    'Utilities',
    ARRAY ['Utilities - Regulated Electric'],
    '$',
    128.46,
    'MID',
    99
);

INSERT INTO companies (name, ticker, sector, industries, currency, current_price, size_category, market_cap_billions) VALUES (
	'Eli Lilly',
    'LLY',
    'Healthcare',
    ARRAY ['Drug Manufacturers - General'],
    '$',
    1042.15,
    'BIG',
    983
);

INSERT INTO companies (name, ticker, sector, industries, currency, current_price, size_category, market_cap_billions) VALUES (
	'NVIDIA Corp',
    'NVDA',
    'Technology',
    ARRAY ['Semiconductors'],
    '$',
    192.85,
    'BIG',
    4695
);

INSERT INTO companies (name, ticker, sector, industries, currency, current_price, size_category, market_cap_billions) VALUES (
	'Microsoft Corp',
    'MSFT',
    'Technology',
    ARRAY ['Software - Infrastructure'],
    '$',
    389.0,
    'BIG',
    2891
);


INSERT INTO relationships (company_1_ticker, company_2_ticker, type, is_directional) VALUES (
	'AAPL',
    'MSFT',
    'Competitor',
    False
);

INSERT INTO relationships (company_1_ticker, company_2_ticker, type, is_directional) VALUES (
	'GOOG',
    'MSFT',
    'Competitor',
    False
);

INSERT INTO relationships (company_1_ticker, company_2_ticker, type, is_directional) VALUES (
	'GOOG',
    'AAPL',
    'Competitor',
    False
);

INSERT INTO relationships (company_1_ticker, company_2_ticker, type, is_directional) VALUES (
	'AAPL',
    'NVDA',
    'Competitor',
    False
);

INSERT INTO relationships (company_1_ticker, company_2_ticker, type, is_directional) VALUES (
	'JNJ',
    'LLY',
    'Competitor',
    False
);










