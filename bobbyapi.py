from flask import Flask, jsonify
import psycopg2

app = Flask(__name__)

def db_connection():
    return psycopg2.connect(
        host="localhost",
        port=5433,
        database="mydb",
        user="admin",
        password="secret"
    ) 

@app.route("/")
def index():
    return 'main'


@app.route("/companies", methods = ["GET"])
def companies():
    conn = db_connection()

    curr = conn.cursor()

    curr.execute("SELECT * FROM companies;")
    rows = curr.fetchall()

    curr.close()
    conn.close()

    return jsonify(rows)


@app.route("/companies/<int:company_id>", methods=["GET"])
def companies_data(company_id):

    conn = db_connection()

    curr = conn.cursor()

    curr.execute("SELECT * FROM companies WHERE company_id = %s;", (company_id,))
    row = curr.fetchone()

    curr.close()
    conn.close()

    if row:
        return jsonify(row)
    else:
        return "ERROR"
    

@app.route("/companies/<int:company_id>/neighbors", methods=["GET"])
def companies_graph(company_id):

    conn = db_connection()

    curr = conn.cursor()

    curr.execute("SELECT * FROM companies WHERE company_id = %s;", (company_id,))
    company = curr.fetchone()

    if not company:
        curr.close()
        conn.close()
        return "ERROR" 
    
    curr.execute("SELECT related_company, relationship_type FROM relationships WHERE company_id = %s;", (company_id,))

    rows = curr.fetchall()

    curr.close()
    conn.close()

    nodes = [{"id": company_id, "label": company[1]}]
    edges = []

    for r in rows:
        nodes.append({"id": r[0], "label": r[0]})
        edges.append({"source": company_id, "target": r[0], "type": r[1]})


    return {"nodes": nodes, "edges": edges}



if __name__ == "__main__":
    app.run(debug=True)