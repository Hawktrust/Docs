"""Database access for the ingestion pipeline.

The pipeline connects as an ordinary application role. It never assumes
superuser and never bypasses row-level security.
"""
import os

import psycopg

DEFAULT_DSN = os.environ.get("CROWN_DSN", "postgresql:///crown_ai")


def connect(dsn: str | None = None) -> psycopg.Connection:
    return psycopg.connect(dsn or DEFAULT_DSN, autocommit=False)
