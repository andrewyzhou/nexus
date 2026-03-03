import os
from psycopg_pool import ConnectionPool

DATABASE_URL = os.getenv("DATABASE_URL") or "postgresql://postgres:postgres@localhost:5432/postgres"

pool = ConnectionPool(DATABASE_URL)
