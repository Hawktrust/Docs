"""Decisions about an opportunity, and the confidence that is not a free field.

Two rules this module exists to hold.

A recommendation is a consequential output. Constitution §4 says nothing
consequential leaves without a stored approval id, and an Acquire reaching a
client or an investment committee is as consequential as an export. So it takes
an approval id and the schema requires one.

Confidence is derived, never typed. The system already classifies every piece of
evidence by class, reliability and how it was retrieved. A second, separately
maintained confidence score drifts from those within weeks and then contradicts
them in front of a client.
"""
from dataclasses import dataclass
from datetime import datetime

from psycopg.types.json import Jsonb

from . import audit

ACTOR_AGENT = "crown.recommendation"

DECISIONS = ("ACQUIRE", "NEGOTIATE", "OPTION", "JOINT_VENTURE", "WATCH", "AVOID")
TIMINGS = ("IMMEDIATE", "ONE_TO_THREE_YEARS", "THREE_TO_SEVEN_YEARS", "LONG_TERM")

# The derivation, stated once, in terms anyone can check against the evidence:
#
#   CONFIRMED    at least one FACT the system retrieved itself
#   PROBABLE     a FACT a named human captured, or a HYPOTHESIS directly retrieved
#   SPECULATIVE  anything else, including anything that came through a relay
#
# Note what cannot happen: a recommendation resting only on search-relay leads
# cannot be CONFIRMED, because migration 0003 already forbids relayed evidence
# from being a FACT at all.
CONFIDENCE_RULE = (
    "CONFIRMED when the opportunity rests on a directly retrieved FACT; "
    "PROBABLE on an operator-captured FACT or a directly retrieved HYPOTHESIS; "
    "SPECULATIVE otherwise."
)


class NotApproved(Exception):
    """A recommendation follows an approval. There is no other way to make one."""


@dataclass
class EvidenceLine:
    evidence_id: str
    source_reference: str
    evidence_class: str
    reliability: str
    retrieval_method: str
    source_url: str
    retrieved_at: datetime
    observed_at: datetime


def evidence_for(conn, opportunity_id) -> list[EvidenceLine]:
    rows = conn.execute(
        """SELECT e.id, e.source_reference, e.evidence_class::text,
                  e.reliability::text, e.retrieval_method, e.source_url,
                  e.retrieved_at, e.observed_at
           FROM opportunity_evidence oe JOIN evidence_record e ON e.id = oe.evidence_id
           WHERE oe.opportunity_id = %s
           ORDER BY e.observed_at DESC""",
        (opportunity_id,),
    ).fetchall()
    return [EvidenceLine(*row) for row in rows]


def confidence_from(evidence: list[EvidenceLine]) -> str:
    """Derive the confidence. See CONFIDENCE_RULE."""
    for line in evidence:
        if line.evidence_class == "FACT" and line.retrieval_method == "DIRECT_FETCH":
            return "CONFIRMED"
    for line in evidence:
        if (line.evidence_class == "FACT" and line.retrieval_method == "OPERATOR_CAPTURE") \
                or (line.evidence_class == "HYPOTHESIS"
                    and line.retrieval_method == "DIRECT_FETCH"):
            return "PROBABLE"
    return "SPECULATIVE"


def snapshot(evidence: list[EvidenceLine]) -> dict:
    """What the recommendation rested on, as it was, when it was made."""
    return {
        "taken_at_evidence_count": len(evidence),
        "confidence_rule": CONFIDENCE_RULE,
        "evidence": [
            {
                "evidence_id": str(line.evidence_id),
                "reference": line.source_reference,
                "class": line.evidence_class,
                "reliability": line.reliability,
                "retrieval_method": line.retrieval_method,
                "source_url": line.source_url,
                "retrieved_at": line.retrieved_at.isoformat(),
                "observed_at": line.observed_at.isoformat(),
            }
            for line in evidence
        ],
    }


def create(conn, *, approval_id, decision: str, strategy: str, timing: str,
           rationale: str, created_by, economics: dict | None = None,
           economics_assumptions: dict | None = None,
           correlation_id=None) -> str:
    """Record a recommendation against an approved match. Caller commits."""
    if decision not in DECISIONS:
        raise ValueError(f"unknown decision {decision}")
    if timing not in TIMINGS:
        raise ValueError(f"unknown timing {timing}")
    if not rationale or not rationale.strip():
        raise ValueError("a recommendation states its reasoning")
    if economics is not None and not economics_assumptions:
        # The database enforces this too. A residual land value moves enormously
        # on a small change to a sales rate; printed beside provenanced planning
        # evidence it borrows a credibility it has not earned.
        raise ValueError(
            "economics must ship with the assumptions that produced them")

    row = conn.execute(
        """SELECT a.decision::text, m.opportunity_id, o.principal::text,
                  o.principal_label
           FROM approval a
           JOIN match_result m ON m.id = a.match_result_id
           JOIN opportunity o  ON o.id = m.opportunity_id
           WHERE a.id = %s""",
        (approval_id,),
    ).fetchone()
    if row is None:
        raise NotApproved(f"no approval {approval_id}")
    approval_decision, opportunity_id, principal, principal_label = row
    if approval_decision != "APPROVED":
        raise NotApproved(
            f"approval {approval_id} is {approval_decision}; only an approved "
            "match produces a recommendation")
    if not principal:
        raise NotApproved(
            f"opportunity {opportunity_id} has no principal. A recommendation is "
            "made for somebody — Crown's own book, a client or a developer — and "
            "which one it is has to be recorded before it is made.")

    evidence = evidence_for(conn, opportunity_id)
    confidence = confidence_from(evidence)
    correlation_id = correlation_id or audit.new_correlation_id()

    recommendation_id = conn.execute(
        """INSERT INTO recommendation (opportunity_id, approval_id, principal,
                   principal_label, decision, strategy, timing, confidence,
                   rationale, economics, economics_assumptions, evidence_snapshot,
                   created_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (opportunity_id, approval_id, principal, principal_label, decision,
         strategy, timing, confidence, rationale.strip(),
         Jsonb(economics) if economics else None,
         Jsonb(economics_assumptions) if economics_assumptions else None,
         Jsonb(snapshot(evidence)), created_by),
    ).fetchone()[0]

    audit.write(conn, correlation_id, f"RECOMMENDATION_{decision}", "recommendation",
                recommendation_id,
                new_state={"decision": decision, "confidence": confidence,
                           "principal": principal, "timing": timing},
                approval_id=approval_id, actor_user_id=created_by,
                actor_agent=ACTOR_AGENT)
    return recommendation_id
