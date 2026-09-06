"""Promote a queued lead into evidence by retrieving it directly.

This is the step that turns "something told us about amendment C266wynd" into
"we read the page for amendment C266wynd". It is the only path by which a lead
becomes evidence, and the only one that may set retrieval_method to
DIRECT_FETCH — which is what migration 0003 requires before a record can be
called authoritative, and therefore before it can be a FACT.

The fetcher and parser are arguments so this path can be exercised now and will
work unchanged the moment the source host is reachable.
"""
from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from crown import audit

from . import provenance
from .adapters import vic_planning
from .fetch import RetrievalBlocked, fetch

ACTOR_AGENT = "ingest.verify"


class VerificationFailed(Exception):
    """The lead could not be retrieved or parsed. It stays in the queue."""


def pending(conn, source_id=None):
    """Leads still waiting on direct retrieval."""
    sql = """SELECT id, source_id, attempted_payload
             FROM evidence_review_queue
             WHERE resolved_at IS NULL
               AND attempted_payload ->> 'retrieval_method' = 'SEARCH_RELAY'"""
    params: tuple = ()
    if source_id:
        sql += " AND source_id = %s"
        params = (source_id,)
    return conn.execute(sql + " ORDER BY created_at", params).fetchall()


def verify(conn, queue_id, source, *, fetcher=fetch, parser=None,
           resolved_by=None, correlation_id=None) -> str:
    """Fetch one lead's canonical URL and promote it. Returns the evidence id."""
    parser = parser or vic_planning.from_html
    correlation_id = correlation_id or audit.new_correlation_id()

    row = conn.execute(
        "SELECT attempted_payload FROM evidence_review_queue WHERE id = %s AND resolved_at IS NULL",
        (queue_id,),
    ).fetchone()
    if row is None:
        raise VerificationFailed(f"no unresolved lead {queue_id}")
    lead = row[0]
    url = lead["canonical_url"]

    try:
        retrieval = fetcher(url)
    except RetrievalBlocked as exc:
        audit.write(conn, correlation_id, "LEAD_VERIFICATION_BLOCKED",
                    "evidence_review_queue", queue_id,
                    new_state={"url": url, "error": str(exc)}, actor_agent=ACTOR_AGENT)
        raise VerificationFailed(f"{url} could not be retrieved: {exc}") from exc

    try:
        parsed = parser(retrieval.body, retrieval.url)
    except vic_planning.SourceFormatUnknown as exc:
        audit.write(conn, correlation_id, "LEAD_VERIFICATION_UNPARSEABLE",
                    "evidence_review_queue", queue_id,
                    new_state={"url": url, "error": str(exc)}, actor_agent=ACTOR_AGENT)
        raise VerificationFailed(f"{url} was retrieved but not parseable: {exc}") from exc

    record = _to_evidence(parsed, lead, retrieval, source)
    gaps = provenance.missing_fields(record)
    if gaps:
        raise VerificationFailed(
            f"{url} was retrieved and parsed but still lacks {gaps}; it stays queued"
        )

    evidence_id = conn.execute(
        """
        INSERT INTO evidence_record (
            source_id, source_reference, source_url, provider, retrieved_at,
            observed_at, last_verified_at, lane, reliability, evidence_class,
            confidence, lga, title, summary, amendment_status, geography,
            retrieval_method)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'DIRECT_FETCH')
        RETURNING id
        """,
        (source.id, record["source_reference"], record["source_url"],
         record["provider"], record["retrieved_at"], record["observed_at"],
         record["last_verified_at"], record["lane"], record["reliability"],
         record["evidence_class"], record["confidence"], record["lga"],
         record["title"], record.get("summary"), record.get("amendment_status"),
         Jsonb(record["geography"]) if record.get("geography") else None),
    ).fetchone()[0]

    conn.execute(
        "UPDATE evidence_review_queue SET resolved_at = now(), resolved_by = %s WHERE id = %s",
        (resolved_by, queue_id),
    )
    audit.write(conn, correlation_id, "LEAD_VERIFIED", "evidence_record", evidence_id,
                new_state={"from_queue": str(queue_id), "source_url": url,
                           "evidence_class": record["evidence_class"]},
                evidence_id=evidence_id, actor_user_id=resolved_by,
                actor_agent=ACTOR_AGENT)
    return evidence_id


def _to_evidence(parsed, lead, retrieval, source) -> dict:
    """Build the evidence record from a directly retrieved page.

    The parsed page is authoritative: it is the publisher's own statement,
    retrieved by us. The lead contributes only the identifiers that led us here.
    """
    item = parsed[0] if isinstance(parsed, list) else parsed
    status = (item.get("status") or "").strip().upper()
    evidence_class = vic_planning.classify(status)
    return {
        "source_reference": item.get("amendment_number") or lead["amendment_number"],
        "source_url": retrieval.url,
        "provider": source.provider,
        "retrieved_at": retrieval.retrieved_at,
        "observed_at": vic_planning._parse_date(item.get("observed_at")),
        "last_verified_at": retrieval.retrieved_at,
        "lane": source.lane,
        "reliability": vic_planning.RELIABILITY,
        "evidence_class": evidence_class,
        "confidence": vic_planning.CONFIDENCE.get(evidence_class,
                                                  vic_planning.DEFAULT_CONFIDENCE),
        "lga": item.get("lga") or lead["lga"],
        "title": item.get("title"),
        "summary": item.get("summary"),
        "amendment_status": item.get("status"),
        "geography": item.get("geography"),
    }
