"""The way out of a message Crown sent.

APP 7.3 requires a *simple* means of opting out of direct marketing. Section 18
of the Spam Act 2003 requires a commercial electronic message to carry a
*functional* unsubscribe facility that keeps working for at least 30 days. Both
words mean the same thing: the person who received the message stops it
themselves, without asking anyone's permission and without an account.

So this path is deliberately unlike every other path in the system.

  no sign-in        an opt-out that needed a password would not be simple, and
                    the recipient is not and never will be an app_user

  no lookup rights  the token is a signed capability, not a database key. The
                    link carries who to suppress; nothing has to be readable to
                    an anonymous caller for it to work

  writes one thing  the only effect available without signing in is adding a
                    suppression. Not reading one, not releasing one, not
                    touching anything else

The signature is an HMAC over the message, so a token cannot be forged without
the application secret, and the same token can be recomputed when a message is
re-sent rather than accumulating a table of live capabilities to leak.

The failure modes are deliberately lopsided. A token that will not verify does
nothing and says so. A token that verifies suppresses somebody — and if it were
ever forged, the consequence is that a person does not get contacted. Every
error in this module falls that way on purpose.
"""
import base64
import binascii
import hmac
import json
from dataclasses import dataclass
from hashlib import sha256

from . import audit, suppression

ACTOR_AGENT = "crown.optout"

# Distinguishes these signatures from any other use of the same secret, so a
# token minted here can never be replayed as a session cookie or the reverse.
PURPOSE = b"crown-opt-out-v1"


class BadToken(Exception):
    """The token is malformed, altered, or signed with a different secret."""


@dataclass(frozen=True)
class OptOut:
    artifact_id: str
    scope: str
    identifier: str


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(secret: str, payload: bytes) -> bytes:
    return hmac.new(secret.encode("utf-8"), PURPOSE + b"." + payload, sha256).digest()


def issue(secret: str, *, artifact_id, scope: str, identifier: str) -> str:
    """Mint the token that goes in the message."""
    if scope not in suppression.SCOPES:
        raise ValueError(f"unknown suppression scope {scope}")
    if not identifier or not str(identifier).strip():
        raise ValueError("an opt-out needs somebody to opt out")

    payload = json.dumps(
        {"a": str(artifact_id), "s": scope, "i": str(identifier)},
        separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    return f"{_b64(payload)}.{_b64(_signature(secret, payload))}"


def read(secret: str, token: str) -> OptOut:
    """Verify a token and say who it is for. Raises rather than guessing."""
    try:
        encoded, signature = str(token).split(".", 1)
        payload = _unb64(encoded)
        presented = _unb64(signature)
    except (ValueError, TypeError, binascii.Error) as exc:
        raise BadToken("this opt-out link is not readable") from exc

    if not hmac.compare_digest(presented, _signature(secret, payload)):
        raise BadToken("this opt-out link has been altered or is not ours")

    try:
        claim = json.loads(payload)
        return OptOut(artifact_id=claim["a"], scope=claim["s"],
                      identifier=claim["i"])
    except (ValueError, KeyError, TypeError) as exc:
        raise BadToken("this opt-out link is not readable") from exc


def redeem(conn, secret: str, token: str, *, requested_at,
           correlation_id=None) -> OptOut:
    """Record the suppression. Safe to call twice; the second is a no-op.

    Clicking an unsubscribe link twice is ordinary — people forward messages,
    scanners follow links, and a person who is unsure clicks again. The partial
    unique index in 0016 makes the repeat a no-op rather than an error, so the
    person always sees the same confirmation.

    The caller commits. Nothing here depends on the caller being signed in, and
    recorded_by is left NULL deliberately: a suppression nobody at Crown typed
    in is the one that proves the mechanism works.
    """
    who = read(secret, token)
    correlation_id = correlation_id or audit.new_correlation_id()

    # No RETURNING. An INSERT that returns rows is subject to the table's SELECT
    # policies, and the anonymous caller deliberately has none — being able to
    # opt out must not become a way to read back who else has. rowcount says
    # whether this click was the first one, which is all that is needed.
    inserted = conn.execute(
        """INSERT INTO contact_suppression
               (scope, identifier, normalised, reason, requested_at,
                recorded_by, source_of_request)
           VALUES (%s, %s, %s, %s, %s, NULL, 'OPT_OUT_LINK')
           ON CONFLICT DO NOTHING""",
        (who.scope, who.identifier, suppression.normalise(who.identifier),
         "opted out through the link in a message Crown sent", requested_at),
    ).rowcount

    # The audit row points at the message, not at the person. Somebody asking to
    # be left alone should not have their name copied into a second table to
    # record it — and the artefact already names them, for anyone entitled to
    # look.
    audit.write(
        conn, correlation_id,
        "OPT_OUT_RECEIVED" if inserted else "OPT_OUT_REPEATED",
        "outbound_artifact", who.artifact_id,
        new_state={"scope": who.scope, "artifact_id": who.artifact_id,
                   "source_of_request": "OPT_OUT_LINK"},
        actor_agent=ACTOR_AGENT)
    return who
