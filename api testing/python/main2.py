from flask import Flask, jsonify, request
from sqlalchemy import create_engine, text
from decimal import Decimal

app = Flask(__name__)

# ----------------------------------------------------------------
# Database connection
# Change these values if needed
# ----------------------------------------------------------------
DB_USER     = "bd"
DB_PASSWORD = "1020"
DB_HOST     = "localhost"
DB_PORT     = "5432"
DB_NAME     = "mydb"

engine = create_engine(
    "postgresql://bd:test123@localhost:5432/mydb"
)

def serialize(row):
    """Convert a SQLAlchemy row to a JSON-safe dict."""
    result = {}
    for key, value in row._mapping.items():
        if isinstance(value, Decimal):
            result[key] = float(value)
        else:
            result[key] = value
    return result


# ----------------------------------------------------------------
# GET /companies
# Supports filtering by sector, industry, country, currency,
# market cap range, stock price range, with pagination.
#
# Example: /companies?sector=Technology&min_cap=500000000000
# ----------------------------------------------------------------
@app.route("/companies", methods=["GET"])
def get_companies():
    sector    = request.args.get("sector")
    industry  = request.args.get("industry")
    country   = request.args.get("country")
    currency  = request.args.get("currency")
    min_cap   = request.args.get("min_cap",   type=int)
    max_cap   = request.args.get("max_cap",   type=int)
    min_price = request.args.get("min_price", type=float)
    max_price = request.args.get("max_price", type=float)
    limit     = request.args.get("limit",     type=int, default=50)
    offset    = request.args.get("offset",    type=int, default=0)

    conditions = []
    params = {}

    if sector:
        conditions.append("sector = :sector")
        params["sector"] = sector
    if industry:
        conditions.append("industry = :industry")
        params["industry"] = industry
    if country:
        conditions.append("country = :country")
        params["country"] = country
    if currency:
        conditions.append("currency = :currency")
        params["currency"] = currency
    if min_cap is not None:
        conditions.append("market_cap >= :min_cap")
        params["min_cap"] = min_cap
    if max_cap is not None:
        conditions.append("market_cap <= :max_cap")
        params["max_cap"] = max_cap
    if min_price is not None:
        conditions.append("stock_price >= :min_price")
        params["min_price"] = min_price
    if max_price is not None:
        conditions.append("stock_price <= :max_price")
        params["max_price"] = max_price

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with engine.connect() as conn:
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM companies {where}"), params
        ).scalar()

        rows = conn.execute(
            text(f"""
                SELECT id, ticker, name, industry, sector, country, currency,
                       stock_price, market_cap, employees, founded_year, created_at
                FROM companies
                {where}
                ORDER BY market_cap DESC NULLS LAST
                LIMIT :limit OFFSET :offset
            """),
            {**params, "limit": limit, "offset": offset}
        ).fetchall()

    return jsonify({
        "total":   total,
        "limit":   limit,
        "offset":  offset,
        "results": [serialize(r) for r in rows],
    })


# ----------------------------------------------------------------
# GET /companies/<id>
# Returns metadata for a single company
#
# Example: /companies/1
# ----------------------------------------------------------------
@app.route("/companies/<int:company_id>", methods=["GET"])
def get_company(company_id):
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT id, ticker, name, industry, sector, country, currency,
                       stock_price, market_cap, employees, founded_year, created_at
                FROM companies
                WHERE id = :id
            """),
            {"id": company_id}
        ).fetchone()

    if not row:
        return jsonify({"error": f"Company with id {company_id} not found"}), 404

    return jsonify(serialize(row))


# ----------------------------------------------------------------
# GET /companies/<id>/neighbors
# Returns graph expansion data: { nodes, edges }
# Supports filtering by relationship_type, min_strength,
# neighbor country, neighbor sector
#
# Example: /companies/1/neighbors?relationship_type=supplier
# ----------------------------------------------------------------
@app.route("/companies/<int:company_id>/neighbors", methods=["GET"])
def get_neighbors(company_id):
    relationship_type = request.args.get("relationship_type")
    min_strength      = request.args.get("min_strength", type=float)
    country           = request.args.get("country")
    sector            = request.args.get("sector")
    limit             = request.args.get("limit", type=int, default=50)

    with engine.connect() as conn:
        # verify root company exists
        root = conn.execute(
            text("SELECT * FROM companies WHERE id = :id"),
            {"id": company_id}
        ).fetchone()

        if not root:
            return jsonify({"error": f"Company with id {company_id} not found"}), 404

        # build edge query
        conditions = ["(r.company_a_id = :cid OR r.company_b_id = :cid)"]
        params = {"cid": company_id}

        if relationship_type:
            conditions.append("r.relationship_type = :relationship_type")
            params["relationship_type"] = relationship_type
        if min_strength is not None:
            conditions.append("r.strength >= :min_strength")
            params["min_strength"] = min_strength

        neighbor_conditions = []
        if country:
            neighbor_conditions.append("neighbor.country = :country")
            params["country"] = country
        if sector:
            neighbor_conditions.append("neighbor.sector = :sector")
            params["sector"] = sector

        neighbor_where = f"AND {' AND '.join(neighbor_conditions)}" if neighbor_conditions else ""
        params["limit"] = limit

        rows = conn.execute(
            text(f"""
                SELECT
                    r.id              AS edge_id,
                    r.relationship_type,
                    r.direction,
                    r.strength,
                    r.description,
                    r.since_year,
                    r.company_a_id,
                    r.company_b_id,
                    CASE WHEN r.company_a_id = :cid THEN r.company_b_id
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
                  ON neighbor.id = CASE WHEN r.company_a_id = :cid THEN r.company_b_id
                                        ELSE r.company_a_id END
                WHERE {' AND '.join(conditions)}
                {neighbor_where}
                ORDER BY r.strength DESC NULLS LAST
                LIMIT :limit
            """),
            params
        ).fetchall()

    # build { nodes, edges } response
    root_data = serialize(root)
    nodes = {
        root_data["id"]: {**root_data, "is_root": True}
    }

    edges = []
    for row in rows:
        r = serialize(row)
        neighbor_id = r["neighbor_id"]

        if neighbor_id not in nodes:
            nodes[neighbor_id] = {
                "id":           neighbor_id,
                "ticker":       r["ticker"],
                "name":         r["name"],
                "industry":     r["industry"],
                "sector":       r["sector"],
                "country":      r["country"],
                "currency":     r["currency"],
                "stock_price":  r["stock_price"],
                "market_cap":   r["market_cap"],
                "employees":    r["employees"],
                "founded_year": r["founded_year"],
                "is_root":      False,
            }

        edges.append({
            "id":                r["edge_id"],
            "source":            r["company_a_id"],
            "target":            r["company_b_id"],
            "relationship_type": r["relationship_type"],
            "direction":         r["direction"],
            "strength":          r["strength"],
            "description":       r["description"],
            "since_year":        r["since_year"],
        })

    return jsonify({
        "nodes": list(nodes.values()),
        "edges": edges,
    })


# ----------------------------------------------------------------
# Health check
# ----------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True, port=3000)