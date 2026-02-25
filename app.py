from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Integer, String, Float, Text, ForeignKey

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:password@127.0.0.1:5432/postgres'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class Companies(db.Model):
    id = db.Column(Integer, primary_key=True, autoincrement=True)
    name = db.Column(String(200), nullable=False, unique=True)
    industries = db.Column(Text)   
    currency = db.Column(String(3), nullable=False)  
    current_price = db.Column(Float)
   
    def __repr__(self):
        return f'<Company {self.name}>'

class Relationships(db.Model):
    id = db.Column(Integer, primary_key=True, autoincrement=True)
    company_id_1 = db.Column(Integer, ForeignKey('companies.id'), nullable=False)
    company_id_2 = db.Column(Integer, ForeignKey('companies.id'), nullable=False)
    relationship_type = db.Column(String(100), nullable=False)  
  
    # relationships to access the companies idk 
    # company_1 = db.relationship('Companies', foreign_keys=[company_id_1])
    # company_2 = db.relationship('Companies', foreign_keys=[company_id_2])
    
    def __repr__(self):
        return f'<Relationship {self.relationship_type} between {self.company_id_1} and {self.company_id_2}>'

@app.route('/companies', methods=['GET'])
def get_companies():
    companies = Companies.query.all()
    return jsonify(companies), 200