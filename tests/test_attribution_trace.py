"""Acceptance criterion 11: for any attribution record, the originating signal
can be traced back to its source URL and retrieval date."""
import pytest

from crown import approval, attribution, matching, opportunity
from tests.conftest import add_evidence, user_id


def a_full_chain(db):
    evidence_id = add_evidence(db, reference="TEST-C060wynd", observed_days_ago=40)
    owner = user_id(db, "analyst@crown.local")
    oid = opportunity.refresh(db, owner)[0].opportunity_id
    matching.rank(db, oid)
    match_id = db.execute(
        "SELECT id FROM match_result WHERE NOT is_excluded ORDER BY total_score DESC LIMIT 1"
    ).fetchone()[0]
    approver = user_id(db, "compliance@crown.local")
    approval_id = approval.decide(db, match_id, "APPROVED", "pack checked",
                                  approver, "COMPLIANCE")
    return evidence_id, approval_id


def test_an_approved_match_produces_a_traceable_attribution(db):
    evidence_id, approval_id = a_full_chain(db)
    attribution_id = attribution.progress(db, approval_id)

    row = attribution.trace(db, attribution_id)
    assert row is not None
    (_, lga, geography, buyer, reference, source_url, retrieved_at,
     evidence_class, source_code) = row

    assert lga == "Wyndham" and geography == "Tarneit"
    assert reference == "TEST-C060wynd"
    assert source_url.startswith("https://www.planning.vic.gov.au/")
    assert retrieved_at is not None
    assert evidence_class == "FACT"
    assert source_code == "VIC_PLANNING_AMENDMENTS"


def test_the_attribution_names_the_evidence_that_originated_it(db):
    evidence_id, approval_id = a_full_chain(db)
    attribution_id = attribution.progress(db, approval_id)
    stored = db.execute(
        "SELECT originating_evidence_id FROM attribution WHERE id = %s",
        (attribution_id,)).fetchone()[0]
    assert stored == evidence_id


def test_the_earliest_observed_evidence_is_the_originating_signal(db):
    """The chain starts with the signal that started it, not the latest one."""
    first = add_evidence(db, reference="TEST-C061wynd", observed_days_ago=200)
    add_evidence(db, reference="TEST-C062wynd", observed_days_ago=5)
    owner = user_id(db, "analyst@crown.local")
    oid = opportunity.refresh(db, owner)[0].opportunity_id
    matching.rank(db, oid)
    match_id = db.execute(
        "SELECT id FROM match_result WHERE NOT is_excluded ORDER BY total_score DESC LIMIT 1"
    ).fetchone()[0]
    approver = user_id(db, "compliance@crown.local")
    approval_id = approval.decide(db, match_id, "APPROVED", "ok", approver, "COMPLIANCE")

    attribution_id = attribution.progress(db, approval_id)
    assert db.execute("SELECT originating_evidence_id FROM attribution WHERE id = %s",
                      (attribution_id,)).fetchone()[0] == first


def test_a_rejected_match_never_produces_an_attribution(db):
    add_evidence(db, reference="TEST-C063wynd")
    owner = user_id(db, "analyst@crown.local")
    oid = opportunity.refresh(db, owner)[0].opportunity_id
    matching.rank(db, oid)
    match_id = db.execute(
        "SELECT id FROM match_result WHERE NOT is_excluded LIMIT 1").fetchone()[0]
    approver = user_id(db, "compliance@crown.local")
    approval_id = approval.decide(db, match_id, "REJECTED", "not for us",
                                  approver, "COMPLIANCE")

    with pytest.raises(attribution.NotApproved, match="REJECTED"):
        attribution.progress(db, approval_id)
    assert db.execute("SELECT count(*) FROM attribution").fetchone()[0] == 0


def test_the_trace_is_rendered_for_a_human(client, db):
    from tests.conftest import sign_in
    _, approval_id = a_full_chain(db)
    attribution_id = attribution.progress(db, approval_id)
    db.commit()

    sign_in(client, "analyst@crown.local")
    page = client.get(f"/attribution/{attribution_id}").get_data(as_text=True)
    assert "TEST-C060wynd" in page
    assert "https://www.planning.vic.gov.au/amendment/TEST-C060wynd" in page
    assert "VIC_PLANNING_AMENDMENTS" in page
