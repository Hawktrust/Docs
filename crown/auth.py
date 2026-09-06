"""AC9: authorisation is enforced server-side.

The rule this module exists to hold: a caller's role is looked up from the
database on every request, using an identity established by a signed session
cookie. It is never read from anything the client can set.

Clients do send role-shaped headers — proxies add them, and an attacker will try
one. The names below are recorded so the intent is legible, and so a test can
assert they change nothing. Nothing in this module or in crown.web reads them.
"""
import hmac
from dataclasses import dataclass
from hashlib import sha256

# Headers a client might hope are trusted. None of them is.
IGNORED_ROLE_HEADERS = (
    "X-Crown-Role", "X-Crown-User-Id", "X-Role", "X-User-Role",
    "X-Forwarded-Role", "Crown-Role",
)


class AuthenticationFailed(Exception):
    pass


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


def authenticate(conn, email: str) -> Identity:
    """Establish who the caller is. Returns their identity as the database has it."""
    row = conn.execute(
        "SELECT id, email, display_name, role FROM app_user WHERE email = %s AND is_active",
        (email,),
    ).fetchone()
    if row is None:
        raise AuthenticationFailed(f"no active user {email}")
    return Identity(str(row[0]), row[1], row[2], row[3])


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
