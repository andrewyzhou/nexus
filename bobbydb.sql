DROP TABLE IF EXISTS relationships;
DROP TABLE IF EXISTS companies;

CREATE TABLE companies (
    company_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_name VARCHAR(30) NOT NULL UNIQUE,
    industry VARCHAR(30) NOT NULL,
    current_price INT NOT NULL
);

INSERT INTO companies (company_name, industry, current_price)
VALUES 
('Google', 'Technology', 311),
('Tesla', 'Automobile', 261),
('Palantir', 'Defense', 142);


CREATE TABLE relationships (
    relation_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,   
    company_id INT REFERENCES companies(company_id),
    related_company VARCHAR(30) NOT NULL,
    relationship_type VARCHAR(30) NOT NULL
);

INSERT INTO relationships (company_id, related_company, relationship_type)
VALUES 
(1, 'Microsoft', 'competitor'), 
(2, 'Nvidia', 'partner');  

CREATE INDEX relationships_company_id
ON relationships (company_id);

SELECT * FROM relationships
JOIN companies ON relationships.company_id = companies.company_id;