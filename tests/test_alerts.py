"""Alerts: what changed, for whom, and whether it is worth saying."""
from datetime import date, datetime, timedelta, timezone

import pytest

from crown import alerts
from tests.conftest import add_evidence, csrf, sign_in, user_id


def watch(db, user_email="analyst@crown.local", kind="LGA", target="Wyndham"):
    uid = user_id(db, user_email)
    return db.execute(
        """INSERT INTO watchlist (user_id, kind, target, label)
           VALUES (%s,%s,%s,%s) RETURNING id""", (uid, kind, target, target)
    ).fetchone()[0], uid


# ------------------------------------------------------------- dedupe

def test_the_same_thing_is_never_said_twice(db):
    """'We already told you that' is the difference between a product people
    read and one they filter to a folder.

    The promise is about what lands in the table, not about which of the two
    mechanisms held it back: a detector may skip a row it has already reported,
    or the unique key may refuse the insert. Both are correct; counting rows is
    the assertion that does not care which one fired.
    """
    watch(db)
    add_evidence(db, reference="TEST-AL-1", origin="REAL")

    first = alerts.run(db)
    after_first = db.execute("SELECT count(*) FROM alert").fetchone()[0]
    second = alerts.run(db)
    after_second = db.execute("SELECT count(*) FROM alert").fetchone()[0]

    assert len(first.created) >= 1
    assert after_first == len(first.created) + len(first.suppressed)
    assert second.created == []
    assert second.suppressed == []
    assert after_second == after_first


def test_a_repeat_is_counted_rather_than_written(db):
    """The backstop under the detectors: the same key twice writes once, and
    the second attempt is reported as already known rather than lost."""
    report = alerts.Raised()
    said = dict(kind="NEW_EVIDENCE", detected_event="an amendment moved stage",
                source_url="https://example.invalid/a", confidence="CONFIRMED",
                investment_impact="i", recommended_action="a",
                key_parts=("C123wynd", 1), report=report)

    first = alerts.raise_alert(db, **said)
    second = alerts.raise_alert(db, **said)

    assert first is not None
    assert second is None
    assert report.created == [first]
    assert report.duplicates == [alerts.dedupe_key("NEW_EVIDENCE", "C123wynd", 1)]
    assert db.execute("SELECT count(*) FROM alert").fetchone()[0] == 1


def test_a_duplicate_key_is_refused(db):
    import psycopg
    key = alerts.dedupe_key("NEW_EVIDENCE", "x", "y")
    db.execute(
        """INSERT INTO alert (kind, detected_event, source_url, confidence,
                   investment_impact, recommended_action, dedupe_key)
           VALUES ('NEW_EVIDENCE','e','u','CONFIRMED','i','a',%s)""", (key,))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(
            """INSERT INTO alert (kind, detected_event, source_url, confidence,
                       investment_impact, recommended_action, dedupe_key)
               VALUES ('NEW_EVIDENCE','e','u','CONFIRMED','i','a',%s)""", (key,))
    db.rollback()


# ------------------------------------------------------- confidence gating

def test_a_speculative_alert_is_recorded_and_withheld(db):
    """Rumours are never presented as facts — but the decision to stay quiet is
    on the record, so nobody wonders whether the system missed it."""
    watch(db)
    eid = add_evidence(db, reference="TEST-AL-2", evidence_class="HYPOTHESIS",
                       status="EXHIBITED", origin="REAL")
    db.execute("UPDATE evidence_record SET retrieval_method = 'SEARCH_RELAY', "
               "reliability = 'WEAK', evidence_class = 'UNKNOWN' WHERE id = %s", (eid,))

    report = alerts.run(db)
    assert report.created == [] or all(
        db.execute("SELECT confidence::text FROM alert WHERE id = %s", (a,)
                   ).fetchone()[0] in alerts.DELIVERABLE_CONFIDENCE
        for a in report.created)
    assert report.suppressed

    row = db.execute(
        """SELECT confidence::text, suppressed_reason, delivered_at FROM alert
           WHERE suppressed_reason IS NOT NULL LIMIT 1""").fetchone()
    assert row[0] == "SPECULATIVE"
    assert "never directly verified" in row[1]
    assert row[2] is None


def test_a_withheld_alert_cannot_also_be_delivered(db):
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation,
                       match="a_suppressed_alert_is_not_delivered"):
        db.execute(
            """INSERT INTO alert (kind, detected_event, source_url, confidence,
                       investment_impact, recommended_action, dedupe_key,
                       suppressed_reason, delivered_at)
               VALUES ('NEW_EVIDENCE','e','u','SPECULATIVE','i','a','k',
                       'withheld', now())""")
    db.rollback()


def test_confidence_uses_the_same_rule_as_a_recommendation(db):
    from crown import recommendation
    for klass, method in (("FACT", "DIRECT_FETCH"), ("FACT", "OPERATOR_CAPTURE"),
                          ("HYPOTHESIS", "DIRECT_FETCH"), ("UNKNOWN", "SEARCH_RELAY")):
        line = recommendation.EvidenceLine(
            "id", "C1", klass, "STRONG", method, "https://x",
            datetime.now(timezone.utc), datetime.now(timezone.utc))
        assert alerts.confidence_of_evidence(klass, method) == \
            recommendation.confidence_from([line])


# -------------------------------------------------------------- detectors

def test_an_alert_carries_everything_the_brief_asks_for(db):
    """Affected place, event, source, confidence, impact, next action."""
    watch(db)
    add_evidence(db, reference="TEST-AL-3", origin="REAL")
    alerts.run(db)

    row = db.execute(
        """SELECT lga, detected_event, source_url, confidence::text,
                  investment_impact, recommended_action
           FROM alert WHERE kind = 'NEW_EVIDENCE' AND suppressed_reason IS NULL
           LIMIT 1""").fetchone()
    assert all(field for field in row)
    assert "TEST-AL-3" in row[1]
    assert row[2].startswith("https://")


def test_nothing_is_raised_for_a_place_nobody_watches(db):
    add_evidence(db, reference="TEST-AL-4", lga="Melton", origin="REAL")
    report = alerts.run(db)
    assert not any(
        db.execute("SELECT lga FROM alert WHERE id = %s", (a,)).fetchone()[0] == "Melton"
        for a in report.created)


def test_a_public_acquisition_overlay_raises_an_avoid(db):
    from tests.test_land_search import a_parcel
    watch(db, target="Whittlesea")
    a_parcel(db, spi="TEST\\PAOALERT", overlays=("PAO",), origin="REAL")

    alerts.run(db)
    row = db.execute(
        """SELECT detected_event, investment_impact, recommended_action, confidence::text
           FROM alert WHERE kind = 'GOVERNMENT_ACQUISITION'""").fetchone()
    assert "Public Acquisition Overlay" in row[0]
    assert "compensation is at market value" in row[1]
    assert "Avoid" in row[2]
    assert row[3] == "CONFIRMED"


def test_stale_evidence_raises_a_re_verification_alert(db):
    """This is what makes last_verified_at more than a column."""
    eid = add_evidence(db, reference="TEST-AL-STALE", origin="REAL")
    db.execute(
        """UPDATE evidence_record
           SET last_verified_at = now() - interval '400 days' WHERE id = %s""", (eid,))

    alerts.run(db)
    row = db.execute(
        """SELECT detected_event, recommended_action FROM alert
           WHERE kind = 'STALE_EVIDENCE'""").fetchone()
    assert "last verified" in row[0]
    assert "re-retrieve" in row[1]


def test_a_relayed_record_goes_stale_far_sooner_than_a_gazetted_one(db):
    fact = add_evidence(db, reference="TEST-FRESH-FACT", origin="REAL")
    relay = add_evidence(db, reference="TEST-RELAY", origin="REAL")
    db.execute("""UPDATE evidence_record SET retrieval_method = 'SEARCH_RELAY',
                         reliability = 'WEAK', evidence_class = 'UNKNOWN',
                         last_verified_at = now() - interval '45 days'
                  WHERE id = %s""", (relay,))
    db.execute("""UPDATE evidence_record
                  SET last_verified_at = now() - interval '45 days' WHERE id = %s""",
               (fact,))

    stale = {r[1] for r in db.execute(
        "SELECT id, source_reference FROM stale_evidence").fetchall()}
    assert "TEST-RELAY" in stale          # 30-day shelf life
    assert "TEST-FRESH-FACT" not in stale  # 365-day shelf life


def test_a_data_rights_exception_raises_an_alert(db):
    """The register gap surfaces where someone will see it.

    The seeded register is complete since 0014, so the gap is opened here: the
    detector is what is under test.
    """
    db.execute("""UPDATE data_source SET register_confirmed_by = NULL
                  WHERE code = 'VIC_PLANNING_AMENDMENTS'""")

    alerts.run(db)
    row = db.execute(
        """SELECT detected_event, recommended_action FROM alert
           WHERE kind = 'DATA_RIGHTS_EXCEPTION'""").fetchone()
    assert "VIC_PLANNING_AMENDMENTS" in row[0]
    assert "register entry" in row[1]


def test_a_market_move_in_a_watched_place_is_reported(db):
    from tests.test_market_signals import a_signal, an_actor
    watch(db, target="Whittlesea")
    developer = an_actor(db, "A Listed Developer")
    a_signal(db, developer, "ASX_ANNOUNCEMENT", lga="Whittlesea",
             locality="Donnybrook", detail="acquired a 180ha holding")

    alerts.run(db)
    row = db.execute(
        """SELECT detected_event, confidence::text FROM alert
           WHERE kind = 'MARKET_SIGNAL'""").fetchone()
    assert "A Listed Developer" in row[0] and "180ha" in row[0]
    assert row[1] == "CONFIRMED"


def test_an_unnamed_actor_is_still_reported_without_the_name(db):
    from tests.test_market_signals import a_signal, an_actor
    watch(db, target="Whittlesea")
    member = an_actor(db, "A Member of Parliament", "ELECTED_OFFICIAL")
    a_signal(db, member, "PERMIT_APPLICATION", lga="Whittlesea",
             locality="Donnybrook", detail="a permit was lodged")

    alerts.run(db)
    events = [r[0] for r in db.execute(
        "SELECT detected_event FROM alert WHERE kind = 'MARKET_SIGNAL'").fetchall()]
    assert events
    assert all("A Member of Parliament" not in e for e in events)
    assert any("not named" in e or "unnamed" in e for e in events)


# ---------------------------------------------------------------- delivery

def test_delivery_marks_only_what_was_sent(db):
    watch(db)
    add_evidence(db, reference="TEST-AL-5", origin="REAL")
    report = alerts.run(db)
    db.commit()

    pending_before = alerts.pending(db)
    assert pending_before
    alerts.mark_delivered(db, [row[0] for row in pending_before])
    assert alerts.pending(db) == []

    # a withheld alert is never delivered by this path
    assert db.execute(
        """SELECT count(*) FROM alert
           WHERE suppressed_reason IS NOT NULL AND delivered_at IS NOT NULL"""
    ).fetchone()[0] == 0


def test_the_run_is_audited(db):
    watch(db)
    add_evidence(db, reference="TEST-AL-6", origin="REAL")
    alerts.run(db)
    assert db.execute(
        "SELECT count(*) FROM audit_event WHERE action = 'ALERT_RUN_COMPLETED'"
    ).fetchone()[0] == 1


# --------------------------------------------------------------- the page

def test_the_alerts_page_shows_pending_and_withheld(client, db):
    watch(db)
    add_evidence(db, reference="TEST-AL-7", origin="REAL")
    alerts.run(db)
    db.commit()

    sign_in(client, "analyst@crown.local")
    page = client.get("/alerts").get_data(as_text=True)
    assert "TEST-AL-7" in page
    assert "Withheld" in page


def test_an_analyst_can_run_a_pass_and_an_agent_cannot(client, db):
    watch(db)
    db.commit()
    sign_in(client, "agent@crown.local")
    assert client.post("/alerts/run", data=csrf(client)).status_code == 403

    sign_in(client, "analyst@crown.local")
    assert client.post("/alerts/run", data=csrf(client)).status_code == 302
