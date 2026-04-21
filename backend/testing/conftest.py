import os
import sys
import pytest
import psycopg2

# Ensure we can import backend packages
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from main import app
from config import DATABASE_URL
from db.init import (
    CREATE_TABLE, 
    CREATE_RELATIONSHIPS_TABLE, 
    CREATE_TRACKS_TABLE, 
    CREATE_COMPANY_TRACKS_TABLE, 
    CREATE_INDEXES
)

@pytest.fixture(scope='session')
def test_client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

@pytest.fixture(scope='session')
def _db_schema():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cursor = conn.cursor()
    cursor.execute("DROP SCHEMA IF EXISTS test_schema CASCADE;")
    cursor.execute("CREATE SCHEMA test_schema;")
    # Force all connections in this DB to use test_schema
    cursor.execute("ALTER ROLE CURRENT_USER SET search_path TO test_schema;")
    conn.close()
    
    # Create tables inside the new schema
    conn2 = psycopg2.connect(DATABASE_URL)
    cursor2 = conn2.cursor()
    cursor2.execute(CREATE_TABLE)
    cursor2.execute(CREATE_RELATIONSHIPS_TABLE)
    cursor2.execute(CREATE_TRACKS_TABLE)
    cursor2.execute(CREATE_COMPANY_TRACKS_TABLE)
    for idx_sql in CREATE_INDEXES:
        cursor2.execute(idx_sql)
    conn2.commit()
    conn2.close()

    yield # Tests run here
    
    # Clean up schema and reset search path back to public
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cursor = conn.cursor()
    cursor.execute("ALTER ROLE CURRENT_USER SET search_path TO public;")
    cursor.execute("DROP SCHEMA IF EXISTS test_schema CASCADE;")
    conn.close()

@pytest.fixture(scope='function')
def db(_db_schema):
    """
    Function-level DB fixture.
    Yields a database connection and clears tables after the test runs
    so data from one test does not pollute another.
    """
    conn = psycopg2.connect(DATABASE_URL)
    yield conn
    
    # Truncate tables to reset DB state for the next test
    try:
        conn.autocommit = True
        cursor = conn.cursor()
        cursor.execute("TRUNCATE TABLE company_tracks, relationships, companies, investment_tracks RESTART IDENTITY CASCADE;")
    except Exception as e:
        print(f"Error truncating tables: {e}")
    finally:
        conn.close()
