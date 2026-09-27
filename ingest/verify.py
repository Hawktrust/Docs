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
from .fetch import NotModified, RetrievalBlocked, fetch

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
            http_etag, http_last_modified, retrieval_method)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'DIRECT_FETCH')
        RETURNING id
        """,
        (source.id, record["source_reference"], record["source_url"],
         record["provider"], record["retrieved_at"], record["observed_at"],
         record["last_verified_at"], record["lane"], record["reliability"],
         record["evidence_class"], record["confidence"], record["lga"],
         record["title"], record.get("summary"), record.get("amendment_status"),
         Jsonb(record["geography"]) if record.get("geography") else None,
         # Kept so this record can be re-verified later by asking the publisher
         # whether it changed, rather than by re-reading it and hoping.
         getattr(retrieval, "etag", None),
         getattr(retrieval, "last_modified", None)),
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


# ------------------------------------------------------- re-verification

def revalidation_due(conn, *, older_than=None, limit=None):
    """Directly-fetched records that carry a validator, least recently verified first.

    Only DIRECT_FETCH records appear: migration 0028 refuses validators on
    anything else, because an operator capture's ETag belongs to a person's
    browser request rather than to one Crown can repeat.
    """
    sql = """SELECT id, source_url, http_etag, http_last_modified, last_verified_at
               FROM evidence_record
              WHERE retrieval_method = 'DIRECT_FETCH'
                AND (http_etag IS NOT NULL OR http_last_modified IS NOT NULL)"""
    params: list = []
    if older_than is not None:
        sql += " AND last_verified_at < %s"
        params.append(older_than)
    sql += " ORDER BY last_verified_at"
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)
    return conn.execute(sql, tuple(params)).fetchall()


def revalidate(conn, evidence_id, *, fetcher=fetch, correlation_id=None,
               actor_user_id=None) -> str:
    """Ask the source whether one record's document has changed.

    Returns what was learned, and the return value is the point:

      UNCHANGED  the source answered 304. last_verified_at and
                 last_revalidated_at move. retrieved_at does NOT — Crown did not
                 retrieve the document, and a record must never imply a fetch
                 that did not happen.
      CHANGED    the source served a document. Nothing is written here: what the
                 page now says has to go through the parser and the provenance
                 checks like any other retrieval, so this reports and leaves the
                 record alone rather than half-updating it.
      UNAVAILABLE the check did not reach the source. Nothing moves; the record
                 keeps the verification date it honestly had.
    """
    correlation_id = correlation_id or audit.new_correlation_id()
    row = conn.execute(
        """SELECT source_url, http_etag, http_last_modified FROM evidence_record
            WHERE id = %s AND retrieval_method = 'DIRECT_FETCH'""",
        (evidence_id,),
    ).fetchone()
    if row is None:
        raise VerificationFailed(
            f"no directly-fetched evidence record {evidence_id} to revalidate")
    url, etag, last_modified = row
    if not (etag or last_modified):
        raise VerificationFailed(
            f"{url} has no validator stored, so there is nothing to ask the source")

    try:
        result = fetcher(url, etag=etag, last_modified=last_modified)
    except RetrievalBlocked as exc:
        audit.write(conn, correlation_id, "EVIDENCE_REVALIDATION_UNAVAILABLE",
                    "evidence_record", evidence_id,
                    new_state={"source_url": url, "error": str(exc)},
                    evidence_id=evidence_id, actor_user_id=actor_user_id,
                    actor_agent=ACTOR_AGENT)
        return "UNAVAILABLE"

    if isinstance(result, NotModified):
        conn.execute(
            """UPDATE evidence_record
                  SET last_verified_at = %s, last_revalidated_at = %s,
                      http_etag = %s, http_last_modified = %s
                WHERE id = %s""",
            (result.checked_at, result.checked_at, result.etag,
             result.last_modified, evidence_id),
        )
        audit.write(conn, correlation_id, "EVIDENCE_REVALIDATED_UNCHANGED",
                    "evidence_record", evidence_id,
                    new_state={"source_url": url,
                               "confirmed_at": result.checked_at.isoformat()},
                    evidence_id=evidence_id, actor_user_id=actor_user_id,
                    actor_agent=ACTOR_AGENT)
        return "UNCHANGED"

    # 200: the document moved. Recording that is useful; acting on it is a
    # re-ingestion, not a revalidation, so it is left to the path that has a
    # parser and the provenance checks.
    audit.write(conn, correlation_id, "EVIDENCE_CHANGED_AT_SOURCE",
                "evidence_record", evidence_id,
                new_state={"source_url": url,
                           "observed_at": result.retrieved_at.isoformat()},
                evidence_id=evidence_id, actor_user_id=actor_user_id,
                actor_agent=ACTOR_AGENT)
    return "CHANGED"
