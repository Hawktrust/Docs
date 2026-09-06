"""What the numbers actually are.

Two rules govern everything here.

Any figure shown to a person counts real records only. The twenty synthetic
mandates and any demo evidence are reported separately and labelled, never
folded into a total — a count that quietly includes demo data is worse than no
count, because it looks like knowledge.

Zero is a real answer. Where the honest number is nothing, these report nothing
rather than hiding the row.
"""
from dataclasses import dataclass


@dataclass
class Overview:
    real_evidence: int
    demo_evidence: int
    real_mandates: int
    synthetic_mandates: int
    opportunities: int
    demo_opportunities: int
    leads_awaiting_verification: int
    matches_awaiting_decision: int
    demo_matches_awaiting_decision: int
    approvals: int
    attributions: int
    outbound_artifacts: int
    data_rights_exceptions: int

    @property
    def has_real_evidence(self) -> bool:
        return self.real_evidence > 0


def overview(conn) -> Overview:
    def count(sql, params=()):
        return conn.execute(sql, params).fetchone()[0]

    return Overview(
        real_evidence=count(
            "SELECT count(*) FROM evidence_record WHERE origin = 'REAL'"),
        demo_evidence=count(
            "SELECT count(*) FROM evidence_record WHERE origin = 'DEMO_SYNTHETIC'"),
        real_mandates=count("SELECT count(*) FROM buyer_mandate_real"),
        synthetic_mandates=count(
            "SELECT count(*) FROM buyer_mandate WHERE origin = 'DEMO_SYNTHETIC'"),
        opportunities=count("SELECT count(*) FROM opportunity WHERE origin = 'REAL'"),
        demo_opportunities=count(
            "SELECT count(*) FROM opportunity WHERE origin = 'DEMO_SYNTHETIC'"),
        leads_awaiting_verification=count(
            """SELECT count(*) FROM evidence_review_queue
               WHERE resolved_at IS NULL"""),
        # a match is real only if both sides of it are
        matches_awaiting_decision=count(
            """SELECT count(*) FROM match_result m
               JOIN opportunity o   ON o.id = m.opportunity_id
               JOIN buyer_mandate b ON b.id = m.buyer_mandate_id
               WHERE NOT m.is_excluded
                 AND o.origin = 'REAL' AND b.origin = 'REAL'
                 AND NOT EXISTS (SELECT 1 FROM approval a WHERE a.match_result_id = m.id)"""),
        demo_matches_awaiting_decision=count(
            """SELECT count(*) FROM match_result m
               JOIN opportunity o   ON o.id = m.opportunity_id
               JOIN buyer_mandate b ON b.id = m.buyer_mandate_id
               WHERE NOT m.is_excluded
                 AND (o.origin <> 'REAL' OR b.origin <> 'REAL')
                 AND NOT EXISTS (SELECT 1 FROM approval a WHERE a.match_result_id = m.id)"""),
        approvals=count("SELECT count(*) FROM approval"),
        attributions=count("SELECT count(*) FROM attribution"),
        outbound_artifacts=count("SELECT count(*) FROM outbound_artifact"),
        data_rights_exceptions=count("SELECT count(*) FROM data_rights_exception"),
    )


def data_rights_exceptions(conn):
    """Sources being ingested without a complete register entry.

    This should be empty before go-live. It is not.
    """
    return conn.execute(
        """SELECT code, display_name, provider, lane::text, exception_reason, notes
           FROM data_rights_exception ORDER BY code"""
    ).fetchall()


def unresolved_review_queue(conn):
    """Everything waiting on a human, oldest first, with nobody assigned to it."""
    return conn.execute(
        """SELECT q.id,
                  q.attempted_payload ->> 'amendment_number',
                  q.attempted_payload ->> 'lga',
                  q.attempted_payload ->> 'corroboration',
                  q.failure_reason,
                  q.missing_fields,
                  q.created_at
           FROM evidence_review_queue q
           WHERE q.resolved_at IS NULL
           ORDER BY q.created_at"""
    ).fetchall()


def audit_trail(conn, limit: int = 100, correlation_id=None):
    """The append-only record, most recent first.

    An audit table nobody can read is a table nobody checks.
    """
    sql = """SELECT a.occurred_at, a.action, a.object_table, a.object_id,
                    coalesce(u.display_name, a.actor_agent, 'unattributed'),
                    a.correlation_id, a.new_state
             FROM audit_event a LEFT JOIN app_user u ON u.id = a.actor_user_id"""
    params: tuple = ()
    if correlation_id:
        sql += " WHERE a.correlation_id = %s"
        params = (correlation_id,)
    return conn.execute(sql + " ORDER BY a.id DESC LIMIT %s", params + (limit,)).fetchall()


def scoring_weight_history(conn):
    """Every change to the numbers that decide which buyer ranks first."""
    return conn.execute(
        """SELECT a.occurred_at, a.action,
                  coalesce(u.display_name, a.actor_agent, 'unattributed'),
                  a.previous_state, a.new_state
           FROM audit_event a LEFT JOIN app_user u ON u.id = a.actor_user_id
           WHERE a.object_table = 'match_weight_config'
           ORDER BY a.id DESC"""
    ).fetchall()
