"""Constitution §5: every state transition writes one row.

There is a single writer so that the shape of an audit row is decided once.
audit_event is append-only — the trigger from migration 0001 refuses UPDATE,
DELETE and TRUNCATE, and migration 0002 additionally revokes those privileges
from the application role.
"""
import uuid

from psycopg.types.json import Jsonb


def new_correlation_id() -> str:
    """One id per operation, so every row a single action produced can be found."""
    return str(uuid.uuid4())


_INSERT = """
        INSERT INTO audit_event (actor_user_id, actor_agent, action, object_table,
                                 object_id, previous_state, new_state, evidence_id,
                                 approval_id, correlation_id, model, provider)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """


def _row(correlation_id, action, object_table, object_id, previous_state,
         new_state, evidence_id, approval_id, actor_user_id, actor_agent,
         model, provider) -> tuple:
    """The shape of an audit row, decided in one place for both writers."""
    return (actor_user_id, actor_agent, action, object_table, str(object_id),
            Jsonb(previous_state) if previous_state is not None else None,
            Jsonb(new_state) if new_state is not None else None,
            evidence_id, approval_id, correlation_id, model, provider)


def write(conn, correlation_id, action, object_table, object_id, *,
          previous_state=None, new_state=None, evidence_id=None,
          approval_id=None, actor_user_id=None, actor_agent=None,
          model=None, provider=None) -> None:
    conn.execute(_INSERT, _row(correlation_id, action, object_table, object_id,
                               previous_state, new_state, evidence_id, approval_id,
                               actor_user_id, actor_agent, model, provider))


def write_many(conn, events) -> None:
    """Write a batch of audit rows in one round trip.

    Every state transition still writes its own row — Constitution §5 is about
    what is recorded, not how many times the process waits for the server. A
    statewide refresh restages tens of thousands of opportunities, and one
    execute each made the audit trail the slowest part of writing it.

    Each event is the keyword set `write` takes, minus the connection.
    """
    rows = [
        _row(e["correlation_id"], e["action"], e["object_table"], e["object_id"],
             e.get("previous_state"), e.get("new_state"), e.get("evidence_id"),
             e.get("approval_id"), e.get("actor_user_id"), e.get("actor_agent"),
             e.get("model"), e.get("provider"))
        for e in events
    ]
    if rows:
        with conn.cursor() as cur:
            cur.executemany(_INSERT, rows)
