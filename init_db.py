import random
from faker import Faker
from app import app, db, Companies, Relationships

fake = Faker()

SECTORS = [
    'Technology',
    'Finance',
    'Healthcare',
    'Energy',
    'Consumer Goods',
    'Industrials',
    'Utilities',
    'Materials'
]

RELATIONSHIP_TYPES = ['supplier', 'competitor', 'partner', 'subsidiary']

def init_database():
    with app.app_context():
        db.drop_all()
        db.create_all()
        
        companies = []
        for i in range(500):
            company = Companies(
                name=fake.unique.company(),
                industries=random.choice(SECTORS),
                currency='USD',
                current_price=round(random.uniform(10, 2000), 2),
                market_cap=round(random.uniform(5_000_000_000, 3_000_000_000_000), 2)
            )
            companies.append(company)
        
        db.session.bulk_save_objects(companies)
        db.session.commit()
        
        all_company_ids = [c.id for c in Companies.query.all()]
        
        num_relationships = random.randint(1000, 2000)
        relationships = []
        used_pairs = set()
        
        for _ in range(num_relationships):
            company_id_1, company_id_2 = random.sample(all_company_ids, 2)
            
            pair = tuple(sorted([company_id_1, company_id_2]))
            
            if pair in used_pairs:
                continue
            
            used_pairs.add(pair)
            
            relationship = Relationships(
                company_id_1=pair[0],
                company_id_2=pair[1],
                relationship_type=random.choice(RELATIONSHIP_TYPES)
            )
            relationships.append(relationship)
        
        db.session.bulk_save_objects(relationships)
        db.session.commit()

if __name__ == '__main__':
    init_database()
