"""Amendment leads discovered through a search relay.

A lead is not evidence. It is a real amendment identifier and its canonical URL,
learned from an intermediary that summarised a page we could not fetch. The
identifier and the URL are structural and check out across independent searches;
the detail does not. Two searches for C232melt disagreed on its gazettal date,
and two for C272hume described different amendments.

So leads go to evidence_review_queue — the place the schema already provides for
records that cannot fill their mandatory provenance — and never into the graph.
A lead becomes evidence when someone fetches its canonical URL directly. See
ingest/verify.py.
"""
import json
from dataclasses import dataclass, field

from psycopg.types.json import Jsonb

from crown import audit

ACTOR_AGENT = "ingest.leads"

FAILURE_REASON = (
    "discovered via search relay; the canonical URL was never fetched, so "
    "provenance cannot be completed and the record may not enter the graph"
)


@dataclass
class Lead:
    lga: str
    amendment_number: str
    canonical_url: str
    relay_claims: dict = field(default_factory=dict)
    corroboration: str = "SINGLE_SOURCE"
    notes: str = ""

    @property
    def unfillable_fields(self) -> list[str]:
        """Mandatory provenance fields the relay could not establish.

        The identifier, the LGA and the canonical URL are reliable — they come
        from the shape of the search results rather than from a summary of them.
        Everything describing the amendment does not.
        """
        missing = ["observed_at", "title"]
        if self.corroboration == "CONTRADICTED":
            missing.append("amendment_status")
        return missing


def load(path: str) -> list[Lead]:
    with open(path) as fh:
        payload = json.load(fh)
    return [Lead(**item) for item in payload["leads"]]


def record(conn, source, leads: list[Lead], *, correlation_id=None) -> list[str]:
    """Put each lead in the review queue. Returns the queue ids created.

    Re-running does not duplicate: a lead already queued and unresolved for the
    same amendment is left alone.
    """
    correlation_id = correlation_id or audit.new_correlation_id()
    created = []

    for lead in leads:
        already = conn.execute(
            """SELECT id FROM evidence_review_queue
               WHERE source_id = %s
                 AND attempted_payload ->> 'amendment_number' = %s
                 AND resolved_at IS NULL""",
            (source.id, lead.amendment_number),
        ).fetchone()
        if already:
            continue

        payload = {
            "amendment_number": lead.amendment_number,
            "lga": lead.lga,
            "canonical_url": lead.canonical_url,
            "retrieval_method": "SEARCH_RELAY",
            "corroboration": lead.corroboration,
            "relay_claims": lead.relay_claims,
            "notes": lead.notes,
        }
        queue_id = conn.execute(
            """INSERT INTO evidence_review_queue (source_id, attempted_payload,
                       failure_reason, missing_fields)
               VALUES (%s,%s,%s,%s) RETURNING id""",
            (source.id, Jsonb(payload), FAILURE_REASON, lead.unfillable_fields),
        ).fetchone()[0]

        created.append(queue_id)
        audit.write(conn, correlation_id, "LEAD_QUEUED", "evidence_review_queue",
                    queue_id, new_state=payload, actor_agent=ACTOR_AGENT)

    return created
