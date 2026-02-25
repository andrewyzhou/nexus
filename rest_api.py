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
        WHERE (%(filter_size)s IS NULL OR size_category=%(filter_size)s);
        """, query_variables)
        data = curr.fetchall()

        curr.close()
        conn.close()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/companies/<company_id>", methods=['GET'])
def getSingleCompany(id):
    try:
        conn = get_db_connection()
        curr = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        curr.execute("""
        SELECT * FROM companies
        WHERE (unique_id=%(id)s);
        """)
        data = curr.fetchall()

        curr.close()
        conn.close()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/companies/<company_id>/neighbors", methods=['GET'])
def getNeighbors(id):
    try:
        conn = get_db_connection()
        curr = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        requested_type = request.args.get('type')
        requested_size = request.args.get('size')

        curr.execute("""
        SELECT r.company_2_ticker,
        FROM companies c JOIN relationships r
        ON c.ticker = r.company_1_ticker
        WHERE c.id = %(id)s
        WHERE LEN(r.company_2_ticker) >= $(requested_size)s;
        """)
        nodes_data = curr.fetchall()

        curr.execute("""
        SELECT r.type,
        FROM companies c JOIN relationships r
        ON c.ticker = r.company_1_ticker
        WHERE c.id = %(id)s
        WHERE r.type = $(requested_type)s;
        """)
        edges_data = curr.fetchall()

        curr.close()
        conn.close()
        return jsonify({
            "nodes": nodes_data,
            "edges": edges_data
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

app.run(debug=True)