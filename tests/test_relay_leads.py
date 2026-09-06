"""The search-relay path: leads, and the constraint that keeps them out of the graph.

Context. Egress from the build environment reaches neither planning.vic.gov.au
nor the planning schemes app. One channel is open, a server-side web search, and
it returns real amendment identifiers. It is not reliable enough to base evidence
on: two independent searches for the same amendment disagreed on its gazettal
date, and two more described different amendments under one number.

These tests hold that line.
"""
import json

import psycopg
import pytest

from crown import audit
from ingest import leads as leads_module
from ingest import registry, verify
from ingest.fetch import RetrievalBlocked
from tests.conftest import LEADS_FILE, FakeRetrieval


def source(db):
    return registry.resolve(db, "VIC_PLANNING_AMENDMENTS")


# ------------------------------------------------- the database holds the line

def test_relayed_data_cannot_be_called_authoritative(db):
    """Migration 0003. Second-hand is not proof."""
    src = source(db)
    with pytest.raises(psycopg.errors.CheckViolation,
                       match="retrieval_method_limits_reliability"):
        db.execute(
            """INSERT INTO evidence_record (source_id, source_reference, source_url,
                   provider, retrieved_at, observed_at, last_verified_at, lane,
                   reliability, evidence_class, confidence, lga, title, retrieval_method)
               VALUES (%s,'C266wynd','https://planning-schemes.app.planning.vic.gov.au/x',
                       'State Government of Victoria', now(), now(), now(), 'B_OPEN',
                       'AUTHORITATIVE','UNKNOWN',0.5,'Wyndham','relayed','SEARCH_RELAY')""",
            (src.id,))
    db.rollback()


def test_relayed_data_therefore_cannot_be_a_fact(db):
    """0003 and 0001 together: a FACT needs a strong source, and a relay is not one."""
    src = source(db)
    for reliability in ("AUTHORITATIVE", "STRONG", "MODERATE", "WEAK", "UNVERIFIED"):
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(
                """INSERT INTO evidence_record (source_id, source_reference, source_url,
                       provider, retrieved_at, observed_at, last_verified_at, lane,
                       reliability, evidence_class, confidence, lga, title, retrieval_method)
                   VALUES (%s,'C266wynd','https://x','VIC', now(), now(), now(), 'B_OPEN',
                           %s,'FACT',1.0,'Wyndham','relayed fact','SEARCH_RELAY')""",
                (src.id, reliability))
        db.rollback()


def test_a_directly_fetched_record_may_be_a_fact(db):
    """The constraint constrains the relay, not the pipeline."""
    src = source(db)
    db.execute(
        """INSERT INTO evidence_record (source_id, source_reference, source_url,
               provider, retrieved_at, observed_at, last_verified_at, lane,
               reliability, evidence_class, confidence, lga, title, retrieval_method)
           VALUES (%s,'C266wynd','https://x','VIC', now(), now(), now(), 'B_OPEN',
                   'AUTHORITATIVE','FACT',1.0,'Wyndham','fetched','DIRECT_FETCH')""",
        (src.id,))
    assert db.execute("SELECT count(*) FROM evidence_record").fetchone()[0] == 1


def test_direct_fetch_is_the_default_so_a_relay_must_declare_itself(db):
    src = source(db)
    db.execute(
        """INSERT INTO evidence_record (source_id, source_reference, source_url,
               provider, retrieved_at, observed_at, last_verified_at, lane,
               reliability, evidence_class, confidence, lga, title)
           VALUES (%s,'C1','https://x','VIC',now(),now(),now(),'B_OPEN',
                   'AUTHORITATIVE','FACT',1.0,'Wyndham','t')""", (src.id,))
    assert db.execute(
        "SELECT retrieval_method FROM evidence_record").fetchone()[0] == "DIRECT_FETCH"


# ----------------------------------------------------------------- the leads

def test_the_shipped_leads_file_is_real_and_honest_about_itself():
    payload = json.load(open(LEADS_FILE))
    assert payload["_provenance"]["why_not_evidence"]
    assert "unreliable for detail" in payload["_provenance"]["reliability_finding"]

    corroboration = {l["amendment_number"]: l["corroboration"] for l in payload["leads"]}
    # the two that contradicted themselves are marked as such, not quietly dropped
    assert corroboration["C232melt"] == "CONTRADICTED"
    assert corroboration["C272hume"] == "CONTRADICTED"
    assert corroboration["C266wynd"] == "CORROBORATED"

    for lead in payload["leads"]:
        assert lead["canonical_url"].startswith(
            "https://planning-schemes.app.planning.vic.gov.au/")
        assert lead["lga"] in ("Wyndham", "Melton", "Hume")


def test_leads_go_to_the_review_queue_and_never_into_the_graph(db):
    src = source(db)
    created = leads_module.record(db, src, leads_module.load(LEADS_FILE))

    assert len(created) == 7
    assert db.execute("SELECT count(*) FROM evidence_record").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM evidence_review_queue").fetchone()[0] == 7

    reason, missing, payload = db.execute(
        """SELECT failure_reason, missing_fields, attempted_payload
           FROM evidence_review_queue
           WHERE attempted_payload ->> 'amendment_number' = 'C266wynd'"""
    ).fetchone()
    assert "never fetched" in reason
    assert set(missing) == {"observed_at", "title"}
    assert payload["retrieval_method"] == "SEARCH_RELAY"


def test_a_contradicted_lead_records_that_its_status_is_unusable(db):
    src = source(db)
    leads_module.record(db, src, leads_module.load(LEADS_FILE))
    missing = db.execute(
        """SELECT missing_fields FROM evidence_review_queue
           WHERE attempted_payload ->> 'amendment_number' = 'C232melt'"""
    ).fetchone()[0]
    assert "amendment_status" in missing


def test_requeueing_the_same_leads_does_not_duplicate_them(db):
    src = source(db)
    leads_module.record(db, src, leads_module.load(LEADS_FILE))
    again = leads_module.record(db, src, leads_module.load(LEADS_FILE))
    assert again == []
    assert db.execute("SELECT count(*) FROM evidence_review_queue").fetchone()[0] == 7


def test_every_queued_lead_is_audited(db):
    src = source(db)
    leads_module.record(db, src, leads_module.load(LEADS_FILE))
    assert db.execute(
        "SELECT count(*) FROM audit_event WHERE action = 'LEAD_QUEUED'").fetchone()[0] == 7


# ---------------------------------------------------------------- verification

def test_a_blocked_verification_leaves_the_lead_queued(db):
    """What actually happens today. The lead stays; nothing is invented."""
    src = source(db)
    queue_id = leads_module.record(db, src, leads_module.load(LEADS_FILE))[0]

    def blocked(url, timeout=30):
        raise RetrievalBlocked(f"GET {url} failed: 403 from the egress proxy")

    with pytest.raises(verify.VerificationFailed, match="could not be retrieved"):
        verify.verify(db, queue_id, src, fetcher=blocked)

    assert db.execute("SELECT count(*) FROM evidence_record").fetchone()[0] == 0
    assert db.execute(
        "SELECT resolved_at FROM evidence_review_queue WHERE id = %s",
        (queue_id,)).fetchone()[0] is None
    assert db.execute(
        "SELECT count(*) FROM audit_event WHERE action = 'LEAD_VERIFICATION_BLOCKED'"
    ).fetchone()[0] == 1


def test_a_retrieved_but_unparseable_page_also_leaves_the_lead_queued(db):
    """The parser refuses to guess, so retrieval alone is not enough."""
    src = source(db)
    queue_id = leads_module.record(db, src, leads_module.load(LEADS_FILE))[0]

    def fetched(url, timeout=30):
        return FakeRetrieval(url)

    with pytest.raises(verify.VerificationFailed, match="not parseable"):
        verify.verify(db, queue_id, src, fetcher=fetched)
    assert db.execute("SELECT count(*) FROM evidence_record").fetchone()[0] == 0


def test_direct_retrieval_promotes_a_lead_into_evidence(db):
    """The path that runs the moment the host is reachable.

    Fetcher and parser are injected here; in production they are the real ones.
    """
    src = source(db)
    queue_id = leads_module.record(db, src, leads_module.load(LEADS_FILE))[0]

    def fetched(url, timeout=30):
        return FakeRetrieval(url)

    def parsed(body, url):
        return [{
            "amendment_number": "C266wynd",
            "lga": "Wyndham",
            "title": "Update to the Wyndham Municipal Planning Strategy",
            "status": "GAZETTED",
            "observed_at": "2026-05-08",
            "geography": {"suburbs": ["Werribee"]},
        }]

    evidence_id = verify.verify(db, queue_id, src, fetcher=fetched, parser=parsed)

    row = db.execute(
        """SELECT source_reference, retrieval_method, evidence_class::text,
                  reliability::text, source_url, retrieved_at, lga
           FROM evidence_record WHERE id = %s""", (evidence_id,)).fetchone()
    assert row[0] == "C266wynd"
    assert row[1] == "DIRECT_FETCH"        # it was fetched, so it may be strong
    assert row[2] == "FACT"                # gazetted, and now directly verified
    assert row[3] == "AUTHORITATIVE"
    assert row[4].endswith("/Wyndham/amendments/C266wynd")
    assert row[5] is not None
    assert row[6] == "Wyndham"

    resolved = db.execute(
        "SELECT resolved_at FROM evidence_review_queue WHERE id = %s",
        (queue_id,)).fetchone()[0]
    assert resolved is not None
    assert db.execute(
        "SELECT count(*) FROM audit_event WHERE action = 'LEAD_VERIFIED'").fetchone()[0] == 1


def test_verification_refuses_a_page_that_still_lacks_provenance(db):
    src = source(db)
    queue_id = leads_module.record(db, src, leads_module.load(LEADS_FILE))[0]

    def fetched(url, timeout=30):
        return FakeRetrieval(url)

    def parsed_without_a_date(body, url):
        return [{"amendment_number": "C266wynd", "lga": "Wyndham",
                 "title": "no observed_at", "status": "GAZETTED"}]

    with pytest.raises(verify.VerificationFailed, match="still lacks"):
        verify.verify(db, queue_id, src, fetcher=fetched, parser=parsed_without_a_date)
    assert db.execute("SELECT count(*) FROM evidence_record").fetchone()[0] == 0
