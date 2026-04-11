from flask import Flask, jsonify, request
from flask_cors import CORS
import hashlib
import psycopg2
import psycopg2.extras
from config import DATABASE_URL

app = Flask(__name__)
CORS(app)


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def track_color(track_name: str) -> str:
    """Stable pastel color for a track name (so the frontend gets consistent colors)."""
    h = int(hashlib.md5(track_name.encode()).hexdigest()[:6], 16)
    palette = [
        "#00d4ff", "#f59e0b", "#10b981", "#ef4444", "#a78bfa",
        "#ec4899", "#22d3ee", "#84cc16", "#f97316", "#6366f1",
    ]
    return palette[h % len(palette)]


def slugify(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")


@app.route("/companies")
def get_companies():
    conn = get_conn()
    cursor = conn.cursor()

    limit = request.args.get("limit", default=500, type=int)
    cursor.execute("SELECT ticker, name, price FROM companies LIMIT %s", (limit,))
    rows = cursor.fetchall()
    conn.close()

    return jsonify([
        {"ticker": r[0], "name": r[1], "price": r[2]}
        for r in rows
    ])


@app.route("/companies/<ticker>")
def get_company(ticker):
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            ticker, name, exchange, country, sector, industry, currency,
            price, market_cap, enterprise_value, pe_ratio, eps,
            employees, website, description, created_at
        FROM companies
        WHERE ticker = %s
    """, (ticker,))

    row = cursor.fetchone()
    if row is None:
        conn.close()
        return jsonify({"error": "Company not found"}), 404

    company = {
        "ticker": row[0],
        "name": row[1],
        "exchange": row[2],
        "country": row[3],
        "sector": row[4],
        "industry": row[5],
        "currency": row[6],
        "price": row[7],
        "market_cap": row[8],
        "enterprise_value": row[9],
        "pe_ratio": row[10],
        "eps": row[11],
        "employees": row[12],
        "website": row[13],
        "description": row[14],
        "created_at": str(row[15]),
    }

    cursor.execute("""
        SELECT t.id, t.name
        FROM investment_tracks t
        JOIN company_tracks ct ON ct.track_id = t.id
        JOIN companies c ON c.id = ct.company_id
        WHERE c.ticker = %s
    """, (ticker,))
    track = cursor.fetchone()
    company["investment_track"] = {"id": track[0], "name": track[1]} if track else None

    conn.close()
    return jsonify(company)


@app.route("/companies/<ticker>/neighbors")
def get_neighbors(ticker):
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT ticker FROM companies WHERE ticker = %s", (ticker,))
    if cursor.fetchone() is None:
        conn.close()
        return jsonify({"error": "Company not found"}), 404

    rel_type = request.args.get("type")
    min_weight = request.args.get("min_weight", type=float)
    max_weight = request.args.get("max_weight", type=float)
    limit = request.args.get("limit", default=50, type=int)

    conditions = ["(r.source_ticker = %s OR r.target_ticker = %s)"]
    params = [ticker, ticker]

    if rel_type:
        conditions.append("r.relationship_type = %s")
        params.append(rel_type)
    if min_weight is not None:
        conditions.append("r.weight >= %s")
        params.append(min_weight)
    if max_weight is not None:
        conditions.append("r.weight <= %s")
        params.append(max_weight)

    params.append(limit)

    cursor.execute(f"""
        SELECT r.id, r.source_ticker, r.target_ticker, r.relationship_type, r.weight, r.metadata
        FROM relationships r
        WHERE {' AND '.join(conditions)}
        ORDER BY r.weight DESC
        LIMIT %s
    """, params)

    edge_rows = cursor.fetchall()

    neighbor_tickers = set()
    for row in edge_rows:
        neighbor_tickers.add(row[1])
        neighbor_tickers.add(row[2])
    neighbor_tickers.discard(ticker)

    all_tickers = list(neighbor_tickers | {ticker})
    cursor.execute("""
        SELECT ticker, name, sector, industry, price, market_cap
        FROM companies
        WHERE ticker = ANY(%s)
    """, (all_tickers,))

    company_rows = cursor.fetchall()
    conn.close()

    nodes = [
        {"ticker": r[0], "name": r[1], "sector": r[2], "industry": r[3], "price": r[4], "market_cap": r[5]}
        for r in company_rows
    ]
    edges = [
        {"id": r[0], "source": r[1], "target": r[2], "type": r[3], "weight": r[4], "metadata": r[5]}
        for r in edge_rows
    ]

    return jsonify({"nodes": nodes, "edges": edges})


@app.route("/investment_tracks", strict_slashes=False)
def get_investment_tracks():
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name FROM investment_tracks")
    track_rows = cursor.fetchall()

    tracks = []
    for track_id, track_name in track_rows:
        cursor.execute("""
            SELECT c.ticker, c.name
            FROM companies c
            JOIN company_tracks ct ON ct.company_id = c.id
            WHERE ct.track_id = %s
        """, (track_id,))
        tracks.append({
            "name": track_name,
            "companies": [{"ticker": r[0], "name": r[1]} for r in cursor.fetchall()]
        })

    conn.close()
    return jsonify(tracks)


@app.route("/investment_tracks/<int:track_id>/companies")
def get_track_companies(track_id):
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM investment_tracks WHERE id = %s", (track_id,))
    if cursor.fetchone() is None:
        conn.close()
        return jsonify({"error": "Track not found"}), 404

    cursor.execute("""
        SELECT c.ticker, c.name
        FROM companies c
        JOIN company_tracks ct ON ct.company_id = c.id
        WHERE ct.track_id = %s
    """, (track_id,))

    companies = [{"ticker": r[0], "name": r[1]} for r in cursor.fetchall()]
    conn.close()
    return jsonify(companies)


@app.route("/graph")
def get_graph():
    """
    Aggregated graph payload consumed by the frontend.
    Shape matches frontend/data/mock.json so the D3 graph renders unchanged.
    """
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name FROM investment_tracks ORDER BY name")
    track_rows = cursor.fetchall()
    tracks = [
        {"id": slugify(name), "label": name, "color": track_color(name)}
        for _, name in track_rows
    ]
    track_id_by_db_id = {db_id: slugify(name) for db_id, name in track_rows}

    cursor.execute("""
        SELECT c.ticker, c.name, c.sector, c.market_cap, c.price, c.description, ct.track_id
        FROM companies c
        LEFT JOIN company_tracks ct ON ct.company_id = c.id
    """)
    nodes = []
    seen = set()
    for ticker, name, sector, market_cap, price, description, db_track_id in cursor.fetchall():
        if ticker in seen:
            continue
        seen.add(ticker)
        nodes.append({
            "id": ticker.lower(),
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "marketCap": (market_cap or 0) / 1e9,
            "price": price,
            "track": track_id_by_db_id.get(db_track_id, "uncategorized"),
            "description": description or "",
        })

    cursor.execute("""
        SELECT source_ticker, target_ticker, relationship_type
        FROM relationships
    """)
    edges = [
        {"source": s.lower(), "target": t.lower(), "type": rt}
        for s, t, rt in cursor.fetchall()
    ]

    conn.close()
    return jsonify({"tracks": tracks, "nodes": nodes, "edges": edges})


if __name__ == "__main__":
    app.run(debug=True, port=5001)
