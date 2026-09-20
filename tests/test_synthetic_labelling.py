"""Acceptance criterion 7: every synthetic buyer record renders with its
DEMO / SYNTHETIC DATA label and is excluded from any count shown to a human."""
from crown import matching, opportunity
from tests.conftest import (SEEDED_MANDATE_COUNT, add_evidence, sign_in,
                            user_id)

LABEL = "DEMO / SYNTHETIC DATA"


def test_every_seeded_mandate_is_flagged_synthetic(db):
    rows = db.execute("SELECT buyer_label, origin::text FROM buyer_mandate").fetchall()
    assert len(rows) == SEEDED_MANDATE_COUNT
    for label, origin in rows:
        assert origin == "DEMO_SYNTHETIC"
        assert label.startswith(LABEL), f"{label} does not carry the label"


def test_the_origin_column_has_no_default_so_it_must_be_stated(db):
    """The schema refuses a mandate that does not say what it is."""
    import psycopg
    import pytest
    with pytest.raises(psycopg.errors.NotNullViolation):
        db.execute(
            """INSERT INTO buyer_mandate (buyer_label, geographies, asset_types, mandate_date)
               VALUES ('unstated', '{Wyndham}', '{RESIDENTIAL_LAND}', '2026-01-01')""")
    db.rollback()


def test_synthetic_records_are_excluded_from_the_real_view(db):
    assert db.execute(
        "SELECT count(*) FROM buyer_mandate").fetchone()[0] == SEEDED_MANDATE_COUNT
    assert db.execute("SELECT count(*) FROM buyer_mandate_real").fetchone()[0] == 0


def test_the_count_shown_to_a_human_excludes_them(client, db):
    db.commit()
    sign_in(client, "analyst@crown.local")
    page = client.get("/mandates").get_data(as_text=True)

    # the figure presented as the count of mandates is the real one
    assert "<strong>0</strong> real mandates" in page
    # and the demo records are visible, but described as what they are
    assert f"{SEEDED_MANDATE_COUNT} records exist in total" in page
    assert f"{SEEDED_MANDATE_COUNT} marked DEMO / SYNTHETIC DATA are excluded" in page


def test_every_synthetic_record_renders_with_its_label(client, db):
    db.commit()
    sign_in(client, "analyst@crown.local")
    page = client.get("/mandates").get_data(as_text=True)
    assert page.count('class="synthetic"') == SEEDED_MANDATE_COUNT


def test_synthetic_mandates_are_labelled_wherever_they_appear(client, db):
    """Not only on the mandate list: on the ranked matches and in the queue too."""
    add_evidence(db, reference="TEST-C050wynd")
    owner = user_id(db, "analyst@crown.local")
    oid = opportunity.refresh(db, owner)[0].opportunity_id
    matching.rank(db, oid)
    db.commit()

    sign_in(client, "analyst@crown.local")

    detail = client.get(f"/opportunities/{oid}").get_data(as_text=True)
    assert detail.count('class="synthetic"') == SEEDED_MANDATE_COUNT

    queue = client.get("/queue").get_data(as_text=True)
    assert 'class="synthetic"' in queue


def test_the_seed_file_matches_the_count_the_tests_assume():
    """Keeps SEEDED_MANDATE_COUNT from drifting silently when the seed changes."""
    import pathlib
    seed = pathlib.Path(__file__).resolve().parent.parent / "seeds" / "002_buyer_mandates.sql"
    assert seed.read_text().count("DEMO / SYNTHETIC DATA") == SEEDED_MANDATE_COUNT


def test_the_new_lga_has_mandates_of_its_own(db):
    """Whittlesea joined the scope on 2026-09-20; without mandates covering it,
    every match there would be excluded for geography."""
    covering = db.execute(
        "SELECT count(*) FROM buyer_mandate WHERE 'Whittlesea' = ANY(geographies)"
    ).fetchone()[0]
    assert covering >= 3
