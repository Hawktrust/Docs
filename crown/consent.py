"""Express consent to a channel.

Not the mirror of a suppression, though the tables look alike. A suppression is
a request to stop and outranks everything; a consent is permission to use one
route. Somebody can consent to email on Monday and ask to stop on Friday, and
both facts have to survive — which is why withdrawing a consent is not the same
act as recording a suppression, and why `crown/outbound.py` checks the
suppression list first regardless of what is recorded here.

The Spam Act recognises express and inferred consent. Only express is recorded
here. Inferred consent is a judgement about conspicuous publication that the
system cannot make and should not appear to have made — see
docs/compliance/CONSENT-POSITION.md.
"""
from . import audit
from .suppression import SCOPES, normalise

ACTOR_AGENT = "crown.consent"

# MANDATE is storable because a buyer's mandate really is consent, but it is not
# accepted as consent to email a landholder: it is consent from a different
# person about a different thing. 0024's trigger makes the same distinction.
BASES = ("EXPRESS_REPLY", "EXPRESS_WRITTEN", "MANDATE")
OPENS_EMAIL_TO_A_LANDHOLDER = ("EXPRESS_REPLY", "EXPRESS_WRITTEN")


class ConsentRefused(Exception):
    """The record as offered would not be evidence of anything."""


def record(conn, *, scope: str, identifier: str, basis: str, evidence: str,
           given_at, recorded_by, correlation_id=None) -> str:
    """Write down that somebody agreed, and what they actually did."""
    if scope not in SCOPES:
        raise ConsentRefused(f"unknown scope {scope}")
    if basis not in BASES:
        raise ConsentRefused(f"unknown consent basis {basis}")
    if not evidence or not evidence.strip():
        raise ConsentRefused(
            "a consent records what happened. 'They consented' is a "
            "conclusion, not evidence, and it is the sentence that will be "
            "read back if this is ever questioned.")

    consent_id = conn.execute(
        """INSERT INTO contact_consent
               (scope, identifier, normalised, basis, evidence, given_at,
                recorded_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (scope, identifier, normalise(identifier), basis, evidence.strip(),
         given_at, recorded_by),
    ).fetchone()[0]

    audit.write(conn, correlation_id or audit.new_correlation_id(),
                "CONSENT_RECORDED", "contact_consent", consent_id,
                new_state={"scope": scope, "basis": basis},
                actor_user_id=recorded_by, actor_agent=ACTOR_AGENT)
    return str(consent_id)


def withdraw(conn, consent_id, *, withdrawn_by, correlation_id=None) -> None:
    """They changed their mind. Recorded, not deleted.

    Withdrawing a consent closes a channel. It is not a suppression and does
    not stop other channels — somebody who says "stop emailing me, send post"
    has done this and not that. If they meant stop entirely, record a
    suppression as well; the two are separate because the requests are.
    """
    rows = conn.execute(
        """UPDATE contact_consent
           SET withdrawn_at = now(), withdrawn_by = %s
           WHERE id = %s AND withdrawn_at IS NULL""",
        (withdrawn_by, consent_id)).rowcount
    if not rows:
        raise ConsentRefused(
            f"consent {consent_id} is not on record, or was already withdrawn")

    audit.write(conn, correlation_id or audit.new_correlation_id(),
                "CONSENT_WITHDRAWN", "contact_consent", consent_id,
                actor_user_id=withdrawn_by, actor_agent=ACTOR_AGENT)
