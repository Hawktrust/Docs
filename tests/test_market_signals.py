"""Where money is moving, and who may be named saying so."""
from datetime import date, datetime, timedelta, timezone

import psycopg
import pytest

from crown import signals

TODAY = date(2026, 9, 20)


def an_actor(conn, name, kind="LISTED_DEVELOPER", asx=None):
    publishable = kind != "ELECTED_OFFICIAL"
    return conn.execute(
        """INSERT INTO market_actor (name, normalised, kind, asx_code, publishable_by_name)
           VALUES (%s,%s,%s,%s,%s) RETURNING id""",
        (name, name.strip().lower(), kind, asx, publishable)).fetchone()[0]


def a_signal(conn, actor_id, kind, lga="Whittlesea", locality="Donnybrook",
             days_ago=30, detail="observed", origin="REAL"):
    source_id = conn.execute(
        "SELECT id FROM data_source WHERE code = 'VIC_PLANNING_AMENDMENTS'").fetchone()[0]
    return signals.record(
        conn, actor_id=actor_id, signal_kind=kind, lga=lga, locality=locality,
        observed_at=TODAY - timedelta(days=days_ago), source_id=source_id,
        source_url="https://example.invalid/announcement",
        retrieved_at=datetime.now(timezone.utc), detail=detail, origin=origin)


# ------------------------------------------------------------ action vs opinion

def test_a_disclosed_acquisition_outranks_a_hotspot_list(db):
    """By the time a suburb reaches a hotspot list, the move has happened."""
    developer = an_actor(db, "A Listed Developer", "LISTED_DEVELOPER", asx="XYZ")
    advocate = an_actor(db, "A Buyer Advocate", "BUYER_AGENT")

    a_signal(db, developer, "ASX_ANNOUNCEMENT", locality="Donnybrook")
    a_signal(db, advocate, "PUBLIC_COMMENTARY", locality="Wollert")

    ranked = signals.hotspots(db, as_of=TODAY)
    assert ranked[0].locality == "Donnybrook"
    assert ranked[0].score > ranked[1].score * 4


def test_every_score_can_be_taken_apart(db):
    """A ranking nobody can interrogate is a ranking nobody should act on."""
    developer = an_actor(db, "A Listed Developer")
    a_signal(db, developer, "ASX_ANNOUNCEMENT", detail="acquired 180ha", days_ago=0)
    a_signal(db, developer, "PERMIT_APPLICATION", detail="lodged", days_ago=10)

    spot = signals.hotspots(db, as_of=TODAY)[0]
    assert spot.signal_count == 2
    assert spot.by_kind() == {"ASX_ANNOUNCEMENT": 1, "PERMIT_APPLICATION": 1}
    for c in spot.contributions:
        assert c.source_url and c.detail
        assert c.score == pytest.approx(c.weight * c.recency)
    assert spot.score == pytest.approx(sum(c.score for c in spot.contributions), abs=1e-4)


def test_an_old_signal_counts_for_less(db):
    developer = an_actor(db, "A Listed Developer")
    a_signal(db, developer, "ASX_ANNOUNCEMENT", locality="Recent", days_ago=10)
    a_signal(db, developer, "ASX_ANNOUNCEMENT", locality="Old", days_ago=700)

    by_place = {h.locality: h.score for h in signals.hotspots(db, as_of=TODAY)}
    assert by_place["Recent"] > by_place["Old"] * 5


def test_a_signal_past_the_horizon_counts_for_nothing(db):
    developer = an_actor(db, "A Listed Developer")
    a_signal(db, developer, "ASX_ANNOUNCEMENT", days_ago=900)
    assert signals.hotspots(db, as_of=TODAY)[0].score == 0.0


# ------------------------------------------------- elected officials stay unnamed

def test_an_elected_official_cannot_be_marked_publishable(db):
    with pytest.raises(psycopg.errors.CheckViolation,
                       match="elected_officials_are_never_named"):
        db.execute(
            """INSERT INTO market_actor (name, normalised, kind, publishable_by_name)
               VALUES ('A Member','a member','ELECTED_OFFICIAL', true)""")
    db.rollback()


def test_an_elected_official_counts_but_is_never_named(db):
    """The aggregate is a fair read of a public register. A named politician in
    a prospecting brief is not."""
    member = an_actor(db, "A Member of Parliament", "ELECTED_OFFICIAL")
    a_signal(db, member, "INTEREST_REGISTER", detail="declared a property interest")

    spot = signals.hotspots(db, as_of=TODAY)[0]
    assert spot.signal_count == 1
    assert spot.score > 0                      # it counted
    assert spot.named_actors == []             # and is not attributable
    assert spot.unnamed_count == 1
    assert all(c.actor_name is None for c in spot.contributions)


def test_the_publishable_view_excludes_them(db):
    member = an_actor(db, "A Member of Parliament", "ELECTED_OFFICIAL")
    developer = an_actor(db, "A Listed Developer")
    a_signal(db, member, "INTEREST_REGISTER")
    a_signal(db, developer, "ASX_ANNOUNCEMENT")

    names = {r[0] for r in db.execute(
        "SELECT name FROM actor_signal_publishable").fetchall()}
    assert names == {"A Listed Developer"}


def test_a_register_of_interests_signal_is_weighted_weakly(db):
    weights = signals.active_weights(db)
    assert weights["INTEREST_REGISTER"] < weights["PERMIT_APPLICATION"]
    assert weights["PUBLIC_COMMENTARY"] == min(weights.values())
    assert weights["ASX_ANNOUNCEMENT"] == max(weights.values())


# ------------------------------------------------------------------ provenance

def test_a_signal_without_a_source_url_is_a_rumour_and_is_refused(db):
    developer = an_actor(db, "A Listed Developer")
    source_id = db.execute(
        "SELECT id FROM data_source WHERE code = 'VIC_PLANNING_AMENDMENTS'").fetchone()[0]
    with pytest.raises(ValueError, match="rumour"):
        signals.record(db, actor_id=developer, signal_kind="ASX_ANNOUNCEMENT",
                       lga="Whittlesea", locality="Donnybrook", observed_at=TODAY,
                       source_id=source_id, source_url="",
                       retrieved_at=datetime.now(timezone.utc), detail="x")


def test_the_same_observation_twice_is_one_signal(db):
    developer = an_actor(db, "A Listed Developer")
    a_signal(db, developer, "ASX_ANNOUNCEMENT", days_ago=5)
    with pytest.raises(psycopg.errors.UniqueViolation):
        a_signal(db, developer, "ASX_ANNOUNCEMENT", days_ago=5)
    db.rollback()


def test_every_signal_is_audited(db):
    developer = an_actor(db, "A Listed Developer")
    a_signal(db, developer, "ASX_ANNOUNCEMENT")
    assert db.execute(
        "SELECT count(*) FROM audit_event WHERE action = 'MARKET_SIGNAL_RECORDED'"
    ).fetchone()[0] == 1


def test_changing_the_signal_weights_is_audited(db):
    """Same discipline as the match weights: the numbers that decide a ranking
    are configuration, and every change to them is on the record."""
    before = db.execute(
        """SELECT count(*) FROM audit_event
           WHERE object_table = 'signal_weight_config'""").fetchone()[0]
    db.execute("""UPDATE signal_weight_config SET weight = 0.5
                  WHERE signal_kind = 'PUBLIC_COMMENTARY' AND version = 1""")
    after = db.execute(
        """SELECT action, new_state FROM audit_event
           WHERE object_table = 'signal_weight_config' ORDER BY id DESC LIMIT 1"""
    ).fetchone()
    assert after[0] == "SIGNAL_WEIGHTS_UPDATE"
    assert float(after[1]["weight"]) == 0.5
    assert db.execute(
        """SELECT count(*) FROM audit_event
           WHERE object_table = 'signal_weight_config'""").fetchone()[0] > before


def test_demo_signals_are_excluded_from_a_real_ranking(db):
    developer = an_actor(db, "A Listed Developer")
    a_signal(db, developer, "ASX_ANNOUNCEMENT", locality="Real", origin="REAL")
    a_signal(db, developer, "ASX_ANNOUNCEMENT", locality="Demo",
             origin="DEMO_SYNTHETIC")
    assert {h.locality for h in signals.hotspots(db, as_of=TODAY)} == {"Real"}


# ----------------------------------------------- government intent is already here

def test_government_acquisition_intent_comes_from_the_overlay_already_held(db):
    """A PAO is a planning control marking land proposed for acquisition. It
    needs no new source — it is in the overlay list on every parcel."""
    from tests.test_land_search import a_parcel

    a_parcel(db, spi="TEST\\PAO1", acres=40, overlays=("PAO", "DPO2"), origin="REAL")
    a_parcel(db, spi="TEST\\NOPAO", acres=40, overlays=("DPO2",), origin="REAL")

    rows = signals.government_intent(db, lga="Whittlesea")
    assert [r[1] for r in rows] == ["TEST\\PAO1"]
    assert "PAO" in rows[0][6]
