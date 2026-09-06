"""Ticket item 3: a rule creates a candidate Opportunity where an amendment
affects a defined geography.

Opportunities are geographic. There is no parcel-level or owner-level
resolution here — that is Gate 0 work — so an opportunity is identified by
(lga, geography_label) and nothing finer.
"""
from dataclasses import dataclass

from . import audit

ACTOR_AGENT = "crown.opportunity"

# ============================================================
# THE STAGE RULE
#
# Stated once, here, in terms a person can check against the evidence:
#
#   a gazetted amendment is settled upstream, so the change is real   -> CONFIRMED
#   two or more exhibited amendments point the same way               -> HIGH_CONFIDENCE
#   one exhibited amendment, still undecided                          -> DEVELOPING
#   evidence exists but is neither settled nor exhibited              -> WATCH
#
# The text returned alongside the stage is stored on the opportunity in
# stage_rule and rendered in the UI, so the reason a thing is at a stage travels
# with it instead of living in someone's head.
# ============================================================

RULE_DESCRIPTION = (
    "CONFIRMED when a gazetted amendment (FACT) affects the geography; "
    "HIGH_CONFIDENCE at two or more exhibited amendments (HYPOTHESIS); "
    "DEVELOPING at one; WATCH otherwise."
)


def stage_for(evidence_classes) -> tuple[str, str]:
    """Return (stage, the human-readable reason it is at that stage)."""
    classes = list(evidence_classes)
    facts = classes.count("FACT")
    hypotheses = classes.count("HYPOTHESIS")

    if facts:
        return "CONFIRMED", (
            f"{facts} gazetted amendment(s) classified FACT affect this geography"
        )
    if hypotheses >= 2:
        return "HIGH_CONFIDENCE", (
            f"{hypotheses} exhibited amendments classified HYPOTHESIS affect this "
            "geography, and none is yet gazetted"
        )
    if hypotheses == 1:
        return "DEVELOPING", (
            "one exhibited amendment classified HYPOTHESIS affects this geography"
        )
    return "WATCH", (
        "evidence affects this geography but none of it is classified FACT or HYPOTHESIS"
    )


@dataclass
class OpportunityChange:
    opportunity_id: str
    lga: str
    geography_label: str
    stage: str
    stage_rule: str
    created: bool
    evidence_ids: list


def geography_label_for(evidence_row) -> str:
    """The defined geography an amendment affects.

    Uses the suburb the amendment names when it names one, and falls back to the
    LGA. It never invents a finer geography than the evidence supports.
    """
    lga, geography = evidence_row
    if isinstance(geography, dict):
        suburbs = geography.get("suburbs") or []
        if suburbs:
            return str(suburbs[0])
    return lga


def refresh(conn, owner_user_id, *, correlation_id=None, lga=None) -> list[OpportunityChange]:
    """Create or restage opportunities from the evidence currently in the graph.

    Re-running is safe: an opportunity is identified by (lga, geography_label),
    so a second run restages the existing row rather than creating a second one.
    """
    correlation_id = correlation_id or audit.new_correlation_id()

    sql = """SELECT id, lga, geography, evidence_class::text
             FROM evidence_record"""
    params: tuple = ()
    if lga:
        sql += " WHERE lga = %s"
        params = (lga,)
    rows = conn.execute(sql, params).fetchall()

    # group the evidence by the geography it affects
    grouped: dict[tuple[str, str], list] = {}
    for evidence_id, row_lga, geography, evidence_class in rows:
        key = (row_lga, geography_label_for((row_lga, geography)))
        grouped.setdefault(key, []).append((evidence_id, evidence_class))

    changes = []
    for (row_lga, label), evidence in sorted(grouped.items()):
        stage, reason = stage_for(c for _, c in evidence)
        evidence_ids = [e for e, _ in evidence]

        existing = conn.execute(
            "SELECT id, stage::text FROM opportunity WHERE lga = %s AND geography_label = %s",
            (row_lga, label),
        ).fetchone()

        if existing is None:
            opportunity_id = conn.execute(
                """
                INSERT INTO opportunity (lga, geography_label, stage, stage_rule,
                                         owner_user_id, next_action)
                VALUES (%s,%s,%s,%s,%s,%s) RETURNING id
                """,
                (row_lga, label, stage, reason, owner_user_id,
                 "Review the evidence pack and confirm the geography is worth working"),
            ).fetchone()[0]
            created = True
            audit.write(conn, correlation_id, "OPPORTUNITY_CREATED", "opportunity",
                        opportunity_id, new_state={"stage": stage, "stage_rule": reason},
                        actor_user_id=owner_user_id, actor_agent=ACTOR_AGENT)
        else:
            opportunity_id, previous_stage = existing
            created = False
            if previous_stage != stage:
                conn.execute(
                    """UPDATE opportunity SET stage = %s, stage_rule = %s, updated_at = now()
                       WHERE id = %s""",
                    (stage, reason, opportunity_id),
                )
                audit.write(conn, correlation_id, "OPPORTUNITY_RESTAGED", "opportunity",
                            opportunity_id, previous_state={"stage": previous_stage},
                            new_state={"stage": stage, "stage_rule": reason},
                            actor_user_id=owner_user_id, actor_agent=ACTOR_AGENT)

        for evidence_id in evidence_ids:
            conn.execute(
                """INSERT INTO opportunity_evidence (opportunity_id, evidence_id)
                   VALUES (%s,%s) ON CONFLICT DO NOTHING""",
                (opportunity_id, evidence_id),
            )

        changes.append(OpportunityChange(
            opportunity_id=opportunity_id, lga=row_lga, geography_label=label,
            stage=stage, stage_rule=reason, created=created, evidence_ids=evidence_ids,
        ))

    return changes
