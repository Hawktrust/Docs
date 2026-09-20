"""The data rights register, and the act of signing an entry.

Adopting a source into the register is not permission to ingest from it. The
register carries register_confirmed_by, described in the schema as NULL until a
named adviser signs, and scripts/confirm_source.py is that act.
"""
import pytest

from ingest import registry
from scripts import confirm_source


def codes(db):
    return {r[0]: r[1] for r in db.execute(
        "SELECT code, is_ingestible FROM data_source").fetchall()}


def test_the_lane_b_stack_is_in_the_register(db):
    present = codes(db)
    for code in ("VICMAP_PROPERTY", "VICMAP_PLANNING", "VPA_PSP"):
        assert code in present, f"{code} was adopted but is not in the register"


def test_adopting_a_source_does_not_make_it_ingestible(db):
    """Being documented and being permitted are different things."""
    present = codes(db)
    for code in ("VICMAP_PROPERTY", "VICMAP_PLANNING", "VPA_PSP",
                 "VG_PROPERTY_SALES", "LANDATA_TITLES"):
        assert present[code] is False
        with pytest.raises(registry.SourceNotIngestible):
            registry.resolve(db, code)


def test_the_titles_register_is_recorded_as_licensed_not_open(db):
    """The only lawful route to a registered proprietor, and it is Lane A."""
    lane, notes = db.execute(
        "SELECT lane::text, notes FROM data_source WHERE code = 'LANDATA_TITLES'"
    ).fetchone()
    assert lane == "A_LICENSED"
    # and the note keeps the two questions apart
    assert "HOLD" in notes and "USE" in notes and "APP 7" in notes


def test_signing_an_entry_turns_the_source_on_and_records_who(db, database, monkeypatch):
    owner_dsn, _ = database
    assert confirm_source.main(
        ["VICMAP_PROPERTY", "--adviser", "A. Named Adviser", "--dsn", owner_dsn]) == 0

    row = db.execute(
        """SELECT is_ingestible, register_confirmed_by, register_confirmed_at
           FROM data_source WHERE code = 'VICMAP_PROPERTY'""").fetchone()
    assert row[0] is True
    assert row[1] == "A. Named Adviser"
    assert row[2] is not None

    # and now the pipeline will accept it
    assert registry.resolve(db, "VICMAP_PROPERTY").code == "VICMAP_PROPERTY"


def test_signing_is_audited(db, database):
    owner_dsn, _ = database
    confirm_source.main(["VPA_PSP", "--adviser", "A. Named Adviser", "--dsn", owner_dsn])

    row = db.execute(
        """SELECT new_state FROM audit_event
           WHERE action = 'SOURCE_REGISTER_CONFIRMED'""").fetchone()
    assert row[0]["code"] == "VPA_PSP"
    assert row[0]["confirmed_by"] == "A. Named Adviser"


def test_a_blocked_source_cannot_be_signed_on(db, database, capsys):
    """RP Data has no platform agreement. Signing it would not create one."""
    owner_dsn, _ = database
    assert confirm_source.main(
        ["RP_DATA_SEAT", "--adviser", "Someone", "--dsn", owner_dsn]) == 2
    assert db.execute(
        "SELECT is_ingestible FROM data_source WHERE code = 'RP_DATA_SEAT'"
    ).fetchone()[0] is False


def test_a_source_missing_its_licence_wording_cannot_be_signed_on(db, database):
    """A confirmation confirms the licence and attribution. There must be some."""
    owner_dsn, _ = database
    assert confirm_source.main(
        ["VG_PROPERTY_SALES", "--adviser", "Someone", "--dsn", owner_dsn]) == 2


def test_signing_twice_is_refused(db, database):
    owner_dsn, _ = database
    assert confirm_source.main(
        ["VICMAP_PLANNING", "--adviser", "First", "--dsn", owner_dsn]) == 0
    assert confirm_source.main(
        ["VICMAP_PLANNING", "--adviser", "Second", "--dsn", owner_dsn]) == 1
    assert db.execute(
        "SELECT register_confirmed_by FROM data_source WHERE code = 'VICMAP_PLANNING'"
    ).fetchone()[0] == "First"


def test_an_unsigned_ingestible_source_shows_as_an_exception(db, database):
    """The one source already in use is unsigned, and the report says so."""
    from crown import reports
    codes_with_exceptions = {row[0] for row in reports.data_rights_exceptions(db)}
    assert "VIC_PLANNING_AMENDMENTS" in codes_with_exceptions

    owner_dsn, _ = database
    confirm_source.main(["VICMAP_PROPERTY", "--adviser", "A. Named Adviser",
                         "--dsn", owner_dsn])
    # newly signed sources do not add exceptions
    assert "VICMAP_PROPERTY" not in {
        row[0] for row in reports.data_rights_exceptions(db)}


# ------------------------------------ holding a source and using it differ

def test_a_source_that_identifies_people_is_marked_as_such(db):
    flagged = dict(db.execute(
        "SELECT code, carries_personal_information FROM data_source").fetchall())
    assert flagged["LANDATA_TITLES"] is True
    assert flagged["VG_PROPERTY_SALES"] is True
    # the open spatial sources do not identify anybody
    for code in ("VICMAP_PROPERTY", "VICMAP_PLANNING", "VPA_PSP",
                 "VIC_PLANNING_AMENDMENTS"):
        assert flagged[code] is False


def test_the_titles_register_needs_an_agreement_not_a_link(db, database):
    owner_dsn, _ = database
    assert confirm_source.main(
        ["LANDATA_TITLES", "--adviser", "Hawk", "--dsn", owner_dsn]) == 2
    assert db.execute(
        "SELECT is_ingestible FROM data_source WHERE code = 'LANDATA_TITLES'"
    ).fetchone()[0] is False


def test_an_agreement_alone_is_not_enough_for_personal_information(db, database):
    """A licence answers whether Crown may hold it, not whether it may use it."""
    owner_dsn, _ = database
    assert confirm_source.main(
        ["LANDATA_TITLES", "--adviser", "Hawk", "--dsn", owner_dsn,
         "--agreement", "LUV-2026-0417"]) == 2
    assert db.execute(
        "SELECT is_ingestible FROM data_source WHERE code = 'LANDATA_TITLES'"
    ).fetchone()[0] is False


def test_both_stated_deliberately_does_turn_it_on(db, database):
    owner_dsn, _ = database
    assert confirm_source.main(
        ["LANDATA_TITLES", "--adviser", "Hawk", "--dsn", owner_dsn,
         "--agreement", "LUV-2026-0417 executed 2026-09-15",
         "--privacy-basis", "APP 7(3); opt-out on every communication"]) == 0

    row = db.execute(
        """SELECT is_ingestible, licence_reference, privacy_basis
           FROM data_source WHERE code = 'LANDATA_TITLES'""").fetchone()
    assert row[0] is True
    assert row[1] == "LUV-2026-0417 executed 2026-09-15"   # the link was replaced
    assert "APP 7" in row[2]


def test_the_database_refuses_to_drop_the_basis_afterwards(db, database):
    import psycopg
    owner_dsn, _ = database
    confirm_source.main(
        ["LANDATA_TITLES", "--adviser", "Hawk", "--dsn", owner_dsn,
         "--agreement", "LUV-2026-0417", "--privacy-basis", "APP 7(3)"])

    with pytest.raises(psycopg.errors.CheckViolation,
                       match="personal_information_needs_a_basis"):
        db.execute(
            "UPDATE data_source SET privacy_basis = NULL WHERE code = 'LANDATA_TITLES'")
    db.rollback()


def test_the_basis_is_recorded_in_the_audit_trail(db, database):
    owner_dsn, _ = database
    confirm_source.main(
        ["LANDATA_TITLES", "--adviser", "Hawk", "--dsn", owner_dsn,
         "--agreement", "LUV-2026-0417", "--privacy-basis", "APP 7(3)"])

    state = db.execute(
        """SELECT new_state FROM audit_event
           WHERE action = 'SOURCE_REGISTER_CONFIRMED'""").fetchone()[0]
    assert state["agreement"] == "LUV-2026-0417"
    assert state["privacy_basis"] == "APP 7(3)"


def test_a_personal_source_cannot_be_switched_on_without_a_basis_at_all(db):
    """The exception report has a branch for this, and the constraint means it
    should never fire: the state is unreachable rather than merely reported."""
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation,
                       match="personal_information_needs_a_basis"):
        db.execute("""UPDATE data_source
                      SET is_ingestible = true, register_confirmed_by = 'someone',
                          licence_reference = 'LUV-2026-0417',
                          attribution_text = 'Contains information from the Victorian Titles Register.'
                      WHERE code = 'LANDATA_TITLES'""")
    db.rollback()


def test_a_lane_c_source_cannot_be_switched_on_either(db):
    """Valuer General sales sit in Lane C until the licence is read, and Lane C
    is not ingestible in bulk at all."""
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation, match="ingestible_lane_only"):
        db.execute("""UPDATE data_source SET is_ingestible = true
                      WHERE code = 'VG_PROPERTY_SALES'""")
    db.rollback()
