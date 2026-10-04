"""The things a system needs before anybody can be asked to rely on it.

Four gaps, none of them clever, all of them the difference between a system
that runs and a system somebody can run:

  the opt-out secret     signing session cookies and unsubscribe links with one
                         secret made a routine rotation into a Spam Act breach

  the brief              a BUYER_BRIEF sent by email is a commercial electronic
                         message too; a mandate supplies consent and not the
                         other two requirements

  the alert scheduler    five detectors that nothing ever invoked, so a
                         watchlist reporting nothing looked like a quiet day

  a health endpoint      no way to ask whether the process is up
"""
import psycopg
import pytest
from psycopg.types.json import Jsonb

from crown import optout, outbound
from scripts import run_alerts
from tests.conftest import a_body, approved_match, add_evidence, user_id
from tests.test_optout import an_identity

SECRET = "the-current-signing-secret"
RETIRED = "a-secret-rotated-out-last-month"


# ------------------------------------------------------- rotating the secret

def test_a_link_signed_with_a_retired_secret_still_works(db):
    """Section 18 gives an unsubscribe link thirty days of life. Rotating a
    secret must not cut that short, so retired secrets still verify."""
    from datetime import datetime, timezone

    old_link = optout.issue(RETIRED, artifact_id="a-1", scope="PERSON",
                            identifier="A. Landholder")

    who = optout.read([SECRET, RETIRED], old_link)
    assert who.identifier == "A. Landholder"

    optout.redeem(db, [SECRET, RETIRED], old_link,
                  requested_at=datetime.now(timezone.utc))
    assert db.execute(
        "SELECT count(*) FROM contact_suppression").fetchone()[0] == 1


def test_a_secret_that_was_never_ours_is_still_refused(db):
    """Accepting several secrets is not accepting any secret."""
    forged = optout.issue("not-crown's-secret", artifact_id="a-1",
                          scope="PERSON", identifier="A. Landholder")
    with pytest.raises(optout.BadToken):
        optout.read([SECRET, RETIRED], forged)


def test_new_links_are_signed_with_the_current_secret_only(db):
    """Rotation moves forward: what is minted today must not verify under a
    secret that has already been retired on its own."""
    fresh = optout.issue(SECRET, artifact_id="a-1", scope="PERSON",
                         identifier="A. Landholder")
    with pytest.raises(optout.BadToken):
        optout.read([RETIRED], fresh)
    assert optout.read([SECRET], fresh).identifier == "A. Landholder"


def test_the_environment_separates_the_two_secrets(monkeypatch):
    monkeypatch.setenv("CROWN_SECRET", "the-cookie-secret")
    monkeypatch.setenv("CROWN_OPTOUT_SECRET", SECRET)
    monkeypatch.setenv("CROWN_OPTOUT_SECRET_PREVIOUS", f" {RETIRED} , ,")

    signing, previous = optout.secrets_from_environment()
    assert signing == SECRET
    assert previous == [RETIRED]          # blanks dropped, whitespace trimmed


def test_it_falls_back_so_that_nothing_breaks_on_upgrade(monkeypatch):
    """A deployment that has not set the new variable keeps working. The
    readiness gate is where that gets reported, not here."""
    monkeypatch.setenv("CROWN_SECRET", "the-cookie-secret")
    monkeypatch.delenv("CROWN_OPTOUT_SECRET", raising=False)
    monkeypatch.delenv("CROWN_OPTOUT_SECRET_PREVIOUS", raising=False)

    signing, previous = optout.secrets_from_environment()
    assert signing == "the-cookie-secret"
    assert previous == []


def test_the_app_accepts_a_link_signed_with_a_retired_secret(app_dsn, database,
                                                             monkeypatch):
    """End to end: rotate, and last month's links keep working."""
    from crown.web import create_app
    from tests.conftest import give_everyone_a_password

    owner_dsn, _ = database
    with psycopg.connect(owner_dsn) as setup:
        give_everyone_a_password(setup)

    monkeypatch.setenv("CROWN_SECRET", "the-cookie-secret")
    monkeypatch.setenv("CROWN_OPTOUT_SECRET", SECRET)
    monkeypatch.setenv("CROWN_OPTOUT_SECRET_PREVIOUS", RETIRED)
    monkeypatch.setenv("CROWN_INSECURE_COOKIES", "1")
    client = create_app(app_dsn).test_client()

    old_link = optout.issue(RETIRED, artifact_id="a-1", scope="PERSON",
                            identifier="A. Landholder")
    assert client.post(f"/opt-out/{old_link}").status_code == 200


def test_the_cookie_secret_alone_no_longer_signs_opt_outs(app_dsn, database,
                                                          monkeypatch):
    """The point of separating them: rotating CROWN_SECRET must not be able to
    invalidate a live unsubscribe link, so it is not what signs them."""
    from crown.web import create_app
    from tests.conftest import give_everyone_a_password

    owner_dsn, _ = database
    with psycopg.connect(owner_dsn) as setup:
        give_everyone_a_password(setup)

    monkeypatch.setenv("CROWN_SECRET", "the-cookie-secret")
    monkeypatch.setenv("CROWN_OPTOUT_SECRET", SECRET)
    monkeypatch.delenv("CROWN_OPTOUT_SECRET_PREVIOUS", raising=False)
    monkeypatch.setenv("CROWN_INSECURE_COOKIES", "1")
    client = create_app(app_dsn).test_client()

    signed_with_the_cookie_secret = optout.issue(
        "the-cookie-secret", artifact_id="a-1", scope="PERSON",
        identifier="A. Landholder")
    assert client.post(f"/opt-out/{signed_with_the_cookie_secret}").status_code == 400


# --------------------------------------------------------------- the brief

def test_a_buyer_brief_now_needs_a_recipient_and_a_sender(db):
    """A mandate supplies the consent a cold approach lacks. It does not supply
    sender identification or a way to stop, which s17 and s18 want anyway."""
    an_identity(db)
    approval_id, creator = approved_match(db)

    with pytest.raises(outbound.NoWayOut, match="message to a person"):
        outbound.create(db, approval_id, "BUYER_BRIEF", {"body": a_body()}, creator)


def test_a_buyer_brief_with_both_is_produced(db):
    an_identity(db)
    approval_id, creator = approved_match(db)

    artifact_id = outbound.create(db, approval_id, "BUYER_BRIEF", {"body": a_body()},
                                  creator, contact={"ORGANISATION": "A Buyer Pty Ltd"},
                                  channel="EMAIL",
                                  recipient_class="MANDATED_BUYER")
    scope, identifier, sender = db.execute(
        """SELECT contact_scope, contact_identifier, sender_identity_id
           FROM outbound_artifact WHERE id = %s""", (artifact_id,)).fetchone()
    assert (scope, identifier) == ("ORGANISATION", "A Buyer Pty Ltd")
    assert sender is not None


def test_an_internal_artefact_still_needs_neither(db):
    """An EXPORT is not a message to anybody. Requiring a recipient of it would
    be ceremony, and ceremony is what people learn to work around."""
    approval_id, creator = approved_match(db)
    assert outbound.create(db, approval_id, "EXPORT", {"rows": []}, creator)


def test_the_database_refuses_it_even_if_the_code_is_bypassed(db):
    """The application says which of the three is missing; the constraint is
    what makes that advice rather than the control."""
    an_identity(db)
    approval_id, creator = approved_match(db)

    with pytest.raises(psycopg.errors.CheckViolation,
                       match="a_message_to_a_person_identifies"):
        db.execute(
            """INSERT INTO outbound_artifact
                   (approval_id, artifact_type, content, created_by)
               VALUES (%s, 'BUYER_BRIEF', %s, %s)""",
            (approval_id, Jsonb({"body": a_body()}), creator))
    db.rollback()


# ------------------------------------------------------- running the alerts

def test_the_scheduler_entry_point_runs_a_pass(database, capsys):
    """Five detectors have existed since 0012 and nothing ever invoked them."""
    owner_dsn, _ = database
    with psycopg.connect(owner_dsn) as conn:
        add_evidence(conn, reference="TEST-OPS-1", origin="REAL")
        conn.execute(
            """INSERT INTO watchlist (user_id, kind, target, label)
               VALUES (%s, 'LGA', 'Wyndham', 'Wyndham')""",
            (user_id(conn, "analyst@crown.local"),))
        conn.commit()

    assert run_alerts.main(["--dsn", owner_dsn]) == 0
    assert "raised" in capsys.readouterr().out


def test_running_it_twice_says_nothing_twice(database):
    """A scheduler re-runs after a crash, and a cron entry can overlap itself."""
    owner_dsn, _ = database
    with psycopg.connect(owner_dsn) as conn:
        add_evidence(conn, reference="TEST-OPS-2", origin="REAL")
        conn.execute(
            """INSERT INTO watchlist (user_id, kind, target, label)
               VALUES (%s, 'LGA', 'Wyndham', 'Wyndham')""",
            (user_id(conn, "analyst@crown.local"),))
        conn.commit()

    run_alerts.main(["--dsn", owner_dsn, "--quiet"])
    run_alerts.main(["--dsn", owner_dsn, "--quiet"])

    with psycopg.connect(owner_dsn) as conn:
        row = conn.execute("SELECT count(*) FROM alert").fetchone()
    assert row is not None and row[0] == 1


def test_a_quiet_day_is_not_an_error(database, capsys):
    """Nothing to report is an answer. A scheduler that alerts on it teaches
    people to ignore the alerts."""
    owner_dsn, _ = database
    assert run_alerts.main(["--dsn", owner_dsn, "--quiet"]) == 0
    assert capsys.readouterr().out == ""


def test_a_failed_run_says_so_where_a_scheduler_will_see_it(capsys):
    """The audit trail records decisions, not failures. A crashed run would
    otherwise leave no trace anywhere at all."""
    assert run_alerts.main(["--dsn", "postgresql://nobody@127.0.0.1:1/nothing"]) == 1
    assert "alert run failed" in capsys.readouterr().err


# ------------------------------------------------------------ is it alive

def test_health_answers_without_a_session(client):
    """Whatever checks it — a load balancer, a monitor, a deploy script — has
    no session and never will."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_health_says_nothing_a_stranger_should_not_know(client):
    """No version, no hostname, no counts, no configuration. Up or not up."""
    body = client.get("/health").get_json()
    assert set(body) == {"status"}
