from typing import Optional, List, Any
from fastapi import FastAPI, Query, Path, HTTPException
from db import pool

app = FastAPI(title="Nexus API")


# ----------------------------
# GET /companies
# starting companies (S&P 500)
# filters: sector, size
# ----------------------------
@app.get("/companies")
def get_companies(
    sector: Optional[str] = Query(default=None),
    size: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=10000),
):
    where = ["c.is_starting = TRUE"]  # <-- CHANGE THIS if your column is different
    params: List[Any] = []

    if sector:
        where.append("c.sector = %s")
        params.append(sector)

    if size:
        where.append("c.size = %s")
        params.append(size)

    params.extend([limit, offset])

    sql = f"""
        SELECT c.id, c.ticker, c.name, c.sector, c.size, c.market_cap
        FROM companies c
        WHERE {" AND ".join(where)}
        ORDER BY c.market_cap DESC NULLS LAST, c.name ASC
        LIMIT %s
        OFFSET %s
    """

    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    companies = [
        {
            "id": r[0],
            "ticker": r[1],
            "name": r[2],
            "sector": r[3],
            "size": r[4],
            "market_cap": r[5],
        }
        for r in rows
    ]

    return {"companies": companies, "limit": limit, "offset": offset}


# ----------------------------
# GET /companies/{id}
# metadata for single company
# ----------------------------
@app.get("/companies/{company_id}")
def get_company(company_id: int = Path(..., gt=0)):
    sql = """
        SELECT c.id, c.ticker, c.name, c.sector, c.size, c.market_cap
        FROM companies c
        WHERE c.id = %s
    """

    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, [company_id])
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Company not found")

    return {
        "id": row[0],
        "ticker": row[1],
        "name": row[2],
        "sector": row[3],
        "size": row[4],
        "market_cap": row[5],
    }


# ---------------------------------------
# GET /companies/{id}/neighbors
# returns { nodes, edges }
# filters: relationship type(s), size, direction, limit
# ---------------------------------------
@app.get("/companies/{company_id}/neighbors")
def get_neighbors(
    company_id: int = Path(..., gt=0),
    type: Optional[str] = Query(default=None),       # single relationship type
    types: Optional[str] = Query(default=None),      # comma list relationship types
    size: Optional[str] = Query(default=None),       # neighbor company size filter
    direction: str = Query(default="both"),          # out | in | both
    limit: int = Query(default=50, ge=1, le=500),
):
    if direction not in {"out", "in", "both"}:
        raise HTTPException(status_code=400, detail="direction must be out, in, or both")

    rel_types: Optional[List[str]] = None
    if types:
        rel_types = [t.strip() for t in types.split(",") if t.strip()]
    elif type:
        rel_types = [type.strip()]

    # Build edge WHERE + params
    edge_where = []
    params: List[Any] = []

    # company id in WHERE
    if direction == "out":
        edge_where.append("r.src_company_id = %s")
        params.append(company_id)
    elif direction == "in":
        edge_where.append("r.dst_company_id = %s")
        params.append(company_id)
    else:
        edge_where.append("(r.src_company_id = %s OR r.dst_company_id = %s)")
        params.extend([company_id, company_id])

    if rel_types:
        edge_where.append("r.type = ANY(%s)")
        params.append(rel_types)

    params.append(limit)

    sql_edges = f"""
        WITH edge_rows AS (
            SELECT
                r.id,
                r.src_company_id AS source,
                r.dst_company_id AS target,
                r.type,
                r.weight,
                CASE
                    WHEN r.src_company_id = %s THEN r.dst_company_id
                    ELSE r.src_company_id
                END AS neighbor_id
            FROM relationships r
            WHERE {" AND ".join(edge_where)}
            ORDER BY r.weight DESC NULLS LAST, r.id ASC
            LIMIT %s
        )
        SELECT id, source, target, type, weight, neighbor_id
        FROM edge_rows
    """

    # NOTE: the CASE needs company_id again at the start
    case_params = [company_id] + params

    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql_edges, case_params)
            edge_rows = cur.fetchall()

    # Get center company
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, ticker, name, sector, size, market_cap FROM companies WHERE id = %s",
                [company_id],
            )
            center = cur.fetchone()

    if not center:
        raise HTTPException(status_code=404, detail="Company not found")

    nodes = [{
        "id": center[0],
        "ticker": center[1],
        "name": center[2],
        "sector": center[3],
        "size": center[4],
        "market_cap": center[5],
    }]

    neighbor_ids = sorted({r[5] for r in edge_rows})
    if neighbor_ids:
        sql_neighbors = """
            SELECT id, ticker, name, sector, size, market_cap
            FROM companies
            WHERE id = ANY(%s)
        """
        neigh_params: List[Any] = [neighbor_ids]

        if size:
            sql_neighbors += " AND size = %s"
            neigh_params.append(size)

        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql_neighbors, neigh_params)
                neigh_rows = cur.fetchall()

        nodes.extend([{
            "id": r[0],
            "ticker": r[1],
            "name": r[2],
            "sector": r[3],
            "size": r[4],
            "market_cap": r[5],
        } for r in neigh_rows])

    edges = [{
        "id": r[0],
        "source": r[1],
        "target": r[2],
        "type": r[3],
        "weight": r[4],
    } for r in edge_rows]

    return {"nodes": nodes, "edges": edges}