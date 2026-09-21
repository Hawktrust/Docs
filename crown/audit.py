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


def write(conn, correlation_id, action, object_table, object_id, *,
          previous_state=None, new_state=None, evidence_id=None,
          approval_id=None, actor_user_id=None, actor_agent=None,
          model=None, provider=None) -> None:
    conn.execute(
        """
        INSERT INTO audit_event (actor_user_id, actor_agent, action, object_table,
                                 object_id, previous_state, new_state, evidence_id,
                                 approval_id, correlation_id, model, provider)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (actor_user_id, actor_agent, action, object_table, str(object_id),
         Jsonb(previous_state) if previous_state is not None else None,
         Jsonb(new_state) if new_state is not None else None,
         evidence_id, approval_id, correlation_id, model, provider),
    )
