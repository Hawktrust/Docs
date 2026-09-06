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


def build_content(conn, approval_id, *, note: str = "") -> dict:
    """Assemble what actually goes out.

    An outreach draft that says only "note: hi" is gated but useless. What
    leaves carries the chain that justifies it: the geography and the rule that
    staged it, the evidence with its provenance, the buyer, the score with every
    factor, and the approval. Anyone receiving it can check the reasoning, and
    anyone auditing it can retrace the decision from the artifact alone.

    Returns an empty envelope when there is no approval to build from; create()
    refuses it a moment later.
    """
    if approval_id is None or str(approval_id).strip() == "":
        return {"note": note}

    header = conn.execute(
        """SELECT o.lga, o.geography_label, o.stage::text, o.stage_rule,
                  b.buyer_label, b.origin::text, m.total_score,
                  m.geographic_fit_score, m.asset_fit_score, m.price_fit_score,
                  m.size_fit_score, m.freshness_score, m.weight_config_version,
                  a.decision::text, a.reason, u.display_name, a.decided_at
           FROM approval a
           JOIN match_result m  ON m.id = a.match_result_id
           JOIN opportunity o   ON o.id = m.opportunity_id
           JOIN buyer_mandate b ON b.id = m.buyer_mandate_id
           JOIN app_user u      ON u.id = a.approver_id
           WHERE a.id = %s""",
        (approval_id,),
    ).fetchone()
    if header is None:
        return {"note": note}

    evidence = conn.execute(
        """SELECT e.source_reference, e.title, e.evidence_class::text,
                  e.reliability::text, e.retrieval_method, e.source_url,
                  e.retrieved_at, e.observed_at, e.origin::text
           FROM approval a
           JOIN match_result m          ON m.id = a.match_result_id
           JOIN opportunity_evidence oe ON oe.opportunity_id = m.opportunity_id
           JOIN evidence_record e       ON e.id = oe.evidence_id
           WHERE a.id = %s
           ORDER BY e.observed_at DESC""",
        (approval_id,),
    ).fetchall()

    return {
        "note": note,
        "approval": {
            "id": str(approval_id),
            "decision": header[13],
            "reason": header[14],
            "approved_by": header[15],
            "decided_at": header[16].isoformat(),
        },
        "opportunity": {
            "lga": header[0],
            "geography": header[1],
            "stage": header[2],
            "stage_rule": header[3],
        },
        "buyer": {"label": header[4], "origin": header[5]},
        "score": {
            "total": float(header[6]),
            "weight_config_version": header[12],
            "contributions": {
                "geographic_fit": float(header[7]),
                "asset_fit": float(header[8]),
                "price_fit": float(header[9]),
                "size_fit": float(header[10]),
                "mandate_freshness": float(header[11]),
            },
        },
        "evidence": [
            {
                "reference": row[0], "title": row[1], "class": row[2],
                "reliability": row[3], "retrieval_method": row[4],
                "source_url": row[5],
                "retrieved_at": row[6].isoformat(),
                "observed_at": row[7].isoformat(),
                "origin": row[8],
            }
            for row in evidence
        ],
    }


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
