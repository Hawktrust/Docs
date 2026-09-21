"""Acceptance criterion 8: an export or outreach draft without an approval id
fails, server-side."""
import psycopg
import pytest

from crown import approval, matching, opportunity, outbound
from tests.conftest import approved_match, csrf, sign_in, user_id
from tests.test_optout import an_identity

# An OUTREACH_DRAFT is a message to a person, so since 0016 it needs somebody to
# be addressed to. Every draft below carries one.
TO = {"PERSON": "A. Landholder"}


def test_no_approval_id_is_refused_before_the_database_is_asked(db):
    creator = user_id(db, "agent@crown.local")
    with pytest.raises(outbound.ApprovalRequired, match="needs a stored approval id"):
        outbound.create(db, None, "EXPORT", {"rows": []}, creator)
    assert db.execute("SELECT count(*) FROM outbound_artifact").fetchone()[0] == 0


def test_an_empty_approval_id_is_refused(db):
    creator = user_id(db, "agent@crown.local")
    with pytest.raises(outbound.ApprovalRequired):
        outbound.create(db, "  ", "OUTREACH_DRAFT", {}, creator)


def test_an_approval_id_that_does_not_exist_is_refused(db):
    creator = user_id(db, "agent@crown.local")
    with pytest.raises(outbound.ApprovalRequired, match="does not exist"):
        outbound.create(db, "00000000-0000-0000-0000-000000000000", "EXPORT", {}, creator)


def test_a_rejected_approval_produces_nothing(db):
    """An approval id alone is not enough: it has to say APPROVED."""
    approval_id, creator = approved_match(db, decision="REJECTED")
    with pytest.raises(outbound.ApprovalRequired, match="REJECTED"):
        outbound.create(db, approval_id, "OUTREACH_DRAFT", {}, creator, contact=TO)
    assert db.execute("SELECT count(*) FROM outbound_artifact").fetchone()[0] == 0


def test_an_approved_match_does_produce_an_artifact(db):
    an_identity(db)
    approval_id, creator = approved_match(db)
    artifact_id = outbound.create(db, approval_id, "OUTREACH_DRAFT",
                                  {"body": "draft"}, creator, contact=TO)
    row = db.execute(
        "SELECT approval_id, artifact_type FROM outbound_artifact WHERE id = %s",
        (artifact_id,)).fetchone()
    assert str(row[0]) == str(approval_id) and row[1] == "OUTREACH_DRAFT"


def test_the_database_refuses_an_artifact_with_no_approval_even_if_code_is_bypassed(db):
    """The application gate is the first control; the NOT NULL is the backstop."""
    creator = user_id(db, "agent@crown.local")
    with pytest.raises(psycopg.errors.NotNullViolation):
        db.execute(
            """INSERT INTO outbound_artifact (approval_id, artifact_type, content, created_by)
               VALUES (NULL, 'EXPORT', '{}', %s)""", (creator,))
    db.rollback()


def test_the_http_endpoint_refuses_an_export_with_no_approval_id(client, db):
    sign_in(client, "agent@crown.local")
    response = client.post("/outbound", data={"artifact_type": "EXPORT", "note": "x",
                                              **csrf(client)})
    assert response.status_code == 403
    assert "approval id" in response.get_json()["error"]
    assert db.execute("SELECT count(*) FROM outbound_artifact").fetchone()[0] == 0


def test_the_http_endpoint_accepts_an_export_with_a_valid_approval(client, db):
    approval_id, _ = approved_match(db)
    sign_in(client, "agent@crown.local")
    response = client.post("/outbound", data={"artifact_type": "EXPORT",
                                              "approval_id": str(approval_id),
                                              **csrf(client)})
    assert response.status_code == 201
    assert db.execute("SELECT count(*) FROM outbound_artifact").fetchone()[0] == 1
