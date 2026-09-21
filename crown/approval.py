"""Ticket item 6: the approval queue.

A named human opens a match, sees the evidence pack behind it, and approves or
rejects with a reason. Nothing consequential leaves the system without the
approval id that produces.
"""
from . import audit

ACTOR_AGENT = "crown.approval"


class NotAuthorised(Exception):
    """The acting user's role may not decide approvals."""


DECIDING_ROLES = ("ADMIN", "COMPLIANCE")


def queue(conn, limit: int = 50):
    """Matches waiting on a decision: scored, not excluded, not yet decided."""
    return conn.execute(
        """
        SELECT m.id, m.opportunity_id, m.total_score, b.buyer_label, b.origin::text,
               o.lga, o.geography_label, o.stage::text, o.stage_rule
        FROM match_result m
        JOIN buyer_mandate b ON b.id = m.buyer_mandate_id
        JOIN opportunity o   ON o.id = m.opportunity_id
        WHERE NOT m.is_excluded
          AND NOT EXISTS (SELECT 1 FROM approval a WHERE a.match_result_id = m.id)
        ORDER BY m.total_score DESC
        LIMIT %s
        """,
        (limit,),
    ).fetchall()


def evidence_pack(conn, match_result_id):
    """Everything the approver needs to see before deciding.

    The pack is the evidence actually linked to the opportunity, with its
    provenance intact — not a summary of it.
    """
    return conn.execute(
        """
        SELECT e.id, e.source_reference, e.title, e.evidence_class::text,
               e.reliability::text, e.source_url, e.retrieved_at, e.observed_at,
               e.amendment_status, e.lga
        FROM match_result m
        JOIN opportunity_evidence oe ON oe.opportunity_id = m.opportunity_id
        JOIN evidence_record e       ON e.id = oe.evidence_id
        WHERE m.id = %s
        ORDER BY e.observed_at DESC
        """,
        (match_result_id,),
    ).fetchall()


def decide(conn, match_result_id, decision: str, reason: str, approver_id,
           approver_role: str, *, correlation_id=None) -> str:
    """Record a decision. Returns the approval id.

    The role check here is a courtesy that produces a clear error. The actual
    enforcement is the RLS policy on approval, which the database applies
    whatever this function believes.
    """
    if approver_role not in DECIDING_ROLES:
        raise NotAuthorised(
            f"role {approver_role or '<none>'} may not decide approvals; "
            f"one of {DECIDING_ROLES} is required"
        )
    if not reason or not reason.strip():
        raise ValueError("a decision needs a reason")

    correlation_id = correlation_id or audit.new_correlation_id()
    approval_id = conn.execute(
        """INSERT INTO approval (match_result_id, decision, reason, approver_id)
           VALUES (%s,%s,%s,%s) RETURNING id""",
        (match_result_id, decision, reason.strip(), approver_id),
    ).fetchone()[0]

    audit.write(conn, correlation_id, f"MATCH_{decision}", "approval", approval_id,
                new_state={"match_result_id": str(match_result_id),
                           "decision": decision, "reason": reason.strip()},
                approval_id=approval_id, actor_user_id=approver_id,
                actor_agent=ACTOR_AGENT)
    return approval_id
