"""Nothing is kept forever, and what is kept is kept for a reason.

APP 11.2 requires personal information to be destroyed or de-identified once it
is no longer needed. The privacy policy states Crown's periods; migration 0026
holds them as data and this is the way to act on them.

Two habits are deliberate. The sweep defaults to a dry run, because one that
acts by default is one somebody runs by accident against the wrong database.
And an expired artefact is de-identified rather than deleted: the person is
removed and the decision stays, because the audit trail exists to show what
Crown did and a retention rule that erased it would be a deletion schedule for
evidence.
"""
from . import audit

ACTOR_AGENT = "crown.retention"


def rules(conn):
    """The periods, as the database holds them."""
    return conn.execute(
        """SELECT category, period, applies_to, basis
           FROM retention_rule ORDER BY category""").fetchall()


def due(conn):
    """What is past its period. Read this before sweeping."""
    return conn.execute(
        """SELECT category, object_table, object_id, held_since
           FROM retention_due ORDER BY held_since""").fetchall()


def apply(conn, *, dry_run: bool = True, correlation_id=None):
    """Destroy or de-identify what is due, and say what was touched.

    Returns the same rows whether or not it acted, so a dry run and a real one
    can be compared. `acted` is the difference.
    """
    rows = conn.execute(
        "SELECT category, object_table, object_id, acted FROM apply_retention(%s)",
        (dry_run,)).fetchall()

    if not dry_run and rows:
        audit.write(conn, correlation_id or audit.new_correlation_id(),
                    "RETENTION_SWEPT", "retention_rule", "all",
                    new_state={"records": len(rows)},
                    actor_agent=ACTOR_AGENT)
    return rows
