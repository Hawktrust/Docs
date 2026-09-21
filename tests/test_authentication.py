"""Authentication.

Authorisation was real from the start. Authentication was not: POST /login took
an email and no password, so anyone who could reach the app could be anyone, and
every control built on identity rested on that.
"""
import time

import pytest

from crown import auth
from tests.conftest import TEST_PASSWORD, give_everyone_a_password, sign_in


# ------------------------------------------------------------- the hash itself

def test_a_password_hash_is_salted_and_self_describing():
    first = auth.hash_password("correct horse battery staple")
    second = auth.hash_password("correct horse battery staple")
    assert first != second, "the same password twice must not give the same hash"
    assert first.startswith("scrypt$")
    # the parameters travel with the digest so they can be raised later
    scheme, n, r, p, salt, digest = first.split("$")
    assert int(n) >= 2 ** 15 and int(r) == 8
    assert len(bytes.fromhex(salt)) == auth.SCRYPT_SALT_BYTES
    assert "correct horse" not in first


def test_verification_accepts_the_password_and_nothing_else():
    stored = auth.hash_password("correct horse battery staple")
    assert auth.verify_password("correct horse battery staple", stored)
    assert not auth.verify_password("Correct horse battery staple", stored)
    assert not auth.verify_password("", stored)
    assert not auth.verify_password("correct horse battery staple", stored[:-2] + "00")


def test_a_missing_or_broken_hash_never_verifies():
    """A NULL password_hash must not be a skeleton key."""
    for stored in (None, "", "not-a-hash", "scrypt$bad", "md5$x$y$z$w$v"):
        assert not auth.verify_password("anything", stored)


def test_short_passwords_are_refused():
    with pytest.raises(ValueError, match="at least 12"):
        auth.hash_password("short")


# ------------------------------------------------------------------ signing in

def test_a_seeded_account_cannot_be_signed_into_until_a_password_is_set(db):
    """0006 leaves password_hash NULL, which is the safe default: these users
    exist as owners and approvers before anyone has given them credentials."""
    assert db.execute(
        "SELECT count(*) FROM app_user WHERE password_hash IS NOT NULL").fetchone()[0] == 0
    with pytest.raises(auth.AuthenticationFailed):
        auth.authenticate(db, "hawk@crown.local", "")


def test_the_right_password_authenticates(db):
    give_everyone_a_password(db)
    identity = auth.authenticate(db, "compliance@crown.local", TEST_PASSWORD)
    assert identity.role == "COMPLIANCE"
    assert identity.email == "compliance@crown.local"


def test_the_wrong_password_does_not(db):
    give_everyone_a_password(db)
    with pytest.raises(auth.AuthenticationFailed):
        auth.authenticate(db, "compliance@crown.local", "not the password")


def test_an_unknown_account_and_a_wrong_password_are_indistinguishable(db):
    """Different messages would tell an attacker which addresses are real."""
    give_everyone_a_password(db)
    with pytest.raises(auth.AuthenticationFailed) as unknown:
        auth.authenticate(db, "nobody@crown.local", "whatever")
    with pytest.raises(auth.AuthenticationFailed) as wrong:
        auth.authenticate(db, "hawk@crown.local", "whatever")
    assert str(unknown.value) == str(wrong.value) == auth.BAD_CREDENTIALS


def test_an_inactive_user_cannot_sign_in(db):
    give_everyone_a_password(db)
    db.execute("UPDATE app_user SET is_active = false WHERE email = 'agent@crown.local'")
    with pytest.raises(auth.AuthenticationFailed):
        auth.authenticate(db, "agent@crown.local", TEST_PASSWORD)


# --------------------------------------------------------------------- lockout

def test_repeated_failures_lock_the_account(db):
    give_everyone_a_password(db)
    for _ in range(auth.MAX_FAILED_ATTEMPTS - 1):
        with pytest.raises(auth.AuthenticationFailed):
            auth.authenticate(db, "hawk@crown.local", "wrong")

    with pytest.raises(auth.AccountLocked):
        auth.authenticate(db, "hawk@crown.local", "wrong")

    # and the correct password does not open it while it is locked
    with pytest.raises(auth.AccountLocked):
        auth.authenticate(db, "hawk@crown.local", TEST_PASSWORD)


def test_a_successful_sign_in_clears_the_counter(db):
    give_everyone_a_password(db)
    for _ in range(2):
        with pytest.raises(auth.AuthenticationFailed):
            auth.authenticate(db, "hawk@crown.local", "wrong")
    auth.authenticate(db, "hawk@crown.local", TEST_PASSWORD)
    assert db.execute(
        "SELECT failed_attempts FROM app_user WHERE email = 'hawk@crown.local'"
    ).fetchone()[0] == 0


def test_setting_a_password_unlocks_the_account(db):
    give_everyone_a_password(db)
    for _ in range(auth.MAX_FAILED_ATTEMPTS):
        with pytest.raises(auth.AuthenticationFailed):
            auth.authenticate(db, "hawk@crown.local", "wrong")
    auth.set_password(db, "hawk@crown.local", "a-brand-new-password")
    assert auth.authenticate(db, "hawk@crown.local", "a-brand-new-password")


# ----------------------------------------------------------- through the door

def test_the_login_form_requires_a_password(client, db):
    db.commit()
    response = client.post("/login", data={"email": "hawk@crown.local"})
    assert response.status_code == 401
    with client.session_transaction() as session:
        assert "user_id" not in session


def test_a_failed_sign_in_is_audited_with_whether_it_locked(client, db):
    db.commit()
    for _ in range(auth.MAX_FAILED_ATTEMPTS):
        client.post("/login", data={"email": "hawk@crown.local", "password": "wrong"})

    rows = db.execute(
        """SELECT new_state FROM audit_event WHERE action = 'SIGN_IN_FAILED'
           ORDER BY id""").fetchall()
    assert len(rows) == auth.MAX_FAILED_ATTEMPTS
    assert rows[-1][0]["locked"] is True


def test_signing_in_starts_a_fresh_session(client, db):
    """An attacker who fixed a session id beforehand must not inherit it."""
    db.commit()
    with client.session_transaction() as session:
        session["planted"] = "value from before sign-in"

    sign_in(client, "analyst@crown.local")

    with client.session_transaction() as session:
        assert "planted" not in session
        assert session["user_id"]


def test_an_idle_session_stops_being_signed_in(client, db):
    db.commit()
    sign_in(client, "compliance@crown.local")
    assert client.get("/overview").status_code == 200

    with client.session_transaction() as session:
        session["last_seen"] = "2020-01-01T00:00:00+00:00"

    assert client.get("/overview").status_code == 401
