# FastAPI application entry point
# Initializes the app, registers routes, and starts the server
from flask import Flask, jsonify, request
import sqlite3
from pathlib import Path

app = Flask(__name__)

DB_PATH = Path(__file__).resolve().parent / "db" / "corporate_data.db"

@app.route("/companies")
def get_companies():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT ticker, name, price FROM companies LIMIT 20")
    rows = cursor.fetchall()

    conn.close()

    companies = [
        {"ticker": r[0], "name": r[1], "price": r[2]}
        for r in rows
    ]

    return jsonify(companies)

@app.route("/companies/<ticker>")
def get_company(ticker):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            ticker,
            name,
            exchange,
            country,
            sector,
            industry,
            currency,
            price,
            market_cap,
            enterprise_value,
            pe_ratio,
            eps,
            employees,
            website,
            description,
            created_at
        FROM companies
        WHERE ticker = ?
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
        "created_at": row[15]
    }

    cursor.execute("""
        SELECT t.id, t.name
        FROM investment_tracks t
        JOIN company_tracks ct ON ct.track_id = t.id
        JOIN companies c ON c.id = ct.company_id
        WHERE c.ticker = ?
    """, (ticker,))
    track = cursor.fetchone()
    company["investment_track"] = {"id": track[0], "name": track[1]} if track else None

    conn.close()
    return jsonify(company)

@app.route("/companies/<ticker>/neighbors")
def get_neighbors(ticker):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT ticker FROM companies WHERE ticker = ?", (ticker,))
    if cursor.fetchone() is None:
        conn.close()
        return jsonify({"error": "Company not found"}), 404

    rel_type = request.args.get("type")
    min_weight = request.args.get("min_weight", type=float)
    max_weight = request.args.get("max_weight", type=float)
    limit = request.args.get("limit", default=50, type=int)

    conditions = ["(r.source_ticker = ? OR r.target_ticker = ?)"]
    params = [ticker, ticker]

    if rel_type:
        conditions.append("r.relationship_type = ?")
        params.append(rel_type)
    if min_weight is not None:
        conditions.append("r.weight >= ?")
        params.append(min_weight)
    if max_weight is not None:
        conditions.append("r.weight <= ?")
        params.append(max_weight)

    params.append(limit)

    cursor.execute(f"""
        SELECT r.id, r.source_ticker, r.target_ticker, r.relationship_type, r.weight, r.metadata
        FROM relationships r
        WHERE {' AND '.join(conditions)}
        ORDER BY r.weight DESC
        LIMIT ?
    """, params)

    edge_rows = cursor.fetchall()

    neighbor_tickers = set()
    for row in edge_rows:
        neighbor_tickers.add(row[1])
        neighbor_tickers.add(row[2])
    neighbor_tickers.discard(ticker)

    all_tickers = list(neighbor_tickers | {ticker})
    placeholders = ",".join("?" * len(all_tickers))
    cursor.execute(f"""
        SELECT ticker, name, sector, industry, price, market_cap
        FROM companies
        WHERE ticker IN ({placeholders})
    """, all_tickers)

    company_rows = cursor.fetchall()
    conn.close()

    nodes = [
        {
            "ticker": r[0],
            "name": r[1],
            "sector": r[2],
            "industry": r[3],
            "price": r[4],
            "market_cap": r[5],
        }
        for r in company_rows
    ]

    edges = [
        {
            "id": r[0],
            "source": r[1],
            "target": r[2],
            "type": r[3],
            "weight": r[4],
            "metadata": r[5],
        }
        for r in edge_rows
    ]

    return jsonify({"nodes": nodes, "edges": edges})

@app.route("/investment_tracks", strict_slashes=False)
def get_investment_tracks():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT id, name FROM investment_tracks")
    track_rows = cursor.fetchall()

    tracks = []
    for track_id, track_name in track_rows:
        cursor.execute("""
            SELECT c.ticker, c.name
            FROM companies c
            JOIN company_tracks ct ON ct.company_id = c.id
            WHERE ct.track_id = ?
        """, (track_id,))
        tracks.append({
            "name": track_name,
            "companies": [
                {"ticker": r[0], "name": r[1]}
                for r in cursor.fetchall()
            ]
        })

    conn.close()
    return jsonify(tracks)


@app.route("/investment_tracks/<int:track_id>/companies")
def get_track_companies(track_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM investment_tracks WHERE id = ?", (track_id,))
    if cursor.fetchone() is None:
        conn.close()
        return jsonify({"error": "Track not found"}), 404

    cursor.execute("""
        SELECT c.ticker, c.name
        FROM companies c
        JOIN company_tracks ct ON ct.company_id = c.id
        WHERE ct.track_id = ?
    """, (track_id,))

    companies = [{"ticker": r[0], "name": r[1]} for r in cursor.fetchall()]
    conn.close()
    return jsonify(companies)


if __name__ == "__main__":
    app.run(debug=True)
