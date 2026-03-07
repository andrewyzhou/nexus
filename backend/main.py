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

if __name__ == "__main__":
    app.run(debug=True)