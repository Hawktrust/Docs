"""Connections, and the one place the authenticated identity reaches the database.

Row-level security decides what a connection can see by reading two session
variables. They are set here, from values the server established after
authentication, and from nowhere else. No request header is ever a source for
them.
"""
import os

import psycopg

DEFAULT_DSN = os.environ.get("CROWN_DSN", "postgresql:///crown_ai")


def connect(dsn: str | None = None) -> psycopg.Connection:
    return psycopg.connect(dsn or DEFAULT_DSN, autocommit=False)


def set_identity(conn: psycopg.Connection, user_id: str | None, role: str | None) -> None:
    """Bind the connection to an authenticated identity for this transaction.

    Both values are scoped to the transaction (set_config's third argument), so
    they cannot leak into the next request that borrows this connection.
    """
    conn.execute("SELECT set_config('crown.user_id', %s, true)", (str(user_id or ""),))
    conn.execute("SELECT set_config('crown.user_role', %s, true)", (str(role or ""),))


def clear_identity(conn: psycopg.Connection) -> None:
    set_identity(conn, "", "")
