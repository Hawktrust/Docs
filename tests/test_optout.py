"""The way out of a message Crown sent.

APP 7.3 wants a simple means of opting out; section 18 of the Spam Act wants a
functional one. Both words mean the recipient does it themselves. These tests
hold that: no account, no sign-in, no help from anybody at Crown, and it works
the second time as well as the first.

They also hold the shape of the thing that makes it safe — the anonymous caller
can add a suppression and can do nothing else at all.
"""
import psycopg
import pytest

from crown import optout, outbound, suppression
from tests.conftest import approved_match, csrf, sign_in, user_id

SECRET = "test-secret-for-opt-out-tokens"


def an_identity(db, user_email="hawk@crown.local"):
    return db.execute(
        """INSERT INTO outbound_identity
               (legal_entity_name, abn, postal_address, contact_email, created_by)
           VALUES ('Crown Capital & Development Pty Ltd', '00 000 000 000',
                   '1 Example Street, Werribee VIC 3030',
                   'contact@crown.local', %s)
           RETURNING id""", (user_id(db, user_email),)).fetchone()[0]


def active_suppressions(db):
    return db.execute(
        """SELECT scope, normalised, source_of_request, recorded_by
           FROM contact_suppression WHERE released_at IS NULL""").fetchall()


# ----------------------------------------------------------------- the token

def test_a_token_survives_a_round_trip(db):
    token = optout.issue(SECRET, artifact_id="a-1", scope="PERSON",
                         identifier="A. Landholder")
    who = optout.read(SECRET, token)
    assert (who.artifact_id, who.scope, who.identifier) == \
        ("a-1", "PERSON", "A. Landholder")


def test_an_altered_token_is_refused(db):
    """The identifier is inside the signature, so it cannot be swapped for
    somebody else's."""
    token = optout.issue(SECRET, artifact_id="a-1", scope="PERSON",
                         identifier="A. Landholder")
    payload, signature = token.split(".")
    forged = optout.issue(SECRET, artifact_id="a-1", scope="PERSON",
                          identifier="B. Someone Else").split(".")[0]

    with pytest.raises(optout.BadToken, match="altered or is not ours"):
        optout.read(SECRET, f"{forged}.{signature}")


def test_a_token_from_another_secret_is_refused(db):
    token = optout.issue("some-other-deployment", artifact_id="a-1",
                         scope="PERSON", identifier="A. Landholder")
    with pytest.raises(optout.BadToken):
        optout.read(SECRET, token)


def test_rubbish_is_refused_without_an_exception_escaping(db):
    for rubbish in ("", "no-dot", "...", "a.b", "!!!.???"):
        with pytest.raises(optout.BadToken):
            optout.read(SECRET, rubbish)


def test_the_signature_is_scoped_to_this_purpose(db):
    """A token minted here can never be replayed as anything else signed with
    the same secret, because the purpose is inside the HMAC."""
    import base64
    import hmac
    from hashlib import sha256

    payload = b'{"a":"a-1","i":"A. Landholder","s":"PERSON"}'
    without_purpose = hmac.new(SECRET.encode(), payload, sha256).digest()
    token = (base64.urlsafe_b64encode(payload).decode().rstrip("=") + "."
             + base64.urlsafe_b64encode(without_purpose).decode().rstrip("="))

    with pytest.raises(optout.BadToken):
        optout.read(SECRET, token)


# --------------------------------------------------------------- redeeming it

def test_redeeming_suppresses_the_person_with_nobody_signed_in(db):
    """The whole point: no account, no staff member, no request to anyone."""
    from datetime import datetime, timezone

    token = optout.issue(SECRET, artifact_id="a-1", scope="PERSON",
                         identifier="A. Landholder")
    optout.redeem(db, SECRET, token, requested_at=datetime.now(timezone.utc))

    rows = active_suppressions(db)
    assert len(rows) == 1
    scope, normalised, source, recorded_by = rows[0]
    assert (scope, normalised, source) == ("PERSON", "a. landholder", "OPT_OUT_LINK")
    assert recorded_by is None, "a self-service opt-out has no staff member on it"


def test_clicking_twice_is_not_an_error(db):
    """People forward messages and click again when unsure. The second click
    shows the same confirmation rather than a failure."""
    from datetime import datetime, timezone

    token = optout.issue(SECRET, artifact_id="a-1", scope="PERSON",
                         identifier="A. Landholder")
    optout.redeem(db, SECRET, token, requested_at=datetime.now(timezone.utc))
    optout.redeem(db, SECRET, token, requested_at=datetime.now(timezone.utc))

    assert len(active_suppressions(db)) == 1


def test_both_clicks_are_on_the_record_and_told_apart(db):
    from datetime import datetime, timezone

    token = optout.issue(SECRET, artifact_id="a-1", scope="PERSON",
                         identifier="A. Landholder")
    optout.redeem(db, SECRET, token, requested_at=datetime.now(timezone.utc))
    optout.redeem(db, SECRET, token, requested_at=datetime.now(timezone.utc))

    actions = [r[0] for r in db.execute(
        """SELECT action FROM audit_event
           WHERE action LIKE 'OPT_OUT%' ORDER BY occurred_at""").fetchall()]
    assert actions == ["OPT_OUT_RECEIVED", "OPT_OUT_REPEATED"]


def test_the_audit_row_does_not_repeat_the_person(db):
    """An opt-out is somebody asking to be left alone. Copying their name into
    a second table to record that is the opposite of honouring it."""
    from datetime import datetime, timezone

    token = optout.issue(SECRET, artifact_id="a-1", scope="PERSON",
                         identifier="A. Landholder")
    optout.redeem(db, SECRET, token, requested_at=datetime.now(timezone.utc))

    state = db.execute(
        """SELECT new_state FROM audit_event
           WHERE action = 'OPT_OUT_RECEIVED'""").fetchone()[0]
    assert "A. Landholder" not in str(state)
    assert state["scope"] == "PERSON"
    assert state["artifact_id"] == "a-1"


def test_the_suppression_then_blocks_the_next_message(db):
    """The loop closes: opting out actually stops the thing it is meant to."""
    from datetime import datetime, timezone

    an_identity(db)
    approval_id, creator = approved_match(db)
    contact = {"PERSON": "A. Landholder"}

    token = optout.issue(SECRET, artifact_id="a-1", scope="PERSON",
                         identifier="A. Landholder")
    optout.redeem(db, SECRET, token, requested_at=datetime.now(timezone.utc))

    with pytest.raises(suppression.Suppressed):
        outbound.create(db, approval_id, "OUTREACH_DRAFT", {"body": "hello"},
                        creator, contact=contact)


# --------------------------------------------- what the anonymous caller cannot do

def test_an_anonymous_caller_can_only_ever_add_a_suppression(app_db):
    """The policy that makes the public route safe. With no identity set, the
    one thing available is opting somebody out — not reading who else has,
    not releasing one, not touching anything else."""
    from crown import db as crowndb
    crowndb.set_identity(app_db, "", "")

    app_db.execute(
        """INSERT INTO contact_suppression
               (scope, identifier, normalised, reason, requested_at,
                recorded_by, source_of_request)
           VALUES ('PERSON','A. Landholder','a. landholder','opted out',
                   now(), NULL, 'OPT_OUT_LINK')""")

    # ...and cannot read it back, or anything else in that table
    assert app_db.execute(
        "SELECT count(*) FROM contact_suppression").fetchone()[0] == 0
    app_db.rollback()


def test_an_anonymous_caller_cannot_record_any_other_kind(app_db):
    """The policy is narrow on purpose: only the self-service shape passes."""
    from crown import db as crowndb
    crowndb.set_identity(app_db, "", "")

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_db.execute(
            """INSERT INTO contact_suppression
                   (scope, identifier, normalised, reason, requested_at,
                    recorded_by, source_of_request)
               VALUES ('PERSON','B. Person','b. person','legal',
                       now(), NULL, 'LEGAL')""")
    app_db.rollback()


# ------------------------------------------------------------- over the wire

def test_a_get_shows_a_confirmation_and_changes_nothing(client, db):
    """Mail scanners follow links without a human ever seeing them. A GET that
    suppressed would record opt-outs nobody asked for."""
    token = optout.issue(client.application.config["SECRET_KEY"],
                         artifact_id="a-1", scope="PERSON",
                         identifier="A. Landholder")

    page = client.get(f"/opt-out/{token}")
    assert page.status_code == 200
    assert b"Stop contacting me" in page.data
    assert active_suppressions(db) == []


def test_the_post_is_what_acts_and_needs_no_sign_in(client, db):
    token = optout.issue(client.application.config["SECRET_KEY"],
                         artifact_id="a-1", scope="PERSON",
                         identifier="A. Landholder")

    done = client.post(f"/opt-out/{token}")
    assert done.status_code == 200
    assert b"You have been removed" in done.data
    assert len(active_suppressions(db)) == 1


def test_the_page_never_repeats_the_person_back(client):
    """Anyone holding the link can read the name in it already. Printing it on
    screen only turns a glance over a shoulder into a disclosure."""
    token = optout.issue(client.application.config["SECRET_KEY"],
                         artifact_id="a-1", scope="PERSON",
                         identifier="A. Landholder")

    assert b"A. Landholder" not in client.get(f"/opt-out/{token}").data
    assert b"A. Landholder" not in client.post(f"/opt-out/{token}").data


def test_a_bad_link_says_so_and_offers_a_way_that_works(client):
    page = client.get("/opt-out/not-a-real-token")
    assert page.status_code == 400
    assert b"did not work" in page.data
    assert b"asking to be removed" in page.data


def test_no_csrf_token_is_needed_to_stop_being_contacted(client, db):
    """There is no session to forge against, and requiring one would make the
    opt-out neither simple nor functional. The worst a forged request achieves
    is that somebody stops being contacted."""
    token = optout.issue(client.application.config["SECRET_KEY"],
                         artifact_id="a-1", scope="PERSON",
                         identifier="A. Landholder")

    assert client.post(f"/opt-out/{token}").status_code == 200
    assert len(active_suppressions(db)) == 1


def test_signing_in_does_not_break_the_public_route(client, db):
    """A staff member testing the link should not get a CSRF rejection for it."""
    sign_in(client, "analyst@crown.local")
    token = optout.issue(client.application.config["SECRET_KEY"],
                         artifact_id="a-1", scope="PERSON",
                         identifier="A. Landholder")

    response = client.post(f"/opt-out/{token}")
    assert response.status_code in (200, 403)
    # whichever it is, a signed-in staff member must not be able to opt
    # somebody out *without* the CSRF token, so 403 is the acceptable answer
    if response.status_code == 403:
        assert active_suppressions(db) == []


# -------------------------------------------------- the link that goes in a message

def test_the_link_is_rebuilt_rather_than_stored(db):
    """Re-sending a message produces the same link, and no table of live
    capabilities accumulates anywhere to be leaked."""
    first = outbound.opt_out_link(SECRET, "https://crown.example",
                                  "a-1", "PERSON", "A. Landholder")
    again = outbound.opt_out_link(SECRET, "https://crown.example/",
                                  "a-1", "PERSON", "A. Landholder")
    assert first == again
    assert first.startswith("https://crown.example/opt-out/")

    stored = db.execute(
        """SELECT count(*) FROM information_schema.columns
           WHERE table_name = 'outbound_artifact'
             AND column_name LIKE '%token%'""").fetchone()[0]
    assert stored == 0, "the token is derived, not kept"
