"""May we fetch this automatically?

The register answered who owns a source and whether an adviser signed it. It did
not answer the question that decides whether a crawler runs: do this publisher's
terms permit automated access at all? For most of what Crown asked about, they
do not.
"""
import psycopg
import pytest

from ingest import fetch, registry


def position(db, code):
    return db.execute(
        "SELECT automated_access::text FROM data_source WHERE code = %s", (code,)
    ).fetchone()[0]


# ---------------------------------------------- the position is on the record

def test_the_sources_crown_asked_about_are_registered_with_their_position(db):
    """Asked and answered once, rather than relitigated each time."""
    assert position(db, "GOOGLE_SEARCH") == "PROHIBITED"
    assert position(db, "SOCIAL_MARKETPLACE") == "PROHIBITED"
    assert position(db, "PROPERTY_PORTALS") == "PROHIBITED"
    assert position(db, "RP_DATA_SEAT") == "PROHIBITED"


def test_the_open_spatial_sources_permit_it(db):
    for code in ("VIC_PLANNING_AMENDMENTS", "VICMAP_PROPERTY", "VICMAP_PLANNING",
                 "VPA_PSP"):
        assert position(db, code) == "PERMITTED", code


def test_unread_terms_are_unknown_not_assumed_permitted(db):
    """The honest default blocks the crawler."""
    assert position(db, "LANDATA_TITLES") == "UNKNOWN"
    assert position(db, "VG_PROPERTY_SALES") == "UNKNOWN"


def test_taking_a_position_on_terms_is_attributed(db):
    with pytest.raises(psycopg.errors.CheckViolation,
                       match="a_position_on_terms_is_attributed"):
        db.execute("""UPDATE data_source SET automated_access = 'PERMITTED'
                      WHERE code = 'LANDATA_TITLES'""")
    db.rollback()


def test_marketplace_listings_are_recorded_as_personal_information(db):
    """Listings by private sellers identify people. Public accessibility is not
    consent, and the OAIC has said so jointly with eleven other regulators."""
    personal, notes = db.execute(
        """SELECT carries_personal_information, notes FROM data_source
           WHERE code = 'SOCIAL_MARKETPLACE'""").fetchone()
    assert personal is True
    assert "not a defence" in notes


# ------------------------------------------------- the register stops a crawler

def test_a_crawler_is_refused_where_terms_prohibit_it(db):
    """Two controls stack: the lane stops it being ingestible at all, and the
    terms position would stop the crawler even if it were."""
    with pytest.raises(registry.SourceNotIngestible):
        registry.resolve(db, "GOOGLE_SEARCH", automated=True)

    # prove the terms check bites on its own, on a source that is ingestible
    db.execute("""UPDATE data_source SET automated_access = 'PROHIBITED',
                         terms_reference = 'terms prohibit it',
                         terms_read_by = 'Crown AI review'
                  WHERE code = 'VIC_PLANNING_AMENDMENTS'""")
    with pytest.raises(registry.AutomatedAccessNotPermitted, match="prohibit"):
        registry.resolve(db, "VIC_PLANNING_AMENDMENTS", automated=True)


def test_a_crawler_is_refused_where_nobody_read_the_terms(db):
    """Even for a source that is otherwise fine to use."""
    db.execute("""UPDATE data_source
                  SET is_ingestible = true, register_confirmed_by = 'someone',
                      licence_reference = 'x', attribution_text = 'y'
                  WHERE code = 'VICMAP_PROPERTY'""")
    db.execute("""UPDATE data_source SET automated_access = 'UNKNOWN',
                         terms_reference = NULL, terms_read_by = NULL
                  WHERE code = 'VICMAP_PROPERTY'""")

    with pytest.raises(registry.AutomatedAccessNotPermitted, match="[Nn]obody has read"):
        registry.resolve(db, "VICMAP_PROPERTY", automated=True)


def test_a_person_with_a_browser_is_not_a_crawler(db):
    """Operator capture is ordinary permitted use and stays available."""
    db.execute("""UPDATE data_source SET automated_access = 'UNKNOWN',
                         terms_reference = NULL, terms_read_by = NULL
                  WHERE code = 'VIC_PLANNING_AMENDMENTS'""")

    with pytest.raises(registry.AutomatedAccessNotPermitted):
        registry.resolve(db, "VIC_PLANNING_AMENDMENTS", automated=True)

    # the capture path is unaffected
    assert registry.resolve(db, "VIC_PLANNING_AMENDMENTS", automated=False).code \
        == "VIC_PLANNING_AMENDMENTS"


def test_a_permitted_source_lets_the_crawler_through(db):
    assert registry.resolve(db, "VIC_PLANNING_AMENDMENTS", automated=True)


def test_an_ingestible_source_with_prohibited_terms_is_an_exception(db):
    from crown import reports
    db.execute("""UPDATE data_source
                  SET is_ingestible = true, register_confirmed_by = 'someone',
                      licence_reference = 'x', attribution_text = 'y',
                      carries_personal_information = false
                  WHERE code = 'GOOGLE_SEARCH' AND lane <> 'BLOCKED'""")
    # BLOCKED lane cannot be ingestible at all, which is the stronger control
    with pytest.raises(psycopg.errors.CheckViolation, match="ingestible_lane_only"):
        db.execute("""UPDATE data_source SET is_ingestible = true
                      WHERE code = 'GOOGLE_SEARCH'""")
    db.rollback()


# ------------------------------------------------------------------- robots.txt

def test_robots_txt_is_honoured(monkeypatch):
    """The register records what the licence says; robots.txt records what the
    operator asks of crawlers today. Both have to allow it."""
    class Response:
        status_code = 200
        text = "User-agent: *\nDisallow: /private/\n"

    monkeypatch.setattr(fetch.requests, "get", lambda *a, **k: Response())
    fetch._robots.clear()

    assert fetch.robots_allows("https://example.test/public/page")
    assert not fetch.robots_allows("https://example.test/private/page")


def test_a_disallowed_url_is_not_fetched(monkeypatch):
    class Response:
        status_code = 200
        text = "User-agent: *\nDisallow: /\n"

    monkeypatch.setattr(fetch.requests, "get", lambda *a, **k: Response())
    fetch._robots.clear()

    with pytest.raises(fetch.DisallowedByRobots):
        fetch.fetch("https://example.test/anything")


def test_an_unreachable_robots_file_does_not_block(monkeypatch):
    """The convention, and the register is the control that actually matters."""
    import requests as requests_module

    def boom(*a, **k):
        raise requests_module.RequestException("no robots.txt")

    monkeypatch.setattr(fetch.requests, "get", boom)
    fetch._robots.clear()
    assert fetch.robots_allows("https://example.test/anything")
