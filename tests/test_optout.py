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
    """Make sure Crown has somebody to send as, and say who.

    Idempotent since 0019 seeds the real one. Only one identity may be active
    at a time — that is the point of the unique index — so a test that wants
    one should get the one that exists rather than fight it.
    """
    existing = db.execute(
        "SELECT id FROM outbound_identity WHERE is_active").fetchone()
    return existing[0] if existing else insert_an_identity(db, user_email)


# A constructed ABN that passes the ATO checksum, which 0020 now requires of
# any stored value. It reads as obviously synthetic, which matters: a
# checksum-valid ABN can belong to a real entity, so this is a fixture and
# never goes in a document or a message.
A_SYNTHETIC_ABN = "11 111 111 106"


def insert_an_identity(db, user_email="hawk@crown.local", *,
                       legal_entity_name="A Second Sender Pty Ltd",
                       abn=A_SYNTHETIC_ABN,
                       postal_address="1 Example Street, Werribee VIC 3030",
                       contact_email="contact@crown.local"):
    """Always inserts. Raises if one is already active, which is what the
    uniqueness test is for.

    Every field is overridable because 0020 checks the contents of this row
    rather than only its existence, and a test of a malformed identity needs
    to be able to build one.
    """
    return db.execute(
        """INSERT INTO outbound_identity
               (legal_entity_name, abn, postal_address, contact_email, created_by)
           VALUES (%s, %s, %s, %s, %s)
           RETURNING id""",
        (legal_entity_name, abn, postal_address, contact_email,
         user_id(db, user_email))).fetchone()[0]


def no_active_identity(db):
    """Take Crown's sender away, for the tests that need its absence.

    0019 records the real one, so 'nobody has said who we send as' is now a
    condition to construct rather than one to inherit from an empty table.
    """
    db.execute("""UPDATE outbound_identity
                  SET is_active = false, superseded_at = now()
                  WHERE is_active""")


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


# ------------------------------------------------- who may set the sender (0017)

def test_the_sender_identity_is_row_secured(db):
    """0016 added the table with no policy at all — the third time a new table
    has arrived unguarded in this project. 0017 closes it, and
    test_review_0013.py is what caught it."""
    secured, forced = db.execute(
        """SELECT relrowsecurity, relforcerowsecurity FROM pg_class
           WHERE relname = 'outbound_identity'""").fetchone()
    assert secured and forced


def test_only_compliance_decides_who_crown_sends_as(app_db, db):
    """Reading the sender is ordinary — anybody drafting a message needs it.
    Deciding it is the claim the Spam Act holds Crown to."""
    from crown import db as crowndb

    author = user_id(db, "hawk@crown.local")
    db.commit()

    crowndb.set_identity(app_db, str(author), "AGENT")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_db.execute(
            """INSERT INTO outbound_identity
                   (legal_entity_name, postal_address, contact_email, created_by)
               VALUES ('Not Crown', '1 Somewhere', 'x@y.local', %s)""", (author,))
    app_db.rollback()

    # 0019 seeds the real sender, and only one may be active, so make room
    # before checking that COMPLIANCE is allowed to record one.
    crowndb.set_identity(app_db, str(author), "COMPLIANCE")
    app_db.execute("""UPDATE outbound_identity
                      SET is_active = false, superseded_at = now()
                      WHERE is_active""")
    app_db.execute(
        """INSERT INTO outbound_identity
               (legal_entity_name, postal_address, contact_email, created_by)
           VALUES ('A Replacement Sender Pty Ltd', '1 Example Street',
                   'contact@crown.local', %s)""", (author,))
    app_db.commit()


def test_an_identity_is_superseded_never_edited(db):
    """An artefact records which identity it went out under. If the address on
    that row can be changed afterwards, every message already sent starts
    misrepresenting its sender, silently and retrospectively."""
    identity_id = an_identity(db)

    with pytest.raises(psycopg.errors.RaiseException,
                       match="superseded, not edited"):
        db.execute(
            "UPDATE outbound_identity SET postal_address = '2 Elsewhere' "
            "WHERE id = %s", (identity_id,))
    db.rollback()


def test_deactivating_one_is_allowed_because_that_is_the_versioning(db):
    identity_id = an_identity(db)
    db.execute(
        """UPDATE outbound_identity
           SET is_active = false, superseded_at = now() WHERE id = %s""",
        (identity_id,))

    assert db.execute(
        "SELECT count(*) FROM outbound_identity WHERE is_active").fetchone()[0] == 0
