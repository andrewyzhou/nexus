from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = \
    'postgresql://nexus:nexus@localhost:5433/nexus'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


class Company(db.Model):
    __tablename__ = "companies"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    industry = db.Column(db.String)
    sector = db.Column(db.String)
    currency = db.Column(db.String)
    current_price = db.Column(db.Numeric)
    market_cap = db.Column(db.BigInteger)


class Relationship(db.Model):
    __tablename__ = "relationships"

    id = db.Column(db.Integer, primary_key=True)
    source_company_id = db.Column(db.Integer)
    target_company_id = db.Column(db.Integer)
    relationship_type = db.Column(db.String)
    confidence = db.Column(db.Numeric)


@app.route("/companies")
def get_companies():
    sector = request.args.get("sector")
    min_market_cap = request.args.get("min_market_cap", type=int)

    query = Company.query

    if sector:
        query = query.filter_by(sector=sector)

    if min_market_cap:
        query = query.filter(Company.market_cap >= min_market_cap)

    companies = query.all()

    return jsonify([
        {
            "id": c.id,
            "name": c.name,
            "sector": c.sector,
            "market_cap": c.market_cap
        }
        for c in companies
    ])


@app.route("/companies/<int:id>")
def get_company(id):
    company = Company.query.get_or_404(id)

    return jsonify({
        "id": company.id,
        "name": company.name,
        "industry": company.industry,
        "sector": company.sector,
        "market_cap": company.market_cap
    })


@app.route("/companies/<int:id>/neighbors")
def get_neighbors(id):
    relationship_type = request.args.get("relationship_type")

    query = Relationship.query.filter(
        or_(
            Relationship.source_company_id == id,
            Relationship.target_company_id == id
        )
    )

    if relationship_type:
        query = query.filter(Relationship.relationship_type == relationship_type)

    relationships = query.all()

    company_ids = set()
    for r in relationships:
        company_ids.add(r.source_company_id)
        company_ids.add(r.target_company_id)

    companies = Company.query.filter(
        Company.id.in_(company_ids)
    ).all()

    return jsonify({
        "nodes": [
            {"id": c.id, "name": c.name, "sector": c.sector}
            for c in companies
        ],
        "edges": [
            {"source": r.source_company_id, "target": r.target_company_id, "type": r.relationship_type}
            for r in relationships
        ]
    })


if __name__ == "__main__":
    app.run(debug=True)