"""Ticket item 3 and acceptance criterion 4."""
from crown import db as crown_db
from crown import opportunity
from tests.conftest import add_evidence, user_id


def test_stage_rule_is_readable_and_covers_every_stage():
    assert opportunity.stage_for(["FACT"])[0] == "CONFIRMED"
    assert opportunity.stage_for(["HYPOTHESIS", "HYPOTHESIS"])[0] == "HIGH_CONFIDENCE"
    assert opportunity.stage_for(["HYPOTHESIS"])[0] == "DEVELOPING"
    assert opportunity.stage_for(["UNKNOWN"])[0] == "WATCH"
    # a gazetted amendment outranks any number of exhibited ones
    assert opportunity.stage_for(["HYPOTHESIS", "HYPOTHESIS", "FACT"])[0] == "CONFIRMED"


def test_every_stage_carries_the_reason_it_is_at_that_stage():
    for classes in (["FACT"], ["HYPOTHESIS", "HYPOTHESIS"], ["HYPOTHESIS"], []):
        stage, reason = opportunity.stage_for(classes)
        assert reason and len(reason) > 20, f"{stage} has no readable reason"


def test_opportunity_is_created_with_evidence_and_a_named_human_owner(db):
    """AC4: an opportunity linked to a real evidence record, with a named owner."""
    evidence_id = add_evidence(db, reference="TEST-C010wynd")
    owner = user_id(db, "analyst@crown.local")

    changes = opportunity.refresh(db, owner)
    assert len(changes) == 1
    change = changes[0]
    assert change.created and change.stage == "CONFIRMED"
    assert evidence_id in change.evidence_ids

    row = db.execute(
        """SELECT o.geography_label, o.stage::text, o.stage_rule, u.display_name,
                  (SELECT count(*) FROM opportunity_evidence oe WHERE oe.opportunity_id = o.id)
           FROM opportunity o JOIN app_user u ON u.id = o.owner_user_id"""
    ).fetchone()
    assert row[0] == "Tarneit"
    assert row[1] == "CONFIRMED"
    assert "gazetted" in row[2]
    assert row[3] == "Crown Analyst"   # a named human, not a system account
    assert row[4] == 1


def test_rerunning_the_rule_restages_rather_than_duplicating(db):
    owner = user_id(db, "analyst@crown.local")
    add_evidence(db, reference="TEST-C011wynd", evidence_class="HYPOTHESIS",
                 status="EXHIBITED")
    first = opportunity.refresh(db, owner)
    assert first[0].stage == "DEVELOPING"

    # a second exhibited amendment in the same geography moves the stage on
    add_evidence(db, reference="TEST-C012wynd", evidence_class="HYPOTHESIS",
                 status="EXHIBITED")
    second = opportunity.refresh(db, owner)
    assert second[0].stage == "HIGH_CONFIDENCE"
    assert not second[0].created

    assert db.execute("SELECT count(*) FROM opportunity").fetchone()[0] == 1
    # the restaging is on the record
    actions = [r[0] for r in db.execute(
        "SELECT action FROM audit_event ORDER BY id").fetchall()]
    assert "OPPORTUNITY_CREATED" in actions and "OPPORTUNITY_RESTAGED" in actions


def test_opportunities_are_geographic_not_parcel_level(db):
    """Ticket item 3: no parcel or owner resolution. Two amendments naming the
    same suburb make one opportunity, not two."""
    owner = user_id(db, "analyst@crown.local")
    add_evidence(db, reference="TEST-C013wynd", suburb="Tarneit")
    add_evidence(db, reference="TEST-C014wynd", suburb="Tarneit")
    changes = opportunity.refresh(db, owner)
    assert len(changes) == 1
    assert len(changes[0].evidence_ids) == 2
