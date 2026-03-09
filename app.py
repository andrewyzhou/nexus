from flask import Flask, jsonify
import psycopg2

app = Flask(__name__)

def get_connection():
    return psycopg2.connect(
        host="localhost",
        database="myapp",
        user="postgres",
        password="password",
        port=5433
    )

# 1️⃣ GET /companies
@app.route("/companies", methods=["GET"])
def get_companies():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, industry FROM companies;")
    rows = cur.fetchall()

    companies = []
    for row in rows:
        companies.append({
            "id": row[0],
            "name": row[1],
            "industry": row[2]
        })

    cur.close()
    conn.close()
    return jsonify(companies)

# 2️⃣ GET /companies/<id>
@app.route("/companies/<int:company_id>", methods=["GET"])
def get_company(company_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, industry FROM companies WHERE id = %s;", (company_id,))
    row = cur.fetchone()

    cur.close()
    conn.close()

    if row is None:
        return jsonify({"error": "Company not found"}), 404

    return jsonify({
        "id": row[0],
        "name": row[1],
        "industry": row[2]
    })

# 3️⃣ GET /companies/<id>/neighbors
@app.route("/companies/<int:company_id>/neighbors", methods=["GET"])
def get_neighbors(company_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT c.id, c.name, r.relationship_type
        FROM relationships r
        JOIN companies c ON c.id = r.company_b_id
        WHERE r.company_a_id = %s;
    """, (company_id,))

    rows = cur.fetchall()

    nodes = []
    edges = []

    for row in rows:
        nodes.append({
            "id": row[0],
            "name": row[1]
        })
        edges.append({
            "source": company_id,
            "target": row[0],
            "type": row[2]
        })

    cur.close()
    conn.close()

    return jsonify({
        "nodes": nodes,
        "edges": edges
    })

if __name__ == "__main__":
    app.run(debug=True, port=5001)