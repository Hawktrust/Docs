"""Operator capture: the channel that exists when the network one does not.

A named human opens the publisher's page in their own browser and the bytes come
back with them. These tests hold the line on what that is worth.
"""
import json

import psycopg
import pytest

from ingest import capture, registry
from tests.conftest import user_id

RAW = "<html><head><title>Wyndham C266wynd</title></head><body>Amendment C266wynd</body></html>"
URL = "https://planning-schemes.app.planning.vic.gov.au/Wyndham/amendments/C266wynd"


def bundle(**overrides):
    payload = {
        "capture": {
            "source_url": URL,
            "captured_at": "2026-09-06T10:00:00+00:00",
            "page_title": "Wyndham C266wynd",
            "sha256": capture.sha256_of(RAW),
            "raw_html": RAW,
        },
        "confirmed_by_operator": True,
        "records": [{
            "amendment_number": "C266wynd",
            "lga": "Wyndham",
            "title": "Update to the Wyndham Municipal Planning Strategy",
            "status": "GAZETTED",
            "observed_at": "2026-05-08",
            "detail_url": URL,
            "geography": {"suburbs": ["Werribee"]},
        }],
    }
    payload.update(overrides)
    return payload


def source(db):
    return registry.resolve(db, "VIC_PLANNING_AMENDMENTS")


# ------------------------------------------------------- a bundle must hold together

def test_a_bundle_whose_hash_does_not_match_its_content_is_refused(db):
    tampered = bundle()
    tampered["capture"]["raw_html"] = RAW.replace("C266wynd", "C999wynd")

    with pytest.raises(capture.BadCapture, match="altered since it was taken"):
        capture.ingest_capture(db, source(db), tampered,
                               user_id(db, "hawk@crown.local"))
    assert db.execute("SELECT count(*) FROM evidence_record").fetchone()[0] == 0


def test_an_unconfirmed_bundle_is_refused(db):
    with pytest.raises(capture.BadCapture, match="has not confirmed"):
        capture.ingest_capture(db, source(db), bundle(confirmed_by_operator=False),
                               user_id(db, "hawk@crown.local"))


def test_a_bundle_missing_the_bytes_is_refused(db):
    broken = bundle()
    broken["capture"]["raw_html"] = ""
    with pytest.raises(capture.BadCapture, match="missing raw_html"):
        capture.ingest_capture(db, source(db), broken, user_id(db, "hawk@crown.local"))


# ---------------------------------------------------------------- what it produces

def test_a_capture_becomes_evidence_a_gazetted_amendment_can_be_a_fact(db):
    operator = user_id(db, "hawk@crown.local")
    report = capture.ingest_capture(db, source(db), bundle(), operator)
    assert report.ingested == ["C266wynd"]

    row = db.execute(
        """SELECT retrieval_method, reliability::text, evidence_class::text,
                  captured_by, capture_sha256, source_url, lga, origin::text
           FROM evidence_record"""
    ).fetchone()
    assert row[0] == "OPERATOR_CAPTURE"
    assert row[1] == "STRONG"
    assert row[2] == "FACT"          # gazetted, and a person read the page
    assert row[3] == operator        # attributable
    assert row[4] == capture.sha256_of(RAW)
    assert row[5] == URL
    assert row[6] == "Wyndham"
    assert row[7] == "REAL"


def test_a_capture_can_never_be_authoritative(db):
    """AUTHORITATIVE stays reserved for a fetch the system made itself."""
    src = source(db)
    with pytest.raises(psycopg.errors.CheckViolation,
                       match="retrieval_method_limits_reliability"):
        db.execute(
            """INSERT INTO evidence_record (source_id, source_reference, source_url,
                   provider, retrieved_at, observed_at, last_verified_at, lane,
                   reliability, evidence_class, confidence, lga, title,
                   retrieval_method, captured_by, capture_sha256)
               VALUES (%s,'C1','https://x','VIC',now(),now(),now(),'B_OPEN',
                       'AUTHORITATIVE','FACT',1.0,'Wyndham','t','OPERATOR_CAPTURE',
                       %s,'abc')""",
            (src.id, user_id(db, "hawk@crown.local")))
    db.rollback()


def test_a_capture_must_name_who_took_it_and_keep_what_they_took(db):
    src = source(db)
    with pytest.raises(psycopg.errors.CheckViolation,
                       match="capture_is_attributed_and_retained"):
        db.execute(
            """INSERT INTO evidence_record (source_id, source_reference, source_url,
                   provider, retrieved_at, observed_at, last_verified_at, lane,
                   reliability, evidence_class, confidence, lga, title,
                   retrieval_method)
               VALUES (%s,'C1','https://x','VIC',now(),now(),now(),'B_OPEN',
                       'STRONG','FACT',1.0,'Wyndham','t','OPERATOR_CAPTURE')""",
            (src.id,))
    db.rollback()


def test_the_bytes_are_kept_so_the_record_can_be_rechecked(db):
    operator = user_id(db, "hawk@crown.local")
    capture.ingest_capture(db, source(db), bundle(), operator)

    stored, url, who = db.execute(
        """SELECT c.raw_html, c.source_url, c.captured_by FROM capture_artifact c
           JOIN evidence_record e ON e.capture_sha256 = c.sha256"""
    ).fetchone()
    assert stored == RAW
    assert url == URL
    assert who == operator


def test_the_same_page_captured_twice_is_one_artifact(db):
    operator = user_id(db, "hawk@crown.local")
    capture.ingest_capture(db, source(db), bundle(), operator)
    capture.ingest_capture(db, source(db), bundle(), operator)
    assert db.execute("SELECT count(*) FROM capture_artifact").fetchone()[0] == 1


def test_a_record_the_operator_left_incomplete_goes_to_review_not_the_graph(db):
    incomplete = bundle()
    del incomplete["records"][0]["observed_at"]

    report = capture.ingest_capture(db, source(db), incomplete,
                                    user_id(db, "hawk@crown.local"))
    assert report.ingested == []
    assert report.review_queued[0][1] == ["observed_at"]
    assert db.execute("SELECT count(*) FROM evidence_record").fetchone()[0] == 0


def test_a_capture_closes_the_lead_that_was_waiting_for_it(db):
    """The seven queued leads are exactly what a capture is for."""
    from ingest import leads as leads_module
    from tests.conftest import LEADS_FILE

    src = source(db)
    leads_module.record(db, src, leads_module.load(LEADS_FILE))
    assert db.execute(
        "SELECT count(*) FROM evidence_review_queue WHERE resolved_at IS NULL"
    ).fetchone()[0] == 7

    report = capture.ingest_capture(db, src, bundle(), user_id(db, "hawk@crown.local"))
    assert report.leads_resolved == ["C266wynd"]
    assert db.execute(
        "SELECT count(*) FROM evidence_review_queue WHERE resolved_at IS NULL"
    ).fetchone()[0] == 6


def test_the_whole_capture_is_audited(db):
    capture.ingest_capture(db, source(db), bundle(), user_id(db, "hawk@crown.local"))
    actions = {r[0] for r in db.execute(
        "SELECT action FROM audit_event WHERE actor_agent = 'ingest.capture'").fetchall()}
    assert {"PAGE_CAPTURED", "EVIDENCE_CREATED"} <= actions


def test_captured_evidence_makes_a_real_opportunity(db):
    """The point of all this: a real amendment reaching the graph."""
    from crown import opportunity, reports

    capture.ingest_capture(db, source(db), bundle(), user_id(db, "hawk@crown.local"))
    change = opportunity.refresh(db, user_id(db, "analyst@crown.local"))[0]

    assert change.origin == "REAL"
    assert change.stage == "CONFIRMED"
    assert change.geography_label == "Werribee"
    assert reports.overview(db).real_evidence == 1
