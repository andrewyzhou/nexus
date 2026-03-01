from fastapi import FastAPI, HTTPException, Query
from typing import Optional
import psycopg2
import psycopg2.extras
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Company Graph API", version="1.0.0")

# ----------------------------------------------------------------
# Database connection
# ----------------------------------------------------------------
def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        user=os.getenv("DB_USER", "bd"),
        password=os.getenv("DB_PASSWORD", "1020"),
        dbname=os.getenv("DB_NAME", "mydb")
    )


# ----------------------------------------------------------------
# GET /companies
# Supports filtering by sector, industry, country, currency,
# market cap range, stock price range, with pagination.
# ----------------------------------------------------------------
@app.get("/companies")
def get_companies(
    sector:    Optional[str]   = Query(None, description="Filter by sector e.g. Technology"),
    industry:  Optional[str]   = Query(None, description="Filter by industry e.g. Semiconductors"),
    country:   Optional[str]   = Query(None, description="Filter by country e.g. USA"),
    currency:  Optional[str]   = Query(None, description="Filter by currency e.g. USD"),
    min_cap:   Optional[int]   = Query(None, description="Minimum market cap"),
    max_cap:   Optional[int]   = Query(None, description="Maximum market cap"),
    min_price: Optional[float] = Query(None, description="Minimum stock price"),
    max_price: Optional[float] = Query(None, description="Maximum stock price"),
    limit:     int             = Query(50,   description="Max results to return"),
    offset:    int             = Query(0,    description="Pagination offset"),
):
    conditions = []
    params = []

    if sector:
        params.append(sector)
        conditions.append(f"sector = %s")
    if industry:
        params.append(industry)
        conditions.append(f"industry = %s")
    if country:
        params.append(country)
        conditions.append(f"country = %s")
    if currency:
        params.append(currency)
        conditions.append(f"currency = %s")
    if min_cap is not None:
        params.append(min_cap)
        conditions.append(f"market_cap >= %s")
    if max_cap is not None:
        params.append(max_cap)
        conditions.append(f"market_cap <= %s")
    if min_price is not None:
        params.append(min_price)
        conditions.append(f"stock_price >= %s")
    if max_price is not None:
        params.append(max_price)
        conditions.append(f"stock_price <= %s")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    query = f"""
        SELECT id, ticker, name, industry, sector, country, currency,
               stock_price, market_cap, employees, founded_year, created_at
        FROM companies
        {where}
        ORDER BY market_cap DESC NULLS LAST
        LIMIT %s OFFSET %s
    """
    count_query = f"SELECT COUNT(*) FROM companies {where}"

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(count_query, params)
            total = cur.fetchone()["count"]

            cur.execute(query, params + [limit, offset])
            rows = cur.fetchall()

        return {
            "total":   total,
            "limit":   limit,
            "offset":  offset,
            "results": [dict(r) for r in rows],
        }
    finally:
        conn.close()


# ----------------------------------------------------------------
# GET /companies/{id}
# Returns metadata for a single company
# ----------------------------------------------------------------
@app.get("/companies/{company_id}")
def get_company(company_id: int):
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, ticker, name, industry, sector, country, currency,
                       stock_price, market_cap, employees, founded_year, created_at
                FROM companies
                WHERE id = %s
                """,
                (company_id,)
            )
            row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Company with id {company_id} not found")

        return dict(row)
    finally:
        conn.close()


# ----------------------------------------------------------------
# GET /companies/{id}/neighbors
# Returns graph expansion data: { nodes, edges }
# Supports filtering by relationship_type, min_strength,
# neighbor country, neighbor sector
# ----------------------------------------------------------------
@app.get("/companies/{company_id}/neighbors")
def get_neighbors(
    company_id:        int,
    relationship_type: Optional[str]   = Query(None, description="Filter by type e.g. supplier, competitor, partner"),
    min_strength:      Optional[float] = Query(None, description="Minimum edge strength 0.0 to 1.0"),
    country:           Optional[str]   = Query(None, description="Filter neighbors by country"),
    sector:            Optional[str]   = Query(None, description="Filter neighbors by sector"),
    limit:             int             = Query(50,   description="Max edges to return"),
):
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:

            # verify root company exists
            cur.execute("SELECT * FROM companies WHERE id = %s", (company_id,))
            root = cur.fetchone()
            if not root:
                raise HTTPException(status_code=404, detail=f"Company with id {company_id} not found")

            # build edge query
            conditions = ["(r.company_a_id = %s OR r.company_b_id = %s)"]
            params = [company_id, company_id]

            if relationship_type:
                params.append(relationship_type)
                conditions.append("r.relationship_type = %s")
            if min_strength is not None:
                params.append(min_strength)
                conditions.append("r.strength >= %s")

            neighbor_conditions = []
            if country:
                params.append(country)
                neighbor_conditions.append("neighbor.country = %s")
            if sector:
                params.append(sector)
                neighbor_conditions.append("neighbor.sector = %s")

            neighbor_where = f"AND {' AND '.join(neighbor_conditions)}" if neighbor_conditions else ""
            params.append(limit)

            cur.execute(f"""
                SELECT
                    r.id              AS edge_id,
                    r.relationship_type,
                    r.direction,
                    r.strength,
                    r.description,
                    r.since_year,
                    r.company_a_id,
                    r.company_b_id,
                    CASE WHEN r.company_a_id = {company_id} THEN r.company_b_id
                         ELSE r.company_a_id
                    END AS neighbor_id,
                    neighbor.ticker,
                    neighbor.name,
                    neighbor.industry,
                    neighbor.sector,
                    neighbor.country,
                    neighbor.currency,
                    neighbor.stock_price,
                    neighbor.market_cap,
                    neighbor.employees,
                    neighbor.founded_year
                FROM relationships r
                JOIN companies neighbor
                  ON neighbor.id = CASE WHEN r.company_a_id = {company_id} THEN r.company_b_id
                                        ELSE r.company_a_id END
                WHERE {' AND '.join(conditions)}
                {neighbor_where}
                ORDER BY r.strength DESC NULLS LAST
                LIMIT %s
            """, params)

            rows = cur.fetchall()

        # build { nodes, edges } response
        nodes = {
            root["id"]: {
                "id":           root["id"],
                "ticker":       root["ticker"],
                "name":         root["name"],
                "industry":     root["industry"],
                "sector":       root["sector"],
                "country":      root["country"],
                "currency":     root["currency"],
                "stock_price":  float(root["stock_price"]) if root["stock_price"] else None,
                "market_cap":   root["market_cap"],
                "employees":    root["employees"],
                "founded_year": root["founded_year"],
                "is_root":      True,
            }
        }

        edges = []
        for row in rows:
            neighbor_id = row["neighbor_id"]
            if neighbor_id not in nodes:
                nodes[neighbor_id] = {
                    "id":           neighbor_id,
                    "ticker":       row["ticker"],
                    "name":         row["name"],
                    "industry":     row["industry"],
                    "sector":       row["sector"],
                    "country":      row["country"],
                    "currency":     row["currency"],
                    "stock_price":  float(row["stock_price"]) if row["stock_price"] else None,
                    "market_cap":   row["market_cap"],
                    "employees":    row["employees"],
                    "founded_year": row["founded_year"],
                    "is_root":      False,
                }

            edges.append({
                "id":                row["edge_id"],
                "source":            row["company_a_id"],
                "target":            row["company_b_id"],
                "relationship_type": row["relationship_type"],
                "direction":         row["direction"],
                "strength":          float(row["strength"]) if row["strength"] else None,
                "description":       row["description"],
                "since_year":        row["since_year"],
            })

        return {
            "nodes": list(nodes.values()),
            "edges": edges,
        }
    finally:
        conn.close()


# ----------------------------------------------------------------
# Health check
# ----------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}