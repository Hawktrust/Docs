"""Re-verification: asking the publisher whether a document changed.

last_verified_at decides what NO_EVIDENCE_IS_PAST_ITS_SHELF_LIFE reports, and
until migration 0028 nothing could move it except a full re-fetch and re-parse.
A conditional request lets the source answer instead, and the point of these
tests is that the answer is recorded as what it is.

The distinction they defend: a 304 moves last_verified_at and must NOT move
retrieved_at, because Crown did not retrieve the document. A record must never
imply a fetch that did not happen.
"""
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from ingest import verify
from ingest.fetch import NotModified, Retrieval, RetrievalBlocked
from tests.conftest import add_evidence


def fetched_record(db, *, reference="TEST-RV-1", etag='"abc123"',
                   last_modified="Wed, 21 Oct 2026 07:28:00 GMT"):
    """A directly-fetched record carrying what the source offered to be asked with."""
    evidence_id = add_evidence(db, reference=reference)
    db.execute(
        """UPDATE evidence_record
              SET retrieval_method = 'DIRECT_FETCH', http_etag = %s,
                  http_last_modified = %s
            WHERE id = %s""",
        (etag, last_modified, evidence_id))
    return evidence_id


def timestamps(db, evidence_id):
    return db.execute(
        """SELECT retrieved_at, last_verified_at, last_revalidated_at
             FROM evidence_record WHERE id = %s""", (evidence_id,)).fetchone()


# --------------------------------------------- the schema holds the distinction

def test_only_a_direct_fetch_may_carry_a_validator(db):
    """An operator capture's ETag belongs to a person's browser, not to Crown.

    Storing it would let a later 304 refresh last_verified_at on a record the
    system has never fetched.
    """
    evidence_id = add_evidence(db, reference="TEST-RV-CAPTURE")
    db.execute(
        """UPDATE evidence_record
              SET retrieval_method = 'OPERATOR_CAPTURE', reliability = 'STRONG',
                  captured_by = (SELECT id FROM app_user LIMIT 1),
                  capture_sha256 = repeat('a', 64)
            WHERE id = %s""", (evidence_id,))

    with pytest.raises(psycopg.errors.CheckViolation,
                       match="only_a_direct_fetch_carries_validators"):
        db.execute("UPDATE evidence_record SET http_etag = %s WHERE id = %s",
                   ('"x"', evidence_id))
    db.rollback()


def test_a_revalidation_cannot_predate_the_retrieval_it_confirms(db):
    evidence_id = fetched_record(db)
    with pytest.raises(psycopg.errors.CheckViolation,
                       match="revalidation_follows_retrieval"):
        db.execute(
            """UPDATE evidence_record SET last_revalidated_at = retrieved_at - interval '1 day'
                WHERE id = %s""", (evidence_id,))
    db.rollback()


# ------------------------------------------------------------------ the fetcher

def test_a_304_to_an_unconditional_request_confirms_nothing(monkeypatch):
    """Nothing was asked, so nothing was answered. Treating it as "unchanged"
    would refresh a verification date on no evidence at all."""
    from ingest import fetch as fetch_module

    class Response:
        status_code = 304
        headers: dict = {}
        text = ""

    monkeypatch.setattr(fetch_module._session, "get", lambda *a, **k: Response())
    with pytest.raises(RetrievalBlocked, match="without a conditional request"):
        fetch_module.fetch("https://example.test/page", check_robots=False)


def test_a_retrieval_keeps_the_validators_the_source_offered(monkeypatch):
    from ingest import fetch as fetch_module

    class Response:
        status_code = 200
        headers = {"etag": '"v2"', "last-modified": "Thu, 01 Jan 2026 00:00:00 GMT",
                   "content-type": "text/html"}
        text = "<html></html>"
        content = b"<html></html>"

    monkeypatch.setattr(fetch_module._session, "get", lambda *a, **k: Response())
    result = fetch_module.fetch("https://example.test/page", check_robots=False)

    assert isinstance(result, Retrieval)
    assert result.etag == '"v2"'
    assert result.last_modified == "Thu, 01 Jan 2026 00:00:00 GMT"


def test_a_conditional_request_asks_with_what_was_stored(monkeypatch):
    """The validators go out as If-None-Match and If-Modified-Since, per request."""
    from ingest import fetch as fetch_module
    seen: dict[str, str] = {}

    class Response:
        status_code = 304
        headers: dict = {}
        text = ""

    def capture(url, timeout=30, headers=None):
        seen.update(headers or {})
        return Response()

    monkeypatch.setattr(fetch_module._session, "get", capture)
    result = fetch_module.fetch("https://example.test/page", check_robots=False,
                                etag='"abc"',
                                last_modified="Mon, 01 Jun 2026 00:00:00 GMT")

    assert seen["If-None-Match"] == '"abc"'
    assert seen["If-Modified-Since"] == "Mon, 01 Jun 2026 00:00:00 GMT"
    assert isinstance(result, NotModified)


# --------------------------------------------------------- what revalidate does

def test_unchanged_moves_the_verification_date_and_not_the_retrieval_date(db):
    """The whole point. The publisher confirmed it; Crown did not re-fetch it."""
    evidence_id = fetched_record(db)
    db.execute(
        """UPDATE evidence_record
              SET retrieved_at = now() - interval '200 days',
                  last_verified_at = now() - interval '200 days'
            WHERE id = %s""", (evidence_id,))
    before = timestamps(db, evidence_id)

    confirmed = datetime.now(timezone.utc)

    def unchanged(url, etag=None, last_modified=None):
        assert etag == '"abc123"'          # it asked with what was stored
        return NotModified(url=url, checked_at=confirmed, etag='"abc123"',
                           last_modified=last_modified)

    assert verify.revalidate(db, evidence_id, fetcher=unchanged) == "UNCHANGED"

    after = timestamps(db, evidence_id)
    assert after[0] == before[0], "retrieved_at must not move: nothing was retrieved"
    assert after[1] > before[1], "last_verified_at should move: the source confirmed it"
    assert after[2] is not None, "last_revalidated_at records the 304"

    assert db.execute(
        """SELECT count(*) FROM audit_event
            WHERE action = 'EVIDENCE_REVALIDATED_UNCHANGED'""").fetchone()[0] == 1


def test_a_changed_document_is_reported_and_not_half_written(db):
    """Re-ingesting is a separate act: it needs the parser and the provenance
    checks, so revalidation reports the change rather than applying it."""
    evidence_id = fetched_record(db)
    before = timestamps(db, evidence_id)

    def changed(url, etag=None, last_modified=None):
        return Retrieval(url=url, retrieved_at=datetime.now(timezone.utc),
                         status_code=200, body="<html>new</html>",
                         content_type="text/html", etag='"v9"')

    assert verify.revalidate(db, evidence_id, fetcher=changed) == "CHANGED"

    assert timestamps(db, evidence_id) == before, "nothing may move on a change"
    assert db.execute(
        "SELECT count(*) FROM audit_event WHERE action = 'EVIDENCE_CHANGED_AT_SOURCE'"
    ).fetchone()[0] == 1


def test_a_check_that_did_not_reach_the_source_moves_nothing(db):
    """A record keeps the verification date it honestly had."""
    evidence_id = fetched_record(db)
    before = timestamps(db, evidence_id)

    def blocked(url, etag=None, last_modified=None):
        raise RetrievalBlocked("403 at CONNECT")

    assert verify.revalidate(db, evidence_id, fetcher=blocked) == "UNAVAILABLE"
    assert timestamps(db, evidence_id) == before
    assert db.execute(
        """SELECT count(*) FROM audit_event
            WHERE action = 'EVIDENCE_REVALIDATION_UNAVAILABLE'""").fetchone()[0] == 1


def test_a_record_with_no_validator_cannot_be_revalidated(db):
    """There is nothing to ask the source, and inventing a question would mean
    inventing the answer."""
    evidence_id = add_evidence(db, reference="TEST-RV-BARE")
    db.execute("UPDATE evidence_record SET retrieval_method='DIRECT_FETCH' WHERE id=%s",
               (evidence_id,))
    with pytest.raises(verify.VerificationFailed, match="no validator stored"):
        verify.revalidate(db, evidence_id)


# ------------------------------------------------------------- what is selected

def test_only_revalidatable_records_are_offered(db):
    """Relayed records and records with no validator are not asked about."""
    with_validator = fetched_record(db, reference="TEST-RV-A")
    bare = add_evidence(db, reference="TEST-RV-B")
    db.execute("UPDATE evidence_record SET retrieval_method='DIRECT_FETCH' WHERE id=%s",
               (bare,))
    relayed = add_evidence(db, reference="TEST-RV-C", evidence_class="UNKNOWN")
    db.execute(
        """UPDATE evidence_record SET retrieval_method='SEARCH_RELAY',
                  reliability='MODERATE', confidence=0.5 WHERE id=%s""", (relayed,))

    offered = [row[0] for row in verify.revalidation_due(db)]
    assert with_validator in offered
    assert bare not in offered
    assert relayed not in offered


def test_the_least_recently_verified_is_asked_about_first(db):
    """A re-verification pass has a budget; it should spend it on the stalest."""
    fresh = fetched_record(db, reference="TEST-RV-FRESH")
    stale = fetched_record(db, reference="TEST-RV-STALE")
    db.execute("UPDATE evidence_record SET last_verified_at = now() - interval '300 days' "
               "WHERE id = %s", (stale,))

    offered = [row[0] for row in verify.revalidation_due(db, limit=1)]
    assert offered == [stale]
    assert fresh not in offered
