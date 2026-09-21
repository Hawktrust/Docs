"""Findings from the review after building alerts and the brief.

Each failed before migration 0013 and the accompanying fixes.
"""
import psycopg
import pytest

from crown import alerts, db as crown_db
from tests.conftest import add_evidence, user_id


def an_unnamed_actor(conn, name="A Named Member of Parliament"):
    return conn.execute(
        """INSERT INTO market_actor (name, normalised, kind, publishable_by_name)
           VALUES (%s,%s,'ELECTED_OFFICIAL',false) RETURNING id""",
        (name, name.lower())).fetchone()[0]


# -------------------------------------------------- the control on the base table

def test_an_analyst_cannot_read_an_unnamed_actor_at_all(app_db, db):
    """The control lived in a view, and the base table answered anyway — the
    same failure buyer_mandate_real had."""
    an_unnamed_actor(db)
    db.commit()

    crown_db.set_identity(app_db, "", "ANALYST")
    assert app_db.execute("SELECT name FROM market_actor").fetchall() == []
    assert app_db.execute("SELECT count(*) FROM actor_signal_publishable").fetchone()[0] == 0


def test_an_agent_cannot_either(app_db, db):
    """Between them, analysts and agents write every brief, export and draft."""
    an_unnamed_actor(db)
    db.commit()
    crown_db.set_identity(app_db, "", "AGENT")
    assert app_db.execute("SELECT name FROM market_actor").fetchall() == []


def test_compliance_can_audit_what_the_system_is_counting(app_db, db):
    an_unnamed_actor(db)
    db.commit()
    crown_db.set_identity(app_db, "", "COMPLIANCE")
    assert len(app_db.execute("SELECT name FROM market_actor").fetchall()) == 1


def test_a_publishable_actor_is_visible_to_everyone(app_db, db):
    db.execute("""INSERT INTO market_actor (name, normalised, kind)
                  VALUES ('A Listed Developer','a listed developer','LISTED_DEVELOPER')""")
    db.commit()
    crown_db.set_identity(app_db, "", "ANALYST")
    assert len(app_db.execute("SELECT name FROM market_actor").fetchall()) == 1


def test_every_table_added_since_the_policies_has_one(db):
    """Each migration added a table and none went back to check."""
    unguarded = {r[0] for r in db.execute(
        """SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'public' AND c.relkind = 'r'
             AND NOT c.relrowsecurity""").fetchall()}

    # These are deliberate: reference data, the append-only log, and the raw
    # landing zone, none of which is row-scoped.
    allowed = {"app_user", "audit_event", "data_source", "evidence_record",
               "evidence_review_queue", "raw_ingest", "match_weight_config",
               "signal_weight_config", "opportunity_evidence", "opportunity_parcel"}
    assert unguarded <= allowed, f"no policy on {sorted(unguarded - allowed)}"


def test_a_parcels_children_are_as_guarded_as_the_parcel(app_db, db):
    """parcel had a policy from 0010 and its children did not, so a role denied
    the parcel could still read its zoning."""
    from tests.test_land_search import a_parcel
    a_parcel(db, spi="TEST\\RLS1", origin="REAL")
    db.commit()

    crown_db.clear_identity(app_db)
    assert app_db.execute("SELECT count(*) FROM parcel").fetchone()[0] == 0
    assert app_db.execute("SELECT count(*) FROM parcel_planning").fetchone()[0] == 0
    assert app_db.execute("SELECT count(*) FROM parcel_dwelling").fetchone()[0] == 0


def test_only_compliance_can_lift_a_suppression(app_db, db):
    """Everyone must be able to see a do-not-contact request. Lifting one is a
    compliance act."""
    from datetime import datetime, timezone

    from crown import suppression
    sid = suppression.record(db, scope="PERSON", identifier="A Person",
                             reason="opted out",
                             requested_at=datetime.now(timezone.utc),
                             recorded_by=user_id(db, "compliance@crown.local"),
                             source_of_request="EMAIL")
    db.commit()

    crown_db.set_identity(app_db, "", "AGENT")
    # everyone can see it — nobody is protected by a secret do-not-contact list
    assert app_db.execute("SELECT count(*) FROM contact_suppression").fetchone()[0] == 1

    # an agent's release affects no rows: row-level security filters it rather
    # than raising, which is the correct semantic and the reason the assertion
    # is about the data rather than about an exception
    app_db.execute(
        """UPDATE contact_suppression SET released_at = now(),
                  released_by = %s, released_reason = 'no'
           WHERE id = %s""", (user_id(db, "agent@crown.local"), sid))
    app_db.commit()
    assert db.execute(
        "SELECT released_at FROM contact_suppression WHERE id = %s", (sid,)
    ).fetchone()[0] is None

    # compliance can
    crown_db.set_identity(app_db, "", "COMPLIANCE")
    app_db.execute(
        """UPDATE contact_suppression SET released_at = now(),
                  released_by = %s, released_reason = 'opted back in, in writing'
           WHERE id = %s""", (user_id(db, "compliance@crown.local"), sid))
    app_db.commit()
    assert db.execute(
        "SELECT released_at FROM contact_suppression WHERE id = %s", (sid,)
    ).fetchone()[0] is not None


# ------------------------------------------------------------- the shortlist

def test_a_quiet_day_returns_a_quiet_shortlist(db):
    """An earlier version fell back to the whole ranking when nothing was new,
    turning a daily shortlist into yesterday's list with today's date on it."""
    from tests.test_market_signals import a_signal, an_actor

    developer = an_actor(db, "A Listed Developer")
    a_signal(db, developer, "ASX_ANNOUNCEMENT", lga="Whittlesea",
             locality="Donnybrook")
    # a ranking exists, but nobody is watching, so nothing is pending
    from crown import signals
    assert signals.hotspots(db)
    assert alerts.pending(db) == []
    assert alerts.daily_shortlist(db) == []


def test_the_shortlist_returns_places_with_something_new(db):
    from tests.test_alerts import watch
    from tests.test_market_signals import a_signal, an_actor

    watch(db, target="Whittlesea")
    developer = an_actor(db, "A Listed Developer")
    a_signal(db, developer, "ASX_ANNOUNCEMENT", lga="Whittlesea",
             locality="Donnybrook")
    alerts.run(db)

    shortlist = alerts.daily_shortlist(db)
    assert [h.locality for h in shortlist] == ["Donnybrook"]


# --------------------------------------------------------- the watcher lookup

def test_a_place_with_no_name_matches_no_watch(db):
    """An empty target would otherwise match every record with an unknown
    locality."""
    db.execute(
        """INSERT INTO watchlist (user_id, kind, target, label)
           VALUES (%s,'SUBURB','','blank')""", (user_id(db, "analyst@crown.local"),))
    assert alerts._watchers(db, None, None) == []
    assert alerts._watchers(db, "Wyndham", None) == []


def test_the_watcher_lookup_is_asked_once_per_place(db):
    """A detector otherwise asks this once per row."""
    from tests.test_alerts import watch
    watch(db, target="Wyndham")
    cache: dict = {}
    first = alerts._watchers(db, "Wyndham", "Tarneit", cache)
    assert first and len(cache) == 1
    assert alerts._watchers(db, "Wyndham", "Tarneit", cache) is first
