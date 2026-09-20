"""Do not contact.

APP 7 requires a simple means of opting out of direct marketing, and requires it
to work. "Works" means the check is in the path that creates outbound artifacts,
not in a policy document beside it.

A suppression is never deleted. Releasing one records who released it and why,
so the original request stays visible.
"""
from dataclasses import dataclass

from . import audit

ACTOR_AGENT = "crown.suppression"

SCOPES = ("PERSON", "ADDRESS", "PARCEL", "ORGANISATION")
REQUEST_SOURCES = ("OPT_OUT_LINK", "EMAIL", "PHONE", "IN_PERSON", "LEGAL", "OTHER")


class Suppressed(Exception):
    """Someone asked not to be contacted, so nothing is produced for them."""


@dataclass(frozen=True)
class Match:
    scope: str
    identifier: str
    reason: str
    requested_at: object


def normalise(identifier: str) -> str:
    """Matching form. Deliberately blunt: a near miss should suppress."""
    return " ".join(str(identifier).strip().lower().split())


def record(conn, *, scope: str, identifier: str, reason: str, requested_at,
           recorded_by, source_of_request: str, correlation_id=None) -> str:
    if scope not in SCOPES:
        raise ValueError(f"unknown suppression scope {scope}")
    if source_of_request not in REQUEST_SOURCES:
        raise ValueError(f"unknown request source {source_of_request}")
    if not reason or not reason.strip():
        raise ValueError("a suppression records why it was requested")

    correlation_id = correlation_id or audit.new_correlation_id()
    suppression_id = conn.execute(
        """INSERT INTO contact_suppression (scope, identifier, normalised, reason,
                   requested_at, recorded_by, source_of_request)
           VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (scope, identifier, normalise(identifier), reason.strip(), requested_at,
         recorded_by, source_of_request),
    ).fetchone()[0]

    audit.write(conn, correlation_id, "CONTACT_SUPPRESSED", "contact_suppression",
                suppression_id,
                new_state={"scope": scope, "source_of_request": source_of_request},
                actor_user_id=recorded_by, actor_agent=ACTOR_AGENT)
    return suppression_id


def check(conn, candidates: dict) -> list[Match]:
    """Return every active suppression matching the given {scope: identifier}.

    Takes everything known about a target at once — the person, the address, the
    parcel, the company — because a request to stop contacting a person should
    not be defeated by addressing the envelope to their company.
    """
    matches = []
    for scope, identifier in candidates.items():
        if not identifier:
            continue
        row = conn.execute(
            """SELECT scope, identifier, reason, requested_at
               FROM contact_suppression
               WHERE scope = %s AND normalised = %s AND released_at IS NULL
               LIMIT 1""",
            (scope, normalise(identifier)),
        ).fetchone()
        if row:
            matches.append(Match(*row))
    return matches


def assert_not_suppressed(conn, candidates: dict) -> None:
    """Raise if anything about this target is suppressed. Called before outbound."""
    matches = check(conn, candidates)
    if matches:
        detail = "; ".join(
            f"{m.scope} {m.identifier!r} asked not to be contacted on "
            f"{m.requested_at:%Y-%m-%d} ({m.reason})" for m in matches)
        raise Suppressed(detail)


def release(conn, suppression_id, *, released_by, reason: str,
            correlation_id=None) -> None:
    """Lift a suppression. Rare, and never silent."""
    if not reason or not reason.strip():
        raise ValueError("releasing a suppression records why")
    correlation_id = correlation_id or audit.new_correlation_id()
    conn.execute(
        """UPDATE contact_suppression
           SET released_at = now(), released_by = %s, released_reason = %s
           WHERE id = %s AND released_at IS NULL""",
        (released_by, reason.strip(), suppression_id))
    audit.write(conn, correlation_id, "CONTACT_SUPPRESSION_RELEASED",
                "contact_suppression", suppression_id,
                new_state={"reason": reason.strip()},
                actor_user_id=released_by, actor_agent=ACTOR_AGENT)
