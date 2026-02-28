from flask import Flask, jsonify, request
import psycopg2
import psycopg2.extras

app = Flask(__name__)

def get_conn():
    return psycopg2.connect(host="localhost", port=5433, dbname="nexusdb", user="nexus", password="password")


# GET /companies
@app.route("/companies")
def get_companies():
    sector = request.args.get("sector")
    size = request.args.get("size")

    query = "SELECT * FROM companies WHERE 1=1"
    params = []

    if sector:
        query += " AND sector = %s"
        params.append(sector)
    if size:
        query += " AND size = %s"
        params.append(size)

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# GET /companies/:id
@app.route("/companies/<int:id>")
def get_company(id):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM companies WHERE id = %s", (id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify(dict(row))


# GET /companies/:id/neighbors
@app.route("/companies/<int:id>/neighbors")
def get_neighbors(id):
    rel_type = request.args.get("type")
    size = request.args.get("size")

    query = """
        SELECT r.id, r.company_a_id, r.company_b_id, r.type
        FROM relationships r
        WHERE r.company_a_id = %s OR r.company_b_id = %s
    """
    params = [id, id]

    if rel_type:
        query += " AND r.type = %s"
        params.append(rel_type)

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(query, params)
    edges_raw = cur.fetchall()

    neighbor_ids = set()
    for e in edges_raw:
        neighbor_ids.add(e["company_a_id"])
        neighbor_ids.add(e["company_b_id"])
    neighbor_ids.discard(id)

    node_query = "SELECT * FROM companies WHERE id = ANY(%s)"
    node_params = [list(neighbor_ids | {id})]
    if size:
        node_query += " AND size = %s"
        node_params.append(size)

    cur.execute(node_query, node_params)
    nodes = [dict(r) for r in cur.fetchall()]
    conn.close()

    edges = [{"id": e["id"], "source": e["company_a_id"], "target": e["company_b_id"], "type": e["type"]} for e in edges_raw]

    return jsonify({"nodes": nodes, "edges": edges})


if __name__ == "__main__":
    app.run(debug=True, port=5001)