"""The controls the prospecting product needs, from docs/PRODUCT-REVIEW.md.

Four things the vision described and had no mechanism for: a person who asked
not to be contacted, Crown sitting on three sides of one deal, an automatic
Acquire bypassing the approval gate, and a brief citing evidence that has since
changed.
"""
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from crown import approval, matching, opportunity, outbound, recommendation, suppression
from tests.conftest import add_evidence, user_id


def approved(db, *, principal="CLIENT", label="Client A", reference="TEST-PC-1",
             suburb="Tarneit", evidence_class="FACT",
             retrieval_method="DIRECT_FETCH"):
    evidence_id = add_evidence(db, reference=reference, suburb=suburb,
                               evidence_class=evidence_class, origin="REAL")
    if retrieval_method == "OPERATOR_CAPTURE":
        # 0006: a capture names who took it and keeps what they took, and may
        # be STRONG but never AUTHORITATIVE.
        db.execute(
            """UPDATE evidence_record
               SET retrieval_method = %s, reliability = 'STRONG',
                   captured_by = %s, capture_sha256 = repeat('a', 64)
               WHERE id = %s""",
            (retrieval_method, user_id(db, "hawk@crown.local"), evidence_id))
    else:
        db.execute("UPDATE evidence_record SET retrieval_method = %s WHERE id = %s",
                   (retrieval_method, evidence_id))
    owner = user_id(db, "analyst@crown.local")
    oid = opportunity.refresh(db, owner)[0].opportunity_id
    db.execute("UPDATE opportunity SET principal = %s, principal_label = %s WHERE id = %s",
               (principal, label, oid))
    matching.rank(db, oid)
    match_id = db.execute(
        """SELECT id FROM match_result WHERE opportunity_id = %s AND NOT is_excluded
           ORDER BY total_score DESC LIMIT 1""", (oid,)).fetchone()[0]
    approver = user_id(db, "compliance@crown.local")
    approval_id = approval.decide(db, match_id, "APPROVED", "pack checked",
                                  approver, "COMPLIANCE")
    return oid, approval_id


# ------------------------------------------------------------- do not contact

def test_a_suppressed_person_is_not_contacted_whatever_the_approval_says(db):
    """An approval permits an action. It does not override a person's request."""
    _, approval_id = approved(db)
    recorder = user_id(db, "compliance@crown.local")
    suppression.record(db, scope="PERSON", identifier="A. Landholder",
                       reason="asked by phone not to be contacted again",
                       requested_at=datetime.now(timezone.utc), recorded_by=recorder,
                       source_of_request="PHONE")

    with pytest.raises(suppression.Suppressed, match="asked not to be contacted"):
        outbound.create(db, approval_id, "OUTREACH_DRAFT", {"body": "hello"},
                        recorder, contact={"PERSON": "A. Landholder"})
    assert db.execute("SELECT count(*) FROM outbound_artifact").fetchone()[0] == 0


def test_suppression_matching_is_blunt_on_purpose(db):
    """A near miss should suppress. Case and spacing must not defeat a request."""
    recorder = user_id(db, "compliance@crown.local")
    suppression.record(db, scope="PERSON", identifier="A. Landholder",
                       reason="opted out", requested_at=datetime.now(timezone.utc),
                       recorded_by=recorder, source_of_request="OPT_OUT_LINK")

    for variant in ("a. landholder", "  A. Landholder  ", "A.  LANDHOLDER"):
        assert suppression.check(db, {"PERSON": variant})


def test_suppressing_a_person_is_not_defeated_by_addressing_the_company(db):
    """Everything known about a target is checked, not just the field used."""
    _, approval_id = approved(db)
    recorder = user_id(db, "compliance@crown.local")
    suppression.record(db, scope="ORGANISATION", identifier="Landholder Pty Ltd",
                       reason="legal request", requested_at=datetime.now(timezone.utc),
                       recorded_by=recorder, source_of_request="LEGAL")

    with pytest.raises(suppression.Suppressed):
        outbound.create(db, approval_id, "OUTREACH_DRAFT", {}, recorder,
                        contact={"PERSON": "Someone Else",
                                 "ORGANISATION": "Landholder Pty Ltd"})


def test_an_unsuppressed_target_still_goes_out(db):
    from tests.test_optout import an_identity

    _, approval_id = approved(db)
    an_identity(db)                       # 0016: a message names who sent it
    creator = user_id(db, "compliance@crown.local")
    artifact_id = outbound.create(db, approval_id, "OUTREACH_DRAFT", {"body": "hi"},
                                  creator, contact={"PERSON": "Nobody Suppressed"})
    assert artifact_id is not None


def test_a_suppression_is_never_deleted_only_released(db):
    recorder = user_id(db, "compliance@crown.local")
    sid = suppression.record(db, scope="PERSON", identifier="B. Person",
                             reason="opted out",
                             requested_at=datetime.now(timezone.utc),
                             recorded_by=recorder, source_of_request="EMAIL")
    suppression.release(db, sid, released_by=recorder,
                        reason="opted back in, in writing, 2026-09-19")

    assert suppression.check(db, {"PERSON": "B. Person"}) == []
    # the original request is still on the record
    row = db.execute(
        """SELECT reason, released_reason, released_by FROM contact_suppression
           WHERE id = %s""", (sid,)).fetchone()
    assert row[0] == "opted out" and "opted back in" in row[1] and row[2] == recorder


def test_a_release_must_be_explained(db):
    recorder = user_id(db, "compliance@crown.local")
    sid = suppression.record(db, scope="PERSON", identifier="C. Person",
                             reason="opted out",
                             requested_at=datetime.now(timezone.utc),
                             recorded_by=recorder, source_of_request="EMAIL")
    with pytest.raises(psycopg.errors.CheckViolation, match="release_is_explained"):
        db.execute("UPDATE contact_suppression SET released_at = now() WHERE id = %s",
                   (sid,))
    db.rollback()


def test_suppression_is_audited(db):
    recorder = user_id(db, "compliance@crown.local")
    suppression.record(db, scope="ADDRESS", identifier="1 Example St",
                       reason="opted out", requested_at=datetime.now(timezone.utc),
                       recorded_by=recorder, source_of_request="OPT_OUT_LINK")
    assert db.execute(
        "SELECT count(*) FROM audit_event WHERE action = 'CONTACT_SUPPRESSED'"
    ).fetchone()[0] == 1


# ------------------------------------------------- three sides of one deal

def test_the_same_parcel_for_two_principals_stops_outbound(db):
    """Crown's own book and a client's mandate on one geography is a conflict,
    and it is disclosed before anything goes out or it does not go out."""
    _, approval_id = approved(db, principal="CLIENT", label="Client A")

    # the same geography, being worked for Crown itself
    db.execute(
        """INSERT INTO opportunity (lga, geography_label, stage, stage_rule,
                   owner_user_id, principal, principal_label)
           SELECT lga, geography_label, stage, stage_rule, owner_user_id,
                  'CROWN_OWN_BOOK', 'Crown Capital'
           FROM opportunity LIMIT 1""")

    with pytest.raises(outbound.ConflictNotDisclosed, match="different principal"):
        outbound.create(db, approval_id, "IC_BRIEF", {}, user_id(db, "hawk@crown.local"))


def test_a_recorded_disclosure_lets_it_proceed(db):
    oid, approval_id = approved(db, principal="CLIENT", label="Client A")
    other = db.execute(
        """INSERT INTO opportunity (lga, geography_label, stage, stage_rule,
                   owner_user_id, principal, principal_label)
           SELECT lga, geography_label, stage, stage_rule, owner_user_id,
                  'CROWN_OWN_BOOK', 'Crown Capital'
           FROM opportunity WHERE id = %s RETURNING id""", (oid,)).fetchone()[0]

    db.execute(
        """INSERT INTO conflict_disclosure (opportunity_id, competing_opportunity_id,
                   disclosed_by, disclosure)
           VALUES (%s,%s,%s,%s)""",
        (oid, other, user_id(db, "hawk@crown.local"),
         "Client A informed in writing 2026-09-20 that Crown also holds an interest"))

    assert outbound.create(db, approval_id, "IC_BRIEF", {},
                           user_id(db, "hawk@crown.local")) is not None


def test_the_same_principal_on_one_parcel_is_not_a_conflict(db):
    oid, approval_id = approved(db, principal="CLIENT", label="Client A")
    db.execute(
        """INSERT INTO opportunity (lga, geography_label, stage, stage_rule,
                   owner_user_id, principal, principal_label)
           SELECT lga, geography_label, stage, stage_rule, owner_user_id,
                  'CLIENT', 'Client A'
           FROM opportunity WHERE id = %s""", (oid,))
    assert outbound.create(db, approval_id, "IC_BRIEF", {},
                           user_id(db, "hawk@crown.local")) is not None


# ------------------------------------------------------- recommendations

def test_a_recommendation_needs_an_approval(db):
    """Constitution §4. An Acquire reaching a client is consequential."""
    with pytest.raises(recommendation.NotApproved):
        recommendation.create(
            db, approval_id="00000000-0000-0000-0000-000000000000",
            decision="ACQUIRE", strategy="land bank", timing="IMMEDIATE",
            rationale="x", created_by=user_id(db, "analyst@crown.local"))


def test_a_rejected_match_produces_no_recommendation(db):
    _, approval_id = approved(db)
    db.execute("UPDATE approval SET decision = 'REJECTED' WHERE id = %s", (approval_id,))
    with pytest.raises(recommendation.NotApproved, match="REJECTED"):
        recommendation.create(
            db, approval_id=approval_id, decision="ACQUIRE", strategy="land bank",
            timing="IMMEDIATE", rationale="x",
            created_by=user_id(db, "analyst@crown.local"))


def test_a_recommendation_needs_a_principal(db):
    """It is made for somebody, and which one has to be recorded first."""
    oid, approval_id = approved(db)
    db.execute("UPDATE opportunity SET principal = NULL WHERE id = %s", (oid,))
    with pytest.raises(recommendation.NotApproved, match="no principal"):
        recommendation.create(
            db, approval_id=approval_id, decision="WATCH", strategy="monitor",
            timing="LONG_TERM", rationale="x",
            created_by=user_id(db, "analyst@crown.local"))


def test_confidence_is_derived_from_the_evidence_not_typed_in(db):
    """A separately maintained confidence field drifts from the evidence
    classification and then contradicts it in front of a client."""
    cases = {
        ("FACT", "DIRECT_FETCH"): "CONFIRMED",
        ("FACT", "OPERATOR_CAPTURE"): "PROBABLE",
        ("HYPOTHESIS", "DIRECT_FETCH"): "PROBABLE",
        ("HYPOTHESIS", "OPERATOR_CAPTURE"): "SPECULATIVE",
    }
    for (evidence_class, method), expected in cases.items():
        line = recommendation.EvidenceLine(
            "id", "C1", evidence_class, "STRONG", method, "https://x",
            datetime.now(timezone.utc), datetime.now(timezone.utc))
        assert recommendation.confidence_from([line]) == expected, (evidence_class, method)

    assert recommendation.confidence_from([]) == "SPECULATIVE"


def test_a_relayed_lead_can_never_produce_a_confirmed_recommendation(db):
    """Migration 0003 already forbids relayed evidence from being a FACT, so the
    strongest a relay-only opportunity reaches is SPECULATIVE."""
    line = recommendation.EvidenceLine(
        "id", "C1", "UNKNOWN", "WEAK", "SEARCH_RELAY", "https://x",
        datetime.now(timezone.utc), datetime.now(timezone.utc))
    assert recommendation.confidence_from([line]) == "SPECULATIVE"


def test_a_recommendation_snapshots_what_it_rested_on(db):
    """Six months later the zoning has changed. The brief must still show what
    was known when it was written."""
    _, approval_id = approved(db, reference="TEST-PC-SNAP")
    rec_id = recommendation.create(
        db, approval_id=approval_id, decision="ACQUIRE", strategy="planning uplift",
        timing="ONE_TO_THREE_YEARS", rationale="gazetted rezoning in the precinct",
        created_by=user_id(db, "analyst@crown.local"))

    stored = db.execute(
        "SELECT confidence::text, evidence_snapshot FROM recommendation WHERE id = %s",
        (rec_id,)).fetchone()
    assert stored[0] == "CONFIRMED"
    snap = stored[1]
    assert snap["evidence"][0]["reference"] == "TEST-PC-SNAP"
    assert snap["evidence"][0]["retrieval_method"] == "DIRECT_FETCH"
    assert snap["confidence_rule"].startswith("CONFIRMED when")

    # the evidence changes afterwards; the snapshot does not
    db.execute("UPDATE evidence_record SET amendment_status = 'SUPERSEDED'")
    unchanged = db.execute(
        "SELECT evidence_snapshot FROM recommendation WHERE id = %s", (rec_id,)
    ).fetchone()[0]
    assert unchanged == snap


def test_economics_cannot_be_published_without_their_assumptions(db):
    """A residual land value moves enormously on a small change to a sales rate."""
    _, approval_id = approved(db)
    with pytest.raises(ValueError, match="assumptions"):
        recommendation.create(
            db, approval_id=approval_id, decision="ACQUIRE", strategy="subdivision",
            timing="IMMEDIATE", rationale="x",
            economics={"residual_land_value_aud": 14_500_000},
            created_by=user_id(db, "analyst@crown.local"))


def test_the_database_refuses_economics_without_assumptions_too(db):
    _, approval_id = approved(db)
    with pytest.raises(psycopg.errors.CheckViolation,
                       match="economics_ship_with_assumptions"):
        db.execute(
            """INSERT INTO recommendation (opportunity_id, approval_id, principal,
                       principal_label, decision, strategy, timing, confidence,
                       rationale, economics, evidence_snapshot, created_by)
               SELECT m.opportunity_id, a.id, 'CLIENT', 'Client A', 'ACQUIRE',
                      'subdivision', 'IMMEDIATE', 'CONFIRMED', 'x',
                      '{"rlv": 1}'::jsonb, '{}'::jsonb, %s
               FROM approval a JOIN match_result m ON m.id = a.match_result_id
               WHERE a.id = %s""",
            (user_id(db, "analyst@crown.local"), approval_id))
    db.rollback()


def test_a_recommendation_is_permanent(db):
    _, approval_id = approved(db)
    rec_id = recommendation.create(
        db, approval_id=approval_id, decision="WATCH", strategy="monitor",
        timing="LONG_TERM", rationale="watching the PSP",
        created_by=user_id(db, "analyst@crown.local"))

    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db.execute("UPDATE recommendation SET decision = 'ACQUIRE' WHERE id = %s",
                   (rec_id,))
    db.rollback()


def test_one_approval_produces_one_recommendation(db):
    _, approval_id = approved(db)
    kwargs = dict(decision="WATCH", strategy="monitor", timing="LONG_TERM",
                  rationale="x", created_by=user_id(db, "analyst@crown.local"))
    recommendation.create(db, approval_id=approval_id, **kwargs)
    db.commit()
    with pytest.raises(psycopg.errors.UniqueViolation):
        recommendation.create(db, approval_id=approval_id, **kwargs)
    db.rollback()
