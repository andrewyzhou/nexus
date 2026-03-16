import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://nexus:nexus@localhost:5433/corporate_data"
)
