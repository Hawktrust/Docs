"""Acceptance criterion 10: the audit table is append-only, and an attempted
update or delete from application code fails."""
import psycopg
import pytest

from crown import audit, db as crown_db
from tests.conftest import user_id


def an_audit_row(conn):
    correlation = audit.new_correlation_id()
    audit.write(conn, correlation, "TEST_ACTION", "app_user", "some-id",
                new_state={"k": "v"}, actor_agent="tests")
    return correlation


def test_application_code_cannot_update_an_audit_row(app_db, db):
    an_audit_row(db)
    db.commit()
    crown_db.set_identity(app_db, str(user_id(db, "hawk@crown.local")), "ADMIN")

    with pytest.raises(psycopg.Error):
        app_db.execute("UPDATE audit_event SET action = 'TAMPERED'")
    app_db.rollback()

    assert db.execute(
        "SELECT count(*) FROM audit_event WHERE action = 'TEST_ACTION'").fetchone()[0] == 1


def test_application_code_cannot_delete_an_audit_row(app_db, db):
    an_audit_row(db)
    db.commit()
    crown_db.set_identity(app_db, str(user_id(db, "hawk@crown.local")), "ADMIN")

    before = db.execute("SELECT count(*) FROM audit_event").fetchone()[0]

    with pytest.raises(psycopg.Error):
        app_db.execute("DELETE FROM audit_event")
    app_db.rollback()

    assert db.execute("SELECT count(*) FROM audit_event").fetchone()[0] == before


def test_the_trigger_refuses_even_the_table_owner(db):
    """Privileges alone would leave the owner free. The trigger does not."""
    an_audit_row(db)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db.execute("UPDATE audit_event SET action = 'TAMPERED'")
    db.rollback()

    an_audit_row(db)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db.execute("DELETE FROM audit_event")
    db.rollback()

    an_audit_row(db)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db.execute("TRUNCATE audit_event")
    db.rollback()


def test_attribution_is_append_only_too(db):
    from crown import approval, attribution, matching, opportunity
    from tests.conftest import add_evidence

    add_evidence(db, reference="TEST-C040wynd")
    owner = user_id(db, "analyst@crown.local")
    oid = opportunity.refresh(db, owner)[0].opportunity_id
    matching.rank(db, oid)
    match_id = db.execute(
        "SELECT id FROM match_result WHERE NOT is_excluded ORDER BY total_score DESC LIMIT 1"
    ).fetchone()[0]
    approver = user_id(db, "compliance@crown.local")
    approval_id = approval.decide(db, match_id, "APPROVED", "ok", approver, "COMPLIANCE")
    attribution.progress(db, approval_id)

    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db.execute("UPDATE attribution SET originating_source_url = 'https://tampered'")
    db.rollback()


def test_every_transition_in_the_loop_writes_an_audit_row(db):
    """Ticket item 8: every state transition in items 1-7 writes one row."""
    from crown import approval, attribution, matching, opportunity, outbound
    from tests.conftest import add_evidence

    add_evidence(db, reference="TEST-C041wynd")
    owner = user_id(db, "analyst@crown.local")
    oid = opportunity.refresh(db, owner)[0].opportunity_id
    matching.rank(db, oid, actor_user_id=owner)
    match_id = db.execute(
        "SELECT id FROM match_result WHERE NOT is_excluded ORDER BY total_score DESC LIMIT 1"
    ).fetchone()[0]
    approver = user_id(db, "compliance@crown.local")
    approval_id = approval.decide(db, match_id, "APPROVED", "ok", approver, "COMPLIANCE")
    attribution.progress(db, approval_id)
    outbound.create(db, approval_id, "BUYER_BRIEF", {"body": "x"}, approver)

    actions = {r[0] for r in db.execute("SELECT action FROM audit_event").fetchall()}
    assert {"OPPORTUNITY_CREATED", "MATCHES_COMPUTED", "MATCH_APPROVED",
            "ATTRIBUTION_WRITTEN", "OUTBOUND_CREATED"} <= actions

    # every row carries a correlation id, so one action's rows can be found together
    assert db.execute(
        "SELECT count(*) FROM audit_event WHERE correlation_id IS NULL").fetchone()[0] == 0
