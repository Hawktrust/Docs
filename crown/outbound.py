"""AC8: nothing may be exported, emailed or drafted for outreach without a
stored approval id.

The database enforces this with a NOT NULL foreign key. This module is the
server-side gate in front of it, and it checks more than the column can: that
the approval exists, and that it says APPROVED rather than REJECTED.
"""
from psycopg.types.json import Jsonb

from . import audit

ACTOR_AGENT = "crown.outbound"

ARTIFACT_TYPES = ("EXPORT", "OUTREACH_DRAFT", "BUYER_BRIEF")


class ApprovalRequired(Exception):
    """No usable approval id, so nothing leaves."""


def create(conn, approval_id, artifact_type: str, content: dict, created_by,
           *, correlation_id=None) -> str:
    if approval_id is None or str(approval_id).strip() == "":
        raise ApprovalRequired(
            f"a {artifact_type} needs a stored approval id; refusing to create one"
        )
    if artifact_type not in ARTIFACT_TYPES:
        raise ValueError(f"unknown artifact type {artifact_type}")

    row = conn.execute(
        "SELECT decision::text FROM approval WHERE id = %s", (approval_id,)
    ).fetchone()
    if row is None:
        raise ApprovalRequired(f"approval {approval_id} does not exist")
    if row[0] != "APPROVED":
        raise ApprovalRequired(
            f"approval {approval_id} is {row[0]}; a rejected match produces nothing"
        )

    correlation_id = correlation_id or audit.new_correlation_id()
    artifact_id = conn.execute(
        """INSERT INTO outbound_artifact (approval_id, artifact_type, content, created_by)
           VALUES (%s,%s,%s,%s) RETURNING id""",
        (approval_id, artifact_type, Jsonb(content), created_by),
    ).fetchone()[0]

    audit.write(conn, correlation_id, "OUTBOUND_CREATED", "outbound_artifact",
                artifact_id, new_state={"artifact_type": artifact_type},
                approval_id=approval_id, actor_user_id=created_by,
                actor_agent=ACTOR_AGENT)
    return artifact_id
