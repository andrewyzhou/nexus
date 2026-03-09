# FastAPI application entry point
# Initializes the app, registers routes, and starts the server
from flask import Flask, jsonify
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
    conn.close()

    if row is None:
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

    return jsonify(company)

if __name__ == "__main__":
    app.run(debug=True)
