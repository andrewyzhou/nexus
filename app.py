from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://admin:password@localhost:5432/ipick_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


# ------------------------
# GET /companies
# ------------------------
@app.route('/companies', methods=['GET'])
def get_companies():
    sector = request.args.get('sector')
    min_cap = request.args.get('min_cap')

    sql = "SELECT * FROM companies WHERE 1=1"
    params = {}

    if sector:
        sql += " AND sector = :sector"
        params['sector'] = sector

    if min_cap:
        sql += " AND market_cap >= :min_cap"
        params['min_cap'] = min_cap

    result = db.session.execute(db.text(sql), params).fetchall()

    return jsonify([dict(row._mapping) for row in result])


# ------------------------
# GET /companies/<id>
# ------------------------
@app.route('/companies/<int:id>', methods=['GET'])
def get_company(id):
    result = db.session.execute(
        db.text("SELECT * FROM companies WHERE id = :id"),
        {"id": id}
    ).fetchone()

    if not result:
        return jsonify({"error": "Company not found"}), 404

    return jsonify(dict(result._mapping))


# ------------------------
# GET /companies/<id>/neighbors
# ------------------------
@app.route('/companies/<int:id>/neighbors', methods=['GET'])
def get_neighbors(id):
    rel_type = request.args.get('type')

    sql = """
        SELECT r.*, c1.name as source_name, c2.name as target_name
        FROM relationships r
        JOIN companies c1 ON r.source_company_id = c1.id
        JOIN companies c2 ON r.target_company_id = c2.id
        WHERE r.source_company_id = :id OR r.target_company_id = :id
    """

    params = {"id": id}

    if rel_type:
        sql += " AND r.relationship_type = :type"
        params["type"] = rel_type

    relationships = db.session.execute(db.text(sql), params).fetchall()

    nodes = {}
    edges = []

    for r in relationships:
        # Add source node
        nodes[r.source_company_id] = {
            "id": r.source_company_id,
            "name": r.source_name
        }

        # Add target node
        nodes[r.target_company_id] = {
            "id": r.target_company_id,
            "name": r.target_name
        }

        edges.append({
            "source": r.source_company_id,
            "target": r.target_company_id,
            "type": r.relationship_type,
            "confidence": float(r.confidence_score)
        })

    return jsonify({
        "nodes": list(nodes.values()),
        "edges": edges
    })


if __name__ == '__main__':
    app.run(debug=True)