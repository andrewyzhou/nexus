from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Integer, String, Float, Text, ForeignKey

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://nexus:nexus@127.0.0.1:5432/nexus_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class Companies(db.Model):
    id = db.Column(Integer, primary_key=True, autoincrement=True)
    name = db.Column(String(200), nullable=False, unique=True)
    industries = db.Column(String(100))
    currency = db.Column(String(3), nullable=False)  
    current_price = db.Column(Float)
    market_cap = db.Column(Float)
    
    __table_args__ = (
        db.Index('idx_industries', 'industries'),
        db.Index('idx_market_cap', 'market_cap'),
    )
   
    def __repr__(self):
        return f'<Company {self.name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'industries': self.industries,
            'currency': self.currency,
            'current_price': self.current_price,
            'market_cap': self.market_cap
        }

class Relationships(db.Model):
    id = db.Column(Integer, primary_key=True, autoincrement=True)
    company_id_1 = db.Column(Integer, ForeignKey('companies.id'), nullable=False)
    company_id_2 = db.Column(Integer, ForeignKey('companies.id'), nullable=False)
    relationship_type = db.Column(String(100), nullable=False)
    
    __table_args__ = (
        db.Index('idx_company1', 'company_id_1'),
        db.Index('idx_company2', 'company_id_2'),
        db.Index('idx_company_pair', 'company_id_1', 'company_id_2'),
    )

    def __repr__(self):
        return f'<Relationship {self.relationship_type} between {self.company_id_1} and {self.company_id_2}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'company_id_1': self.company_id_1,
            'company_id_2': self.company_id_2,
            'relationship_type': self.relationship_type
        }

@app.route('/companies', methods=['GET'])
def get_companies():
    query = Companies.query
    
    sector = request.args.get('sector')
    if sector:
        query = query.filter(Companies.industries == sector)
    
    min_market_cap = request.args.get('min_market_cap', type=float)
    if min_market_cap is not None:
        query = query.filter(Companies.market_cap >= min_market_cap)
    
    max_market_cap = request.args.get('max_market_cap', type=float)
    if max_market_cap is not None:
        query = query.filter(Companies.market_cap <= max_market_cap)
    
    companies = query.all()
    return jsonify([company.to_dict() for company in companies]), 200

@app.route('/companies/<int:id>/', methods=['GET'])
def get_company(id):
    company = Companies.query.get(id)
    if not company:
        return jsonify({'error': 'Company not found'}), 404
    return jsonify(company.to_dict()), 200

@app.route('/companies/<int:id>/neighbors', methods=['GET'])
def get_neighbors(id):
    company = Companies.query.get(id)
    if not company:
        return jsonify({'error': 'Company not found'}), 404
    
    query = db.session.query(Relationships).filter(
        (Relationships.company_id_1 == id) | (Relationships.company_id_2 == id)
    )
    
    relationship_type = request.args.get('relationship_type')
    if relationship_type:
        query = query.filter(Relationships.relationship_type == relationship_type)
    
    relationships = query.all()
    
    nodes = {}
    edges = []
    
    nodes[id] = company.to_dict()
    
    for rel in relationships:
        neighbor_id = rel.company_id_2 if rel.company_id_1 == id else rel.company_id_1
        
        if neighbor_id not in nodes:
            neighbor = Companies.query.get(neighbor_id)
            if neighbor:
                nodes[neighbor_id] = neighbor.to_dict()
        
        edges.append({
            'id': rel.id,
            'source': rel.company_id_1,
            'target': rel.company_id_2,
            'relationship_type': rel.relationship_type
        })
    
    return jsonify({
        'nodes': list(nodes.values()),
        'edges': edges
    }), 200

if __name__ == '__main__':
    app.run(debug=True, port=5001)