"""AC9: authorisation is enforced server-side.

The rule this module exists to hold: a caller's role is looked up from the
database on every request, using an identity established by a signed session
cookie. It is never read from anything the client can set.

Clients do send role-shaped headers — proxies add them, and an attacker will try
one. The names below are recorded so the intent is legible, and so a test can
assert they change nothing. Nothing in this module or in crown.web reads them.
"""
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import scrypt, sha256

# Headers a client might hope are trusted. None of them is.
IGNORED_ROLE_HEADERS = (
    "X-Crown-Role", "X-Crown-User-Id", "X-Role", "X-User-Role",
    "X-Forwarded-Role", "Crown-Role",
)


class AuthenticationFailed(Exception):
    """Wrong credentials, unknown account, or no password set.

    Deliberately one exception with one message. Distinguishing "no such user"
    from "wrong password" tells an attacker which addresses are real.
    """


class AccountLocked(AuthenticationFailed):
    """Too many failed attempts. Says so, because the account holder needs to know."""


# scrypt: memory-hard, in the standard library, no dependency to keep current.
# Parameters follow the interactive-login end of RFC 7914's guidance.
SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_SALT_BYTES = 16
SCRYPT_KEY_BYTES = 32
# OpenSSL caps scrypt at 32 MiB by default; N=2**15 needs 128*N*r = 32 MiB
# exactly, so the cap has to be raised or the hash refuses to compute.
SCRYPT_MAXMEM = 64 * 1024 * 1024

MAX_FAILED_ATTEMPTS = 5
LOCKOUT = timedelta(minutes=15)

# Longer than a working session, short enough that an unattended browser stops
# being an approver by the next morning.
SESSION_IDLE_TIMEOUT = timedelta(hours=8)


def hash_password(password: str) -> str:
    """Return a self-describing hash: the parameters travel with the digest, so
    they can be raised later without invalidating existing passwords."""
    if len(password) < 12:
        raise ValueError("a password must be at least 12 characters")
    salt = os.urandom(SCRYPT_SALT_BYTES)
    digest = scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N,
                    r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_KEY_BYTES,
                    maxmem=SCRYPT_MAXMEM)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time check. A missing or unparseable hash is a failure, not a pass."""
    if not stored:
        return False
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                           n=int(n), r=int(r), p=int(p),
                           dklen=len(bytes.fromhex(digest_hex)),
                           maxmem=SCRYPT_MAXMEM)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, bytes.fromhex(digest_hex))


@dataclass(frozen=True)
class Identity:
    user_id: str
    email: str
    display_name: str
    role: str

    def has_role(self, *roles: str) -> bool:
        return self.role in roles


def sign(secret: str, value: str) -> str:
    return hmac.new(secret.encode(), value.encode(), sha256).hexdigest()


def verify(secret: str, value: str, signature: str) -> bool:
    return hmac.compare_digest(sign(secret, value), signature)


BAD_CREDENTIALS = "email or password is not correct"


def authenticate(conn, email: str, password: str) -> Identity:
    """Establish who the caller is, or refuse.

    Counts failed attempts and locks the account after MAX_FAILED_ATTEMPTS, so a
    password cannot be found by trying. The caller commits.
    """
    row = conn.execute(
        """SELECT id, email, display_name, role, password_hash, failed_attempts,
                  locked_until
           FROM app_user WHERE email = %s AND is_active""",
        (email,),
    ).fetchone()

    if row is None:
        # Spend comparable time so a missing account is not faster to probe.
        verify_password(password, hash_password(secrets.token_urlsafe(16)))
        raise AuthenticationFailed(BAD_CREDENTIALS)

    user_id, stored_email, display_name, role, stored_hash, attempts, locked_until = row
    now = datetime.now(timezone.utc)

    if locked_until and locked_until > now:
        raise AccountLocked(
            f"too many failed attempts; locked until {locked_until:%H:%M} UTC")

    if not verify_password(password, stored_hash):
        attempts += 1
        lock = now + LOCKOUT if attempts >= MAX_FAILED_ATTEMPTS else None
        conn.execute(
            "UPDATE app_user SET failed_attempts = %s, locked_until = %s WHERE id = %s",
            (attempts, lock, user_id))
        if lock:
            raise AccountLocked(
                f"too many failed attempts; locked until {lock:%H:%M} UTC")
        raise AuthenticationFailed(BAD_CREDENTIALS)

    conn.execute(
        """UPDATE app_user SET failed_attempts = 0, locked_until = NULL,
                  last_sign_in_at = now() WHERE id = %s""", (user_id,))
    return Identity(str(user_id), stored_email, display_name, role)


def set_password(conn, email: str, password: str) -> str:
    """Set or replace a password. Returns the user id. The caller commits."""
    row = conn.execute(
        "UPDATE app_user SET password_hash = %s, password_set_at = now(), "
        "failed_attempts = 0, locked_until = NULL WHERE email = %s RETURNING id",
        (hash_password(password), email),
    ).fetchone()
    if row is None:
        raise AuthenticationFailed(f"no user {email}")
    return str(row[0])


def load(conn, user_id: str) -> Identity | None:
    """Re-read the identity for an already-authenticated session.

    Called on every request rather than trusting a role carried in the cookie,
    so a role changed or revoked in the database takes effect immediately.
    """
    if not user_id:
        return None
    row = conn.execute(
        "SELECT id, email, display_name, role FROM app_user WHERE id = %s AND is_active",
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    return Identity(str(row[0]), row[1], row[2], row[3])
