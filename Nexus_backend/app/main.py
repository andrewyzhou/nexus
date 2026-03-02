from fastapi import FastAPI, HTTPException
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI()

def get_connection():
    return psycopg2.connect(
        host="localhost",
        port=5434,          # IMPORTANT (we used 5434)
        database="nexus",
        user="nexus",
        password="password"
    )

old_filtered = [
        {"id": 1, "name": "Apple", "sector": "Technology", "size": 5000},
        {"id": 2, "name": "Tesla", "sector": "Automotive", "size": 300},
        {"id": 3, "name": "JPMorgan", "sector": "Finance", "size": 2000}
    ]

filtered = [
        {"id": 1, "name": "Apple", "sector": "Technology", "size": 5000},
        {"id": 2, "name": "Tesla", "sector": "Automotive", "size": 300},
        {"id": 3, "name": "JPMorgan", "sector": "Finance", "size": 2000}
    ]

old_relationships = [
    {"source": 1, "target": 2, "type": "supplier"},
    {"source": 1, "target": 3, "type": "investor"},
    {"source": 2, "target": 3, "type": "partner"}
    ]

relationships = [
    {"source": 1, "target": 2, "type": "supplier"},
    {"source": 1, "target": 3, "type": "investor"},
    {"source": 2, "target": 3, "type": "partner"}
    ]

@app.get("/companies")
def get_companies(sector: str = None, size: int = None):
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    query = "SELECT * FROM companies WHERE 1=1"
    params = []

    if sector:
        query += " AND sector = %s"
        params.append(sector)

    if size:
        query += " AND size >= %s"
        params.append(size)

    cursor.execute(query, params)
    companies = cursor.fetchall()

    cursor.close()
    conn.close()

    return companies

@app.get("/companies/{id}")
def get_company(id: int):
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("SELECT * FROM companies WHERE id = %s", (id,))
    company = cursor.fetchone()

    cursor.close()
    conn.close()

    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    return company

@app.get("/companies/{id}/neighbors")
def get_neighbors(
    id: int,
    relationship_type: str = None,
    min_size: int = None
):
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    # Build relationship query
    query = "SELECT * FROM relationships WHERE (source = %s OR target = %s)"
    params = [id, id]

    if relationship_type:
        query += " AND type = %s"
        params.append(relationship_type)

    cursor.execute(query, params)
    edges = cursor.fetchall()

    # Extract neighbor IDs
    neighbor_ids = set()
    for edge in edges:
        if edge["source"] != id:
            neighbor_ids.add(edge["source"])
        if edge["target"] != id:
            neighbor_ids.add(edge["target"])

    # Fetch neighbor companies
    if neighbor_ids:
        company_query = "SELECT * FROM companies WHERE id = ANY(%s)"
        company_params = [list(neighbor_ids)]

        if min_size:
            company_query += " AND size >= %s"
            company_params.append(min_size)

        cursor.execute(company_query, company_params)
        nodes = cursor.fetchall()
    else:
        nodes = []

    cursor.close()
    conn.close()

    return {
        "nodes": nodes,
        "edges": edges
    }