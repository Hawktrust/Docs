"""The prospecting query, against the land layer.

    land in Whittlesea between 20 and 150 acres, under investigation or draft,
    with or without a house, showing zoning and overlays

The parcels here are synthetic and flagged DEMO_SYNTHETIC. The point is the
query, which runs unchanged the day Vicmap Property is ingested.
"""
from datetime import date, datetime, timezone

import pytest

from crown import land
from tests.conftest import user_id

ACRE = land.ACRE_SQM


def a_parcel(conn, *, spi, lga="Whittlesea", locality="Donnybrook", acres=50.0,
             zone="UGZ", zone_name="Urban Growth Zone", overlays=("DPO2",),
             psp_status="DRAFT", psp_name="Donnybrook PSP", crown=False,
             lat=-37.52, lon=144.97, dwelling=None, origin="DEMO_SYNTHETIC"):
    from psycopg.types.json import Jsonb
    source_id = conn.execute(
        "SELECT id FROM data_source WHERE code = 'VIC_PLANNING_AMENDMENTS'").fetchone()[0]
    now = datetime.now(timezone.utc)
    parcel_id = conn.execute(
        """INSERT INTO parcel (spi, lga, locality, area_sqm, is_crown_land,
                   centroid_lat, centroid_lon, boundary, source_id, retrieved_at, origin)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (spi, lga, locality, acres * ACRE, crown, lat, lon,
         Jsonb({"type": "Point", "coordinates": [lon, lat]}), source_id, now, origin),
    ).fetchone()[0]
    conn.execute(
        """INSERT INTO parcel_planning (parcel_id, zone_code, zone_name, overlay_codes,
                   psp_name, psp_status, as_at, source_id, retrieved_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (parcel_id, zone, zone_name, list(overlays), psp_name, psp_status,
         date(2026, 9, 1), source_id, now))
    if dwelling is not None:
        conn.execute(
            """INSERT INTO parcel_dwelling (parcel_id, has_dwelling, observed_at,
                       source_id, method)
               VALUES (%s,%s,%s,%s,'IMAGERY')""",
            (parcel_id, dwelling, date(2026, 9, 1), source_id))
    return parcel_id


# ------------------------------------------------------------ the actual query

def test_the_whittlesea_query(db):
    """20 to 150 acres, under investigation or draft, zoning and overlays shown."""
    a_parcel(db, spi="TEST\\PP1234", acres=45.0, psp_status="DRAFT")
    a_parcel(db, spi="TEST\\PP1235", acres=120.0, psp_status="UNDER_INVESTIGATION")
    a_parcel(db, spi="TEST\\PP1236", acres=12.0, psp_status="DRAFT")      # too small
    a_parcel(db, spi="TEST\\PP1237", acres=400.0, psp_status="DRAFT")     # too big
    a_parcel(db, spi="TEST\\PP1238", acres=60.0, psp_status="APPROVED")   # wrong status
    a_parcel(db, spi="TEST\\PP1239", acres=60.0, lga="Hume")              # wrong council

    found = land.search(db, land.LandQuery(
        lga="Whittlesea", min_acres=20, max_acres=150,
        planning_status=["DRAFT", "UNDER_INVESTIGATION"], include_demo=True))

    assert {r.spi for r in found.results} == {"TEST\\PP1234", "TEST\\PP1235"}
    assert found.total_matched == 2

    biggest = found.results[0]
    assert biggest.acres == 120.0
    assert biggest.zone_code == "UGZ"
    assert biggest.overlays == ["DPO2"]
    assert biggest.psp_status == "UNDER_INVESTIGATION"
    assert "Whittlesea" in biggest.address and "Donnybrook" in biggest.address


def test_the_search_explains_what_it_did(db):
    found = land.search(db, land.LandQuery(lga="Whittlesea", min_acres=20,
                                           max_acres=150, zone_codes=["UGZ"]))
    assert "Whittlesea" in found.sql_explained
    assert "20 and 150 acres" in found.sql_explained
    assert "UGZ" in found.sql_explained
    assert "freehold only" in found.sql_explained


def test_an_empty_result_says_whether_it_is_the_filter_or_the_data(db):
    found = land.search(db, land.LandQuery(lga="Whittlesea"))
    assert found.is_empty_because_no_data


# ------------------------------------------------------------- the filters

def test_acreage_conversion_is_exact_at_the_boundary(db):
    a_parcel(db, spi="TEST\\EXACT20", acres=20.0)
    a_parcel(db, spi="TEST\\EXACT150", acres=150.0)
    found = land.search(db, land.LandQuery(min_acres=20, max_acres=150, include_demo=True))
    assert len(found.results) == 2
    assert {r.acres for r in found.results} == {20.0, 150.0}


def test_overlays_can_be_required_and_excluded(db):
    a_parcel(db, spi="TEST\\OV1", overlays=("DPO2", "DCPO3"))
    a_parcel(db, spi="TEST\\OV2", overlays=("BMO",))
    a_parcel(db, spi="TEST\\OV3", overlays=("DPO2", "LSIO"))

    wanted = land.search(db, land.LandQuery(any_overlay=["DPO2"], include_demo=True))
    assert {r.spi for r in wanted.results} == {"TEST\\OV1", "TEST\\OV3"}

    without_flood = land.search(db, land.LandQuery(
        any_overlay=["DPO2"], exclude_overlay=["LSIO"], include_demo=True))
    assert {r.spi for r in without_flood.results} == {"TEST\\OV1"}


def test_crown_land_is_excluded_unless_asked_for(db):
    a_parcel(db, spi="TEST\\FREEHOLD", crown=False)
    a_parcel(db, spi="TEST\\CROWN", crown=True)

    assert {r.spi for r in land.search(
        db, land.LandQuery(include_demo=True)).results} == {"TEST\\FREEHOLD"}
    assert len(land.search(
        db, land.LandQuery(include_crown_land=True, include_demo=True)).results) == 2


def test_demo_parcels_are_excluded_from_a_real_search(db):
    a_parcel(db, spi="TEST\\DEMO", origin="DEMO_SYNTHETIC")
    a_parcel(db, spi="TEST\\REAL", origin="REAL")
    found = land.search(db, land.LandQuery())
    assert {r.spi for r in found.results} == {"TEST\\REAL"}


# --------------------------------------------- what the data cannot answer

def test_an_unobserved_dwelling_is_unknown_not_no(db):
    """Modelling this as a boolean on parcel would make every parcel read
    'no dwelling' the moment the table was created — a lie with a default."""
    a_parcel(db, spi="TEST\\NOOBS", dwelling=None)
    a_parcel(db, spi="TEST\\HASHOUSE", dwelling=True)
    a_parcel(db, spi="TEST\\VACANT", dwelling=False)

    by_spi = {r.spi: r.dwelling for r in
              land.search(db, land.LandQuery(include_demo=True)).results}
    assert by_spi["TEST\\NOOBS"] == "UNKNOWN"
    assert by_spi["TEST\\HASHOUSE"] == "YES"
    assert by_spi["TEST\\VACANT"] == "NO"


def test_filtering_on_dwelling_says_the_result_is_partial(db):
    a_parcel(db, spi="TEST\\NOOBS", dwelling=None)
    a_parcel(db, spi="TEST\\VACANT", dwelling=False)

    found = land.search(db, land.LandQuery(has_dwelling=False, include_demo=True))
    assert {r.spi for r in found.results} == {"TEST\\VACANT"}
    # and it does not pretend the answer is complete
    assert "has_dwelling" in found.unanswerable
    assert "no registered source" in found.unanswerable["has_dwelling"]


def test_the_filters_with_no_source_are_named(db):
    """Asking for one is a question the data cannot answer, not an error."""
    for key in ("has_dwelling", "on_market", "off_market", "owner"):
        assert key in land.UNSOURCED_FILTERS
    assert "Gate 0" in land.UNSOURCED_FILTERS["owner"]
    assert "CROWN_INBOX" in land.UNSOURCED_FILTERS["off_market"]


def test_no_result_carries_an_owner(db):
    """The cadastre has none, and the search does not imply otherwise."""
    a_parcel(db, spi="TEST\\NOOWNER")
    result = land.search(db, land.LandQuery(include_demo=True)).results[0]
    assert not hasattr(result, "owner")
    assert "TEST\\NOOWNER" in result.address


# ---------------------------------------------------------------- proximity

def test_nearby_finds_neighbouring_parcels_by_distance(db):
    target = a_parcel(db, spi="TEST\\CENTRE", lat=-37.5200, lon=144.9700)
    a_parcel(db, spi="TEST\\CLOSE", lat=-37.5205, lon=144.9705)     # ~70m
    a_parcel(db, spi="TEST\\MEDIUM", lat=-37.5290, lon=144.9700)    # ~1km
    a_parcel(db, spi="TEST\\FAR", lat=-37.7000, lon=145.2000)       # ~30km

    rows = land.nearby(db, target, radius_metres=2000)
    spis = [row[1] for row in rows]
    assert spis[:2] == ["TEST\\CLOSE", "TEST\\MEDIUM"]
    assert "TEST\\FAR" not in spis
    assert rows[0][4] < rows[1][4]           # ordered by distance


def test_nearby_is_honest_about_being_a_proxy(db):
    doc = land.nearby.__doc__ or ""
    assert "adjacency" in doc
    assert "PostGIS" in doc


# ------------------------------------------------------------------ the page

def test_the_search_page_renders_and_says_why_it_is_empty(client, db):
    from tests.conftest import sign_in
    db.commit()
    sign_in(client, "analyst@crown.local")
    page = client.get("/land?lga=Whittlesea&min_acres=20&max_acres=150"
                      "&status=DRAFT").get_data(as_text=True)
    assert "No parcels are loaded" in page
    assert "Vicmap Property" in page
    assert "No owner is shown" in page


def test_the_page_lists_matches_when_there_are_some(client, db):
    from tests.conftest import sign_in
    a_parcel(db, spi="TEST\\PAGE1", acres=88.0, origin="REAL")
    db.commit()
    sign_in(client, "analyst@crown.local")
    page = client.get("/land?lga=Whittlesea&min_acres=20&max_acres=150").get_data(as_text=True)
    assert "TEST\\PAGE1" in page
    assert "88.0" in page
    assert "UGZ" in page and "DPO2" in page
