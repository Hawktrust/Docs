"""Ticket item 3: a rule creates a candidate Opportunity where an amendment
affects a defined geography.

Opportunities are geographic. There is no parcel-level or owner-level
resolution here — that is Gate 0 work — so a geography is (lga, geography_label)
and nothing finer.

That pair identifies the opportunity *this module raises*, not every opportunity.
0008 lets a geography carry one per principal on purpose: Crown working Tarneit
for its own book and for a client is the conflict conflict_disclosure exists to
record. A rule-raised opportunity has no principal yet, and 0027's partial unique
index keeps there being at most one of those per geography.
"""
from dataclasses import dataclass
from typing import Any

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
    """Return (stage, the human-readable reason it is at that stage).

    Takes one class per *amendment*, not per evidence record. Ingestion writes a
    new evidence record whenever an amendment's payload changes upstream, so a
    single amendment revised twice yields two records. Counting those as two
    amendments escalated an opportunity from DEVELOPING to HIGH_CONFIDENCE on
    the strength of one amendment being edited. Callers must deduplicate by
    source_reference first; refresh's per_amendment CTE does that, ordering by
    CLASS_STRENGTH so a revised amendment counts once, at its strongest class.
    """
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


# Strongest first: an amendment that has been gazetted is a FACT whatever an
# earlier revision of the same amendment was classified as.
CLASS_STRENGTH = {"FACT": 3, "HYPOTHESIS": 2, "INFERENCE": 1, "PREDICTION": 0, "UNKNOWN": 0}

# The same ordering, for the query that does the collapsing. Built from the dict
# above rather than written out, so the strengths are stated once: a second copy
# in SQL would be the kind of thing that drifts silently and restages
# opportunities nobody asked it to.
_STRENGTH_CASE = "CASE e.evidence_class::text " + " ".join(
    f"WHEN '{name}' THEN {rank}" for name, rank in CLASS_STRENGTH.items()
) + " ELSE 0 END"


@dataclass
class OpportunityChange:
    opportunity_id: str
    lga: str
    geography_label: str
    stage: str
    stage_rule: str
    created: bool
    evidence_ids: list
    origin: str = "REAL"


# The geography an amendment affects — the suburb it names, else the LGA, never
# finer than the evidence supports — is decided by the COALESCE in refresh's
# query. It was a Python function here as well; two statements of one rule is
# how a label starts meaning different things in different places.


def refresh(conn, owner_user_id, *, correlation_id=None, lga=None) -> list[OpportunityChange]:
    """Create or restage opportunities from the evidence currently in the graph.

    Re-running is safe: an opportunity is identified by (lga, geography_label),
    so a second run restages the existing row rather than creating a second one.
    """
    correlation_id = correlation_id or audit.new_correlation_id()

    # Group in the database, one row out per geography rather than one per
    # evidence record.
    #
    # This used to be SELECT ... FROM evidence_record with no WHERE and no LIMIT,
    # grouped in Python. At the size the graph is now that is harmless; at the
    # size it is meant to reach — every amendment in 79 planning schemes, plus a
    # fresh record each time one is revised — it reads the whole table into
    # memory on every refresh, and the read grows with history rather than with
    # the work. Postgres already knows how to group; this asks it to.
    #
    # per_amendment collapses an amendment's revisions to its strongest class
    # before anything is counted. That is not an optimisation: stage_for counts
    # HYPOTHESIS to decide DEVELOPING against HIGH_CONFIDENCE, so counting two
    # revisions of one amendment as two amendments escalated a geography on the
    # strength of an edit.
    sql = f"""
        WITH scoped AS (
            SELECT e.id, e.lga,
                   -- the suburb the amendment names, else the LGA; never finer
                   -- than the evidence supports
                   COALESCE(e.geography -> 'suburbs' ->> 0, e.lga) AS label,
                   e.evidence_class::text AS evidence_class,
                   e.source_reference, e.origin::text AS origin,
                   {_STRENGTH_CASE} AS strength
            FROM evidence_record e
            {{where}}
        ),
        per_amendment AS (
            SELECT lga, label, source_reference,
                   (array_agg(evidence_class ORDER BY strength DESC))[1] AS evidence_class
            FROM scoped
            GROUP BY lga, label, source_reference
        ),
        -- Rolled up in its own step and joined, never correlated against the
        -- geography. As a subquery per geography this re-scanned per_amendment
        -- once for every geography — quadratic, and measured 3x slower than the
        -- Python grouping it replaced at 60,000 records. Two hash aggregates and
        -- a hash join are linear in the table.
        classes AS (
            SELECT lga, label, array_agg(evidence_class) AS amendment_classes
            FROM per_amendment
            GROUP BY lga, label
        ),
        records AS (
            SELECT lga, label,
                   array_agg(id ORDER BY id) AS evidence_ids,
                   bool_or(origin = 'REAL')  AS any_real
            FROM scoped
            GROUP BY lga, label
        )
        SELECT r.lga, r.label, r.evidence_ids, r.any_real, c.amendment_classes
        FROM records r
        JOIN classes c ON c.lga = r.lga AND c.label = r.label
        -- C collation so the order matches Python's, which sorted these tuples
        ORDER BY r.lga COLLATE "C", r.label COLLATE "C"
    """
    params: tuple = ()
    if lga:
        sql = sql.replace("{where}", "WHERE e.lga = %s")
        params = (lga,)
    else:
        sql = sql.replace("{where}", "")
    rows = conn.execute(sql, params).fetchall()

    # Decide every geography's stage before touching the database. The rule stays
    # here in Python, where it is stated once and can be read; only the grouping
    # and the writing moved into SQL.
    wanted = []
    for row_lga, label, evidence_ids, any_real, amendment_classes in rows:
        stage, reason = stage_for(amendment_classes or [])
        # An opportunity is only as real as the evidence under it. Left to the
        # column default, an opportunity built entirely from demo records was
        # recorded as REAL and counted in figures shown to people.
        origin = "REAL" if any_real else "DEMO_SYNTHETIC"
        wanted.append((row_lga, label, stage, reason, origin, evidence_ids or []))

    if not wanted:
        return []

    # The write phase was four statements per geography — read the existing row,
    # insert or update it, write the audit event, link the evidence. Restaging
    # 31,600 geographies therefore cost 126,401 statements and about a hundred
    # seconds, nearly all of it round trips. It is now a fixed handful of
    # statements no matter how many geographies there are.
    #
    # Reading the existing rows in one query, rather than upserting blind, is
    # what keeps the audit honest: OPPORTUNITY_RESTAGED records the stage a
    # geography came from, and RETURNING on a conflicting insert reports the row
    # as it now is, not as it was.
    existing = {
        (row[0], row[1]): (row[2], row[3], row[4])
        for row in conn.execute(
            """SELECT o.lga, o.geography_label, o.id, o.stage::text, o.origin::text
                 FROM opportunity o
                 JOIN unnest(%s::text[], %s::text[]) AS t(lga, label)
                   ON t.lga = o.lga AND t.label = o.geography_label""",
            ([w[0] for w in wanted], [w[1] for w in wanted]),
        ).fetchall()
    }

    to_insert = [w for w in wanted if (w[0], w[1]) not in existing]
    # Only a changed stage or a changed origin is a restaging, exactly as before.
    # A stage_rule whose counts moved while the stage held is deliberately left
    # alone here; changing that is a behaviour change, not a speed one.
    to_update = [
        w for w in wanted
        if (w[0], w[1]) in existing
        and (existing[(w[0], w[1])][1] != w[2] or existing[(w[0], w[1])][2] != w[4])
    ]

    # uuid.UUID at runtime, not str — the dataclass field has always said str and
    # has always been handed a UUID. Typed Any here rather than corrected there,
    # because tightening that annotation is a change to every caller, not to this.
    ids: dict[tuple[str, str], Any] = {
        key: value[0] for key, value in existing.items()
    }

    if to_insert:
        inserted = conn.execute(
            """
            INSERT INTO opportunity (lga, geography_label, stage, stage_rule,
                                     owner_user_id, next_action, origin)
            SELECT t.lga, t.label, t.stage::opportunity_stage, t.rule, %s, %s,
                   t.origin::data_origin
              FROM unnest(%s::text[], %s::text[], %s::text[], %s::text[],
                          %s::text[]) AS t(lga, label, stage, rule, origin)
            RETURNING id, lga, geography_label
            """,
            (owner_user_id,
             "Review the evidence pack and confirm the geography is worth working",
             [w[0] for w in to_insert], [w[1] for w in to_insert],
             [w[2] for w in to_insert], [w[3] for w in to_insert],
             [w[4] for w in to_insert]),
        ).fetchall()
        for new_id, new_lga, new_label in inserted:
            ids[(new_lga, new_label)] = new_id

    if to_update:
        conn.execute(
            """
            UPDATE opportunity o
               SET stage = t.stage::opportunity_stage, stage_rule = t.rule,
                   origin = t.origin::data_origin, updated_at = now()
              FROM unnest(%s::text[], %s::text[], %s::text[], %s::text[],
                          %s::text[]) AS t(lga, label, stage, rule, origin)
             WHERE o.lga = t.lga AND o.geography_label = t.label
            """,
            ([w[0] for w in to_update], [w[1] for w in to_update],
             [w[2] for w in to_update], [w[3] for w in to_update],
             [w[4] for w in to_update]),
        )

    audit.write_many(conn, [
        {"correlation_id": correlation_id, "action": action,
         "object_table": "opportunity", "object_id": ids[(row_lga, label)],
         "previous_state": ({"stage": existing[(row_lga, label)][1]}
                            if (row_lga, label) in existing else None),
         "new_state": {"stage": stage, "stage_rule": reason},
         "actor_user_id": owner_user_id, "actor_agent": ACTOR_AGENT}
        for action, batch in (("OPPORTUNITY_CREATED", to_insert),
                              ("OPPORTUNITY_RESTAGED", to_update))
        for row_lga, label, stage, reason, _origin, _evidence in batch
    ])

    # Every geography's evidence in one statement. ON CONFLICT DO NOTHING is what
    # makes a rerun link nothing twice.
    pairs = [(str(ids[(w[0], w[1])]), str(e)) for w in wanted for e in w[5]]
    if pairs:
        conn.execute(
            """INSERT INTO opportunity_evidence (opportunity_id, evidence_id)
               SELECT o, e FROM unnest(%s::uuid[], %s::uuid[]) AS t(o, e)
               ON CONFLICT DO NOTHING""",
            ([p[0] for p in pairs], [p[1] for p in pairs]),
        )

    inserted_keys = {(w[0], w[1]) for w in to_insert}
    return [
        OpportunityChange(
            opportunity_id=ids[(row_lga, label)], lga=row_lga,
            geography_label=label, stage=stage, stage_rule=reason,
            created=(row_lga, label) in inserted_keys,
            evidence_ids=evidence_ids, origin=origin,
        )
        for row_lga, label, stage, reason, origin, evidence_ids in wanted
    ]
