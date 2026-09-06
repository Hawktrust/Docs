"""Each test module gets a database built by the real migration.

The fixtures below are test data and live only in the throwaway test database.
They are never written to a database that a person reads a figure from.
"""
import os
import subprocess
import uuid
from datetime import datetime, timezone

import psycopg
import pytest

MIGRATION = os.path.join(os.path.dirname(__file__), "..", "migrations",
                         "0001_ticket01_thin_loop.sql")
ADMIN_DSN = os.environ.get("CROWN_ADMIN_DSN", "postgresql://postgres@127.0.0.1:5432/postgres")


@pytest.fixture()
def db():
    name = f"crown_test_{uuid.uuid4().hex[:10]}"
    admin = psycopg.connect(ADMIN_DSN, autocommit=True)
    admin.execute(f'CREATE DATABASE "{name}"')
    dsn = ADMIN_DSN.rsplit("/", 1)[0] + "/" + name
    subprocess.run(["psql", "-q", "-v", "ON_ERROR_STOP=1", "-d", dsn, "-f", MIGRATION],
                   check=True, capture_output=True)
    conn = psycopg.connect(dsn, autocommit=False)
    try:
        yield conn
    finally:
        conn.close()
        admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.close()


class FakeRetrieval:
    """Stands in for a real fetch. Carries the same provenance a real one would."""
    def __init__(self, url="https://www.planning.vic.gov.au/guides-and-resources/amendments"):
        self.url = url
        self.retrieved_at = datetime.now(timezone.utc)
        self.status_code = 200
        self.body = ""
        self.content_type = "application/json"


@pytest.fixture()
def retrieval():
    return FakeRetrieval()
