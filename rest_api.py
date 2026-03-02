from flask import Flask, jsonify, request
import psycopg2
import psycopg2.extras

app = Flask(__name__)

DB_HOST = "127.0.0.1"
DB_NAME = "postgres"
DB_USER = "postgres"
DB_PASS = "nexus123"

def get_db_connection():
    connection = psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )
    return connection

@app.route('/companies', methods=['GET'])
def getCompanies():
    try:
        requested_sector = request.args.get('sector')
        requested_size = request.args.get('size')
        conn = get_db_connection()
        curr = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        query_variables = {
            'filter_sector': requested_sector,
            'filter_size': requested_size
        }
        curr.execute("""
                     SELECT * FROM companies 
                     WHERE (%(filter_sector)s IS NULL OR sector=%(filter_sector)s) 
                     AND (%(filter_size)s IS NULL OR size_category=%(filter_size)s);
        """, query_variables)
        data = curr.fetchall()

        curr.close()
        conn.close()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/companies/<company_id>", methods=['GET'])
def getSingleCompany(company_id):
    try:
        conn = get_db_connection()
        curr = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        curr.execute("""
                     SELECT * FROM companies
                     WHERE (unique_id=%(company_id)s);
        """, {'company_id': company_id })
        data = curr.fetchall()

        curr.close()
        conn.close()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/companies/<company_id>/neighbors", methods=['GET'])
def getNeighbors(company_id):
    try:
        conn = get_db_connection()
        curr = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        requested_type = request.args.get('type')
        requested_size = request.args.get('size')

        curr.execute("""
                     SELECT r.company_1_ticker, r.company_2_ticker, r.type 
                     FROM companies c1
                     JOIN relationships r ON TRIM(UPPER(c1.ticker)) = TRIM(UPPER(r.company_1_ticker))
                     JOIN companies c2 ON TRIM(UPPER(c2.ticker)) = TRIM(UPPER(r.company_2_ticker))
                     WHERE (c1.unique_id = %(company_id)s)
                     AND (%(type)s IS NULL OR r.type = %(type)s)
                     AND (%(size)s IS NULL OR c2.size_category = %(size)s);
        """, { 'company_id': company_id, 'size': requested_size, 'type': requested_type })
        data = curr.fetchall()

        nodes = [row['company_2_ticker'] for row in data]
        edges = [ {"from": row['company_1_ticker'], "to": row['company_2_ticker'], "type": row['type']} for row in data]

        curr.close()
        conn.close()

        print(f"DEBUG: Looking for ID: {company_id}")
        print(f"DEBUG: Rows found: {len(data)}")
        print(f"DEBUG: Raw Data: {data}")
        return jsonify({
            "nodes": nodes,
            "edges": edges
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

app.run(debug=True)