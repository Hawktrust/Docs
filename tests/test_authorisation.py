"""Acceptance criterion 9: authorisation is enforced server-side.

A request carrying a forged role header is rejected. The tests below forge the
header in every way a client could and show it changes nothing, at both layers:
the HTTP surface and row-level security in the database.
"""
import psycopg
import pytest

from crown import auth, db as crown_db
from tests.conftest import add_evidence, sign_in, user_id

FORGED = {h: "ADMIN" for h in auth.IGNORED_ROLE_HEADERS}


def a_match(db):
    """Set up one scored, undecided match and return its id."""
    from crown import matching, opportunity
    add_evidence(db, reference="TEST-C020wynd")
    owner = user_id(db, "analyst@crown.local")
    oid = opportunity.refresh(db, owner)[0].opportunity_id
    matching.rank(db, oid)
    db.commit()
    return db.execute(
        "SELECT id FROM match_result WHERE NOT is_excluded ORDER BY total_score DESC LIMIT 1"
    ).fetchone()[0]


def test_unauthenticated_request_with_a_forged_admin_header_is_rejected(client, db):
    match_id = a_match(db)
    response = client.post(f"/queue/{match_id}/decide",
                           data={"decision": "APPROVED", "reason": "forged"},
                           headers=FORGED)
    assert response.status_code == 401


def test_analyst_with_a_forged_admin_header_cannot_approve(client, db):
    """The header says ADMIN. The database says ANALYST. The database wins."""
    match_id = a_match(db)
    sign_in(client, "analyst@crown.local")

    response = client.post(f"/queue/{match_id}/decide",
                           data={"decision": "APPROVED", "reason": "forged"},
                           headers=FORGED)
    assert response.status_code == 403
    assert db.execute("SELECT count(*) FROM approval").fetchone()[0] == 0


def test_a_forged_header_does_not_change_the_role_the_server_reports(client, db):
    sign_in(client, "analyst@crown.local")
    page = client.get("/opportunities", headers=FORGED).get_data(as_text=True)
    assert "ANALYST" in page
    assert "· ADMIN" not in page


def test_compliance_may_approve(client, db):
    """The same request, from a role that is actually allowed, succeeds."""
    match_id = a_match(db)
    sign_in(client, "compliance@crown.local")
    response = client.post(f"/queue/{match_id}/decide",
                           data={"decision": "APPROVED", "reason": "evidence checked"})
    assert response.status_code == 302
    assert db.execute("SELECT count(*) FROM approval").fetchone()[0] == 1


def test_row_level_security_rejects_a_forged_role_at_the_database(app_db, db):
    """Below HTTP: even a caller who can set the session variable directly is
    constrained, because the policy is evaluated by the database."""
    match_id = a_match(db)
    approver = user_id(db, "analyst@crown.local")

    crown_db.set_identity(app_db, str(approver), "ANALYST")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_db.execute(
            """INSERT INTO approval (match_result_id, decision, reason, approver_id)
               VALUES (%s,'APPROVED','analyst should not be able to do this',%s)""",
            (match_id, approver),
        )
    app_db.rollback()


def test_a_connection_with_no_identity_sees_nothing(app_db, db):
    a_match(db)
    crown_db.clear_identity(app_db)
    assert app_db.execute("SELECT count(*) FROM opportunity").fetchone()[0] == 0
    assert app_db.execute("SELECT count(*) FROM buyer_mandate").fetchone()[0] == 0
    assert app_db.execute("SELECT count(*) FROM match_result").fetchone()[0] == 0


def test_rls_applies_to_the_application_role_even_though_policies_exist(app_db, db):
    """Migration 0002 sets FORCE ROW LEVEL SECURITY. Without it, a role that
    owned these tables would bypass every policy above."""
    forced = dict(db.execute(
        """SELECT relname, relforcerowsecurity FROM pg_class
           WHERE relname IN ('opportunity','buyer_mandate','match_result',
                             'approval','outbound_artifact','attribution')"""
    ).fetchall())
    assert all(forced.values()), forced


def test_the_role_is_read_from_the_database_not_the_session_cookie(client, db):
    """A role revoked in the database takes effect on the next request."""
    match_id = a_match(db)
    sign_in(client, "compliance@crown.local")

    db.execute("UPDATE app_user SET is_active = false WHERE email = 'compliance@crown.local'")
    db.commit()

    response = client.post(f"/queue/{match_id}/decide",
                           data={"decision": "APPROVED", "reason": "should not land"})
    assert response.status_code == 401
    assert db.execute("SELECT count(*) FROM approval").fetchone()[0] == 0
