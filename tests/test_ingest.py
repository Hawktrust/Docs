"""Acceptance criteria 2 and 3, and the classification rule behind item 2.

These run the real pipeline against a database built by the real migration.
"""
import pytest

from ingest import registry
from ingest.adapters import vic_planning
from ingest.pipeline import ingest

WYNDHAM_GAZETTED = {
    "amendment_number": "TEST-C001wynd",
    "lga": "Wyndham",
    "title": "Test fixture — gazetted amendment",
    "status": "GAZETTED",
    "observed_at": "2026-08-14",
    "detail_url": "https://www.planning.vic.gov.au/amendment/TEST-C001wynd",
}
WYNDHAM_EXHIBITED = dict(WYNDHAM_GAZETTED,
                         amendment_number="TEST-C002wynd", status="EXHIBITED")
# no observed_at and no title: two mandatory provenance fields absent
WYNDHAM_INCOMPLETE = {
    "amendment_number": "TEST-C003wynd",
    "lga": "Wyndham",
    "status": "GAZETTED",
    "detail_url": "https://www.planning.vic.gov.au/amendment/TEST-C003wynd",
}
MELTON = dict(WYNDHAM_GAZETTED, amendment_number="TEST-C900melt", lga="Melton")


def source(db):
    return registry.resolve(db, "VIC_PLANNING_AMENDMENTS")


def test_register_refuses_a_blocked_source(db):
    """Constitution §1: a BLOCKED source cannot be ingested from."""
    with pytest.raises(registry.SourceNotIngestible):
        registry.resolve(db, "RP_DATA_SEAT")


def test_register_refuses_an_unregistered_source(db):
    with pytest.raises(registry.SourceNotRegistered):
        registry.resolve(db, "NOT_IN_THE_REGISTER")


def test_ingestion_writes_evidence_with_full_provenance(db, retrieval):
    report = ingest(db, source(db), retrieval, [WYNDHAM_GAZETTED], "Wyndham")
    assert report.ingested == ["TEST-C001wynd"]

    row = db.execute(
        """SELECT source_reference, source_url, provider, retrieved_at, observed_at,
                  lane, reliability, evidence_class, lga
           FROM evidence_record"""
    ).fetchone()
    assert all(v is not None for v in row)
    assert row[7] == "FACT"          # gazetted
    assert row[8] == "Wyndham"


def test_rerunning_ingestion_produces_zero_duplicates(db, retrieval):
    """Acceptance criterion 2."""
    src = source(db)
    first = ingest(db, src, retrieval, [WYNDHAM_GAZETTED], "Wyndham")
    second = ingest(db, src, retrieval, [WYNDHAM_GAZETTED], "Wyndham")

    assert first.ingested == ["TEST-C001wynd"]
    assert second.ingested == []
    assert second.duplicates == ["TEST-C001wynd"]

    counts = db.execute(
        "SELECT (SELECT count(*) FROM raw_ingest), (SELECT count(*) FROM evidence_record)"
    ).fetchone()
    assert counts == (1, 1)


def test_missing_provenance_goes_to_the_review_queue_not_the_graph(db, retrieval):
    """Acceptance criterion 3."""
    report = ingest(db, source(db), retrieval, [WYNDHAM_INCOMPLETE], "Wyndham")

    assert report.ingested == []
    assert len(report.review_queued) == 1
    _, missing = report.review_queued[0]
    assert set(missing) == {"observed_at", "title"}

    assert db.execute("SELECT count(*) FROM evidence_record").fetchone()[0] == 0
    queued = db.execute(
        "SELECT failure_reason, missing_fields FROM evidence_review_queue"
    ).fetchone()
    assert "provenance" in queued[0]
    assert set(queued[1]) == {"observed_at", "title"}


def test_exhibited_amendment_is_a_hypothesis_not_a_fact(db, retrieval):
    """Ticket item 2: gazetted is FACT, exhibited-but-undecided is HYPOTHESIS."""
    ingest(db, source(db), retrieval, [WYNDHAM_GAZETTED, WYNDHAM_EXHIBITED], "Wyndham")
    classes = dict(db.execute(
        "SELECT source_reference, evidence_class::text FROM evidence_record").fetchall())
    assert classes == {"TEST-C001wynd": "FACT", "TEST-C002wynd": "HYPOTHESIS"}


def test_run_is_scoped_to_one_lga(db, retrieval):
    report = ingest(db, source(db), retrieval, [WYNDHAM_GAZETTED, MELTON], "Wyndham")
    assert report.ingested == ["TEST-C001wynd"]
    assert db.execute("SELECT count(*) FROM evidence_record WHERE lga='Melton'").fetchone()[0] == 0


def test_every_transition_writes_one_audit_row(db, retrieval):
    """Ticket item 8 / Constitution §5."""
    src = source(db)
    ingest(db, src, retrieval, [WYNDHAM_GAZETTED, WYNDHAM_INCOMPLETE], "Wyndham")
    actions = [r[0] for r in db.execute(
        "SELECT action FROM audit_event ORDER BY id").fetchall()]
    assert actions == ["RAW_INGESTED", "EVIDENCE_CREATED",
                       "RAW_INGESTED", "EVIDENCE_REJECTED_TO_REVIEW"]

    ingest(db, src, retrieval, [WYNDHAM_GAZETTED], "Wyndham")
    assert db.execute(
        "SELECT count(*) FROM audit_event WHERE action='INGEST_SKIPPED_DUPLICATE'"
    ).fetchone()[0] == 1


def test_live_page_parser_refuses_to_guess(db):
    """The parser for the real page is absent, and says so rather than inventing."""
    with pytest.raises(vic_planning.SourceFormatUnknown):
        vic_planning.from_html("<html>anything</html>", "https://example.invalid")
