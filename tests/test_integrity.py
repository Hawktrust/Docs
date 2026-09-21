"""The five defects found reviewing the thin loop, each reproduced.

Every test here failed before migration 0004 and the accompanying code changes.
They are kept as regressions rather than deleted, because each one was reachable
from ordinary use — a double-clicked button, a re-ranked opportunity, an
amendment edited upstream.
"""
import psycopg
import pytest

from crown import approval, attribution, matching, opportunity
from crown import db as crown_db
from tests.conftest import add_evidence, csrf, sign_in, user_id


def a_decided_match(db):
    add_evidence(db, reference="TEST-INT-1")
    owner = user_id(db, "analyst@crown.local")
    oid = opportunity.refresh(db, owner)[0].opportunity_id
    matching.rank(db, oid)
    match_id, score = db.execute(
        """SELECT id, total_score FROM match_result WHERE NOT is_excluded
           ORDER BY total_score DESC LIMIT 1""").fetchone()
    approver = user_id(db, "compliance@crown.local")
    approval_id = approval.decide(db, match_id, "APPROVED", "checked",
                                  approver, "COMPLIANCE")
    db.commit()          # the first decision is real; a later rollback must not undo it
    return oid, match_id, approval_id, score


# ------------------------------------------------------------------ defect 1

def test_the_real_mandate_view_does_not_bypass_row_level_security(app_db, db):
    """A view runs as its owner unless told otherwise.

    buyer_mandate_real is the view the schema tells you to use for any figure
    shown to a person, and it was the one path that ignored the policies on the
    table underneath it.
    """
    db.execute(
        """INSERT INTO buyer_mandate (buyer_label, origin, geographies, asset_types,
               mandate_date)
           VALUES ('a real mandate','REAL','{Wyndham}','{RESIDENTIAL_LAND}','2026-08-01')""")
    db.commit()

    crown_db.clear_identity(app_db)
    assert app_db.execute("SELECT count(*) FROM buyer_mandate").fetchone()[0] == 0
    assert app_db.execute("SELECT count(*) FROM buyer_mandate_real").fetchone()[0] == 0

    crown_db.set_identity(app_db, "", "ANALYST")
    assert app_db.execute("SELECT count(*) FROM buyer_mandate_real").fetchone()[0] == 1


def test_the_view_is_declared_security_invoker(db):
    options = db.execute(
        "SELECT reloptions FROM pg_class WHERE relname = 'buyer_mandate_real'").fetchone()[0]
    assert options and any("security_invoker=true" in o for o in options), options


# ------------------------------------------------------------ defects 2 and 3

def test_a_match_cannot_be_approved_twice(db):
    """A double-clicked Approve button was enough to create two decisions."""
    _, match_id, _, _ = a_decided_match(db)
    approver = user_id(db, "compliance@crown.local")

    with pytest.raises(psycopg.errors.UniqueViolation):
        approval.decide(db, match_id, "APPROVED", "second click", approver, "COMPLIANCE")
    db.rollback()

    assert db.execute("SELECT count(*) FROM approval").fetchone()[0] == 1


def test_one_approval_produces_at_most_one_attribution(db):
    """Attribution is append-only, so a duplicate could never be removed."""
    _, _, approval_id, _ = a_decided_match(db)
    attribution.progress(db, approval_id)
    db.commit()

    with pytest.raises(psycopg.errors.UniqueViolation):
        attribution.progress(db, approval_id)
    db.rollback()

    assert db.execute("SELECT count(*) FROM attribution").fetchone()[0] == 1


def test_double_submitting_the_decision_form_does_not_double_decide(client, db):
    """The same defect through the door a person actually uses."""
    add_evidence(db, reference="TEST-INT-2")
    owner = user_id(db, "analyst@crown.local")
    oid = opportunity.refresh(db, owner)[0].opportunity_id
    matching.rank(db, oid)
    db.commit()
    match_id = db.execute(
        "SELECT id FROM match_result WHERE NOT is_excluded LIMIT 1").fetchone()[0]

    sign_in(client, "compliance@crown.local")
    token = csrf(client)
    first = client.post(f"/queue/{match_id}/decide",
                        data={"decision": "APPROVED", "reason": "checked", **token})
    assert first.status_code == 302

    second = client.post(f"/queue/{match_id}/decide",
                         data={"decision": "APPROVED", "reason": "checked again", **token})
    assert second.status_code >= 400

    assert db.execute("SELECT count(*) FROM approval").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM attribution").fetchone()[0] == 1


# ------------------------------------------------------------------ defect 4

def test_an_approved_match_keeps_the_numbers_its_approver_saw(db):
    """Recomputing rewrote match_result in place, under the approval."""
    oid, match_id, _, score_at_approval = a_decided_match(db)

    # a mandate is edited, and the ranking is recomputed
    db.execute(
        """UPDATE buyer_mandate SET mandate_date = '2024-01-01'
           WHERE id = (SELECT buyer_mandate_id FROM match_result WHERE id = %s)""",
        (match_id,))
    matching.rank(db, oid)

    after = db.execute(
        "SELECT total_score FROM match_result WHERE id = %s", (match_id,)).fetchone()[0]
    assert after == score_at_approval


def test_recomputing_still_rescores_everything_undecided(db):
    """Freezing decided matches must not freeze the rest of the board."""
    oid, match_id, _, _ = a_decided_match(db)
    others_before = dict(db.execute(
        "SELECT id, total_score FROM match_result WHERE id <> %s", (match_id,)).fetchall())

    db.execute("UPDATE match_weight_config SET is_active = false WHERE version = 1")
    db.execute(
        """INSERT INTO match_weight_config (version, geographic_fit, asset_fit,
               price_fit, size_fit, mandate_freshness, is_active)
           VALUES (2, 0.050, 0.200, 0.200, 0.150, 0.900, true)""")
    matching.rank(db, oid)

    others_after = dict(db.execute(
        """SELECT id, total_score FROM match_result
           WHERE id <> %s AND weight_config_version = 2""", (match_id,)).fetchall())
    assert others_after, "no undecided match was rescored under the new weights"


def test_the_database_refuses_the_rescore_even_if_code_forgets(db):
    """The application skips decided rows; this is the backstop."""
    _, match_id, _, _ = a_decided_match(db)
    with pytest.raises(psycopg.errors.RaiseException, match="cannot be rescored"):
        db.execute("UPDATE match_result SET total_score = 0.99 WHERE id = %s", (match_id,))
    db.rollback()


# ------------------------------------------------------------------ defect 5

def test_one_amendment_revised_twice_is_still_one_amendment(db):
    """Ingestion writes a new evidence record when a payload changes upstream.

    Counting those revisions as separate amendments escalated an opportunity
    from DEVELOPING to HIGH_CONFIDENCE because a council edited a page.
    """
    add_evidence(db, reference="C999wynd", evidence_class="HYPOTHESIS",
                 status="EXHIBITED", suburb="Tarneit")
    add_evidence(db, reference="C999wynd", evidence_class="HYPOTHESIS",
                 status="EXHIBITED", suburb="Tarneit")
    owner = user_id(db, "analyst@crown.local")

    change = opportunity.refresh(db, owner)[0]
    assert change.stage == "DEVELOPING"
    assert len(change.evidence_ids) == 2      # both records are still linked


def test_two_genuinely_different_amendments_do_escalate(db):
    add_evidence(db, reference="C001wynd", evidence_class="HYPOTHESIS",
                 status="EXHIBITED", suburb="Tarneit")
    add_evidence(db, reference="C002wynd", evidence_class="HYPOTHESIS",
                 status="EXHIBITED", suburb="Tarneit")
    owner = user_id(db, "analyst@crown.local")
    assert opportunity.refresh(db, owner)[0].stage == "HIGH_CONFIDENCE"


def test_a_later_gazettal_of_the_same_amendment_wins(db):
    """The strongest class for an amendment is the one that counts."""
    add_evidence(db, reference="C003wynd", evidence_class="HYPOTHESIS",
                 status="EXHIBITED", suburb="Tarneit")
    add_evidence(db, reference="C003wynd", evidence_class="FACT",
                 status="GAZETTED", suburb="Tarneit")
    owner = user_id(db, "analyst@crown.local")
    assert opportunity.refresh(db, owner)[0].stage == "CONFIRMED"
