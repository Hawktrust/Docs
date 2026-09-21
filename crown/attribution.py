"""Ticket item 7: when an approved match progresses, write an immutable
attribution record.

The record answers, for any row it covers: which signal created this? It stores
the originating evidence id together with that evidence's own source URL and
retrieval date, so the answer survives even if the evidence row is later
superseded.
"""
from . import audit

ACTOR_AGENT = "crown.attribution"


class NotApproved(Exception):
    """Attribution follows an approval. There is no other way to create one."""


def progress(conn, approval_id, *, correlation_id=None) -> str:
    """Write the attribution record for an approved match. Returns its id."""
    row = conn.execute(
        """
        SELECT a.decision::text, a.approver_id, m.opportunity_id, m.buyer_mandate_id
        FROM approval a JOIN match_result m ON m.id = a.match_result_id
        WHERE a.id = %s
        """,
        (approval_id,),
    ).fetchone()
    if row is None:
        raise NotApproved(f"no approval {approval_id}")

    decision, approver_id, opportunity_id, buyer_mandate_id = row
    if decision != "APPROVED":
        raise NotApproved(
            f"approval {approval_id} is {decision}; only an APPROVED match progresses"
        )

    # The originating signal: the earliest observed evidence linked to the
    # opportunity. Earliest, because that is the one that started the chain.
    origin = conn.execute(
        """
        SELECT e.id, e.source_url, e.retrieved_at
        FROM opportunity_evidence oe
        JOIN evidence_record e ON e.id = oe.evidence_id
        WHERE oe.opportunity_id = %s
        ORDER BY e.observed_at ASC, e.created_at ASC
        LIMIT 1
        """,
        (opportunity_id,),
    ).fetchone()
    if origin is None:
        raise NotApproved(
            f"opportunity {opportunity_id} has no linked evidence, so there is no "
            "signal to attribute it to"
        )

    evidence_id, source_url, retrieved_at = origin
    correlation_id = correlation_id or audit.new_correlation_id()

    attribution_id = conn.execute(
        """
        INSERT INTO attribution (opportunity_id, buyer_mandate_id, approval_id,
            originating_evidence_id, originating_source_url,
            originating_retrieved_at, approver_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id
        """,
        (opportunity_id, buyer_mandate_id, approval_id, evidence_id,
         source_url, retrieved_at, approver_id),
    ).fetchone()[0]

    audit.write(conn, correlation_id, "ATTRIBUTION_WRITTEN", "attribution",
                attribution_id,
                new_state={"originating_evidence_id": str(evidence_id),
                           "originating_source_url": source_url},
                evidence_id=evidence_id, approval_id=approval_id,
                actor_user_id=approver_id, actor_agent=ACTOR_AGENT)
    return attribution_id


def trace(conn, attribution_id):
    """AC11: for any attribution record, the originating signal, its source URL
    and its retrieval date."""
    return conn.execute(
        """
        SELECT at.id, o.lga, o.geography_label, b.buyer_label,
               e.source_reference, at.originating_source_url,
               at.originating_retrieved_at, e.evidence_class::text, ds.code
        FROM attribution at
        JOIN opportunity o      ON o.id = at.opportunity_id
        JOIN buyer_mandate b    ON b.id = at.buyer_mandate_id
        JOIN evidence_record e  ON e.id = at.originating_evidence_id
        JOIN data_source ds     ON ds.id = e.source_id
        WHERE at.id = %s
        """,
        (attribution_id,),
    ).fetchone()
