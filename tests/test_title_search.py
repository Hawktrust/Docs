"""The lawful route to a registered proprietor, and the two gates on it.

The question behind migration 0031 was why the commercial platforms can show an
owner's name and Crown cannot. The answer is that they hold commercial licences
to state land registry data, and the route open to Crown is the same register
searched one property at a time, under its own licence, for a stated purpose.

seeds/003 has recorded that since 2026-09-20, in a note, which made the sequence
— read the licence, settle the APP 7 basis, then search — a thing a person had
to remember. These tests are what makes it the table's own precondition.
"""
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from crown import db as crown_db
from crown import retention, title
from tests.conftest import user_id

LICENCE = "https://www.landata.online/title-search/"
NOW = datetime.now(timezone.utc)
# Fourteen months ago, which is past the twelve-month period. Dated at the
# point the result is recorded, because the freeze trigger refuses a
# backdated one — a test that had to defeat a control to set itself up
# would have been testing a different system.
LONG_AGO = NOW - timedelta(days=430)


def a_parcel(db, spi="TEST-1\\PS123456"):
    source = db.execute(
        "SELECT id FROM data_source WHERE code = 'VICMAP_PROPERTY'").fetchone()[0]
    return db.execute(
        """INSERT INTO parcel (spi, lga, area_sqm, source_id, retrieved_at, origin)
           VALUES (%s, 'Wyndham', 40000, %s, now(), 'DEMO_SYNTHETIC')
           RETURNING id""", (spi, source)).fetchone()[0]


def read_the_licence(db, by="Test suite"):
    """Satisfy gate one, and only gate one."""
    db.execute("""UPDATE data_source
                  SET terms_reference = %s, terms_read_by = %s, terms_read_at = now()
                  WHERE code = 'LANDATA_TITLES'""", (LICENCE, by))


def settle_the_basis(db):
    """Satisfy gate two. Separate function because it is separate work."""
    db.execute("""UPDATE data_source
                  SET privacy_basis = 'test fixture: not a position Crown holds'
                  WHERE code = 'LANDATA_TITLES'""")


def a_search(db, **kw):
    kw.setdefault("searched_for", "TEST-1\\PS123456")
    kw.setdefault("purpose", "OPPORTUNITY_SHORTLIST")
    kw.setdefault("fee_cents", 2920)
    kw.setdefault("requested_by", user_id(db, "analyst@crown.local"))
    if "parcel_id" not in kw and "opportunity_id" not in kw:
        kw["parcel_id"] = a_parcel(db)
    return title.request(db, **kw)


# ------------------------------------------------- what ships, and what does not

def test_the_path_ships_with_both_gates_closed(db):
    """0031 builds the route and asserts nothing about the licence. This build
    environment cannot reach landata.online, and a register entry claiming a
    position nobody read would be the exact failure the provenance model exists
    to prevent."""
    entry = db.execute(
        """SELECT terms_read_by, privacy_basis, is_ingestible
           FROM data_source WHERE code = 'LANDATA_TITLES'""").fetchone()
    assert entry == (None, None, False), (
        "the Landata entry now claims a licence or privacy position. If a "
        "person read the licence, their name belongs in terms_read_by and this "
        "test should name them; if nobody did, nothing may assert it.")


def test_the_outstanding_work_is_a_list_and_not_a_surprise(db):
    """The gates refuse with a sentence at the moment somebody tries. This is
    the same information beforehand."""
    assert title.blockers(db) == [
        "nobody has read LANDATA_TITLES's licence. No search can be recorded "
        "until terms_read_by names who read it.",
        "LANDATA_TITLES has no privacy basis on file. A search can be recorded "
        "and paid for; the owner's name cannot be stored.",
        "no named adviser has signed LANDATA_TITLES's register entry.",
    ]


def test_the_readiness_view_names_the_first_blocker(db):
    rows = {r[0]: r for r in title.readiness(db)}
    assert "LANDATA_TITLES" in rows
    assert rows["LANDATA_TITLES"][6] == (
        "nobody has read the licence: no search can be recorded")


def test_the_cadastre_is_not_a_registry(db):
    """Vicmap Property is in the register and carries no owner at all. Asking
    this module to search it should say so rather than fail later."""
    with pytest.raises(title.TitleSearchRefused, match="not a land registry"):
        title.blockers(db, "VICMAP_PROPERTY")


# ------------------------------------------------------- gate one: the licence

def test_no_search_before_somebody_has_read_the_licence(db):
    with pytest.raises(psycopg.errors.RaiseException, match="nobody has read"):
        a_search(db)
    db.rollback()


def test_the_refusal_says_what_to_do(db):
    """A control that refuses without naming the remedy gets worked around."""
    with pytest.raises(psycopg.errors.RaiseException) as raised:
        a_search(db)
    assert "terms_read_by" in str(raised.value)
    db.rollback()


def test_a_search_is_recordable_once_the_licence_is_read(db):
    read_the_licence(db)
    search_id = a_search(db)
    assert db.execute("SELECT fee_cents FROM title_search WHERE id = %s",
                      (search_id,)).fetchone()[0] == 2920


def test_a_direct_fetch_is_automated_access_whatever_it_is_called(db):
    """automated_access is UNKNOWN on this source, which blocks the crawler. A
    row labelled DIRECT_FETCH would be automated retrieval wearing a different
    word for it."""
    read_the_licence(db)
    with pytest.raises(psycopg.errors.RaiseException, match="automated access"):
        a_search(db, retrieval_method="DIRECT_FETCH")
    db.rollback()


def test_an_operator_capture_is_ordinary_permitted_use(db):
    """A person logging into the portal is not the crawler, and the gate does
    not pretend otherwise."""
    read_the_licence(db)
    assert a_search(db, retrieval_method="OPERATOR_CAPTURE")


# ---------------------------------------------------------- gate two: the name

def test_the_fee_and_the_folio_are_storable_without_a_basis(db):
    """Which is the point of two gates rather than one: the search can proceed
    while the privacy question is still open, and what it stores is a fact about
    land."""
    read_the_licence(db)
    search_id = a_search(db)
    title.record_result(db, search_id, retrieved_at=NOW,
                        volume_folio="12345/678", is_company=True)
    assert db.execute("SELECT volume_folio FROM title_search WHERE id = %s",
                      (search_id,)).fetchone()[0] == "12345/678"


def test_the_name_waits_for_a_basis(db):
    read_the_licence(db)
    search_id = a_search(db)
    with pytest.raises(psycopg.errors.RaiseException, match="no privacy basis"):
        title.record_result(db, search_id, retrieved_at=NOW,
                            volume_folio="12345/678",
                            registered_proprietor="A. Landholder",
                            proprietor_address="1 Example Street")
    db.rollback()


def test_the_name_lands_once_the_basis_is_on_file(db):
    read_the_licence(db)
    settle_the_basis(db)
    search_id = a_search(db)
    title.record_result(db, search_id, retrieved_at=NOW,
                        volume_folio="12345/678",
                        registered_proprietor="A. Landholder",
                        proprietor_address="1 Example Street", is_company=False)
    assert db.execute(
        "SELECT registered_proprietor FROM title_search WHERE id = %s",
        (search_id,)).fetchone()[0] == "A. Landholder"


def test_a_name_cannot_be_added_to_a_search_recorded_without_one(db):
    """The workflow this forbids: the gate is closed, the search happens anyway,
    and the name is filled in once the paperwork catches up. A name not stored
    at the time was either not obtained or held somewhere the database could not
    account for."""
    read_the_licence(db)
    search_id = a_search(db)
    title.record_result(db, search_id, retrieved_at=NOW,
                        volume_folio="12345/678")
    settle_the_basis(db)
    with pytest.raises(psycopg.errors.RaiseException, match="cannot be added"):
        db.execute("UPDATE title_search SET registered_proprietor = 'A. Landholder' "
                   "WHERE id = %s", (search_id,))
    db.rollback()


# ------------------------------------------------------------ not a bulk extract

def test_a_prospecting_search_names_what_it_came_from(db):
    """The anti-bulk control. The system already produces a shortlist; the
    lawful search is against the parcels on it, not a sweep for questions to
    ask."""
    read_the_licence(db)
    with pytest.raises(title.TitleSearchRefused, match="must name the parcel"):
        title.request(db, searched_for="somewhere", purpose="MANDATE_MATCH",
                      fee_cents=2920,
                      requested_by=user_id(db, "analyst@crown.local"))


def test_a_vendor_instruction_needs_no_shortlist(db):
    """Because the property came to Crown rather than Crown going looking."""
    read_the_licence(db)
    assert title.request(db, searched_for="12 Example Street, Tarneit",
                         purpose="VENDOR_INSTRUCTION", fee_cents=2920,
                         requested_by=user_id(db, "analyst@crown.local"))


def test_there_is_no_purpose_meaning_no_purpose(db):
    read_the_licence(db)
    for purpose in ("RESEARCH", "GENERAL", ""):
        with pytest.raises(title.TitleSearchRefused, match="unknown purpose"):
            title.request(db, searched_for="x", purpose=purpose, fee_cents=1,
                          requested_by=user_id(db, "analyst@crown.local"))


# ----------------------------------------------------------------- not rewritten

def test_the_registers_answer_is_not_edited(db):
    read_the_licence(db)
    settle_the_basis(db)
    search_id = a_search(db)
    title.record_result(db, search_id, retrieved_at=NOW,
                        volume_folio="12345/678",
                        registered_proprietor="A. Landholder")
    with pytest.raises(psycopg.errors.RaiseException, match="may be\n?\\s*removed but not altered"):
        db.execute("UPDATE title_search SET registered_proprietor = 'Someone Else' "
                   "WHERE id = %s", (search_id,))
    db.rollback()


def test_the_fee_is_not_edited(db):
    """An invoice line does not change retrospectively."""
    read_the_licence(db)
    search_id = a_search(db)
    with pytest.raises(psycopg.errors.RaiseException, match="what it cost"):
        db.execute("UPDATE title_search SET fee_cents = 0 WHERE id = %s", (search_id,))
    db.rollback()


def test_the_source_cannot_be_swapped_after_the_fact(db):
    """Otherwise gate one is enforced only at insert, which is the hole 0024's
    channel trigger closed by running on UPDATE too."""
    read_the_licence(db)
    search_id = a_search(db)
    other = db.execute(
        "SELECT id FROM data_source WHERE code = 'VICMAP_PROPERTY'").fetchone()[0]
    with pytest.raises(psycopg.errors.RaiseException):
        db.execute("UPDATE title_search SET source_id = %s WHERE id = %s",
                   (other, search_id))
    db.rollback()


# ---------------------------------------------------------------------- the cost

def test_what_it_cost_is_answerable(db):
    """A prospecting system that cannot say what a lead costs keeps buying leads
    nobody can justify."""
    read_the_licence(db)
    a_search(db)
    a_search(db, parcel_id=a_parcel(db, "TEST-2\\PS2"), fee_cents=4420)
    rows = {r[1]: r for r in title.spend(db)}
    assert rows["OPPORTUNITY_SHORTLIST"][2] == 2
    assert rows["OPPORTUNITY_SHORTLIST"][3] == 7340


def test_a_search_with_no_result_is_still_charged(db):
    """The number worth watching: a fee paid for nothing."""
    read_the_licence(db)
    search_id = a_search(db)
    assert title.spend(db)[0][4] == 0
    title.record_result(db, search_id, retrieved_at=NOW, volume_folio="1/1")
    assert title.spend(db)[0][4] == 1


# ------------------------------------------------------------------- retention

def test_the_name_does_not_outlive_its_purpose(db):
    """Twelve months. The register moves: a name two years old is both
    unnecessary and probably wrong."""
    read_the_licence(db)
    settle_the_basis(db)
    search_id = a_search(db)
    title.record_result(db, search_id, retrieved_at=LONG_AGO,
                        volume_folio="12345/678",
                        registered_proprietor="A. Landholder",
                        proprietor_address="1 Example Street")

    assert [r[0] for r in retention.due(db)] == ["TITLE_SEARCH_PROPRIETOR"]
    retention.apply(db, dry_run=False)

    after = db.execute(
        """SELECT registered_proprietor, proprietor_address, volume_folio, fee_cents
           FROM title_search WHERE id = %s""", (search_id,)).fetchone()
    tombstone = "[removed: retention period expired]"
    assert after == (tombstone, tombstone, "12345/678", 2920), (
        "the person is removed and the record of Crown's conduct stays: the "
        "fee and the folio are what a licence audit would ask about")


def test_the_sweep_does_not_re_offer_what_it_already_removed(db):
    read_the_licence(db)
    settle_the_basis(db)
    search_id = a_search(db)
    title.record_result(db, search_id, retrieved_at=LONG_AGO,
                        registered_proprietor="A. Landholder",
                        volume_folio="12345/678")
    retention.apply(db, dry_run=False)
    assert retention.due(db) == []


def test_the_period_has_a_reason_written_down(db):
    rule = {r[0]: r for r in retention.rules(db)}["TITLE_SEARCH_PROPRIETOR"]
    assert "register has moved on" in rule[3]


# -------------------------------------------------------- who may read a search

def test_a_search_is_visible_to_whoever_asked_for_it(db, app_db):
    read_the_licence(db)
    analyst = user_id(db, "analyst@crown.local")
    search_id = a_search(db, requested_by=analyst)
    db.commit()

    crown_db.set_identity(app_db, str(analyst), "ANALYST")
    assert app_db.execute("SELECT count(*) FROM title_search").fetchone()[0] == 1


def test_another_agent_does_not_see_it(db, app_db):
    """It names an owner, an address, and the fact that Crown was interested in
    their land. There is nothing in this schema more worth restricting."""
    read_the_licence(db)
    search_id = a_search(db, requested_by=user_id(db, "analyst@crown.local"))
    db.commit()

    crown_db.set_identity(app_db, str(user_id(db, "agent@crown.local")), "AGENT")
    assert app_db.execute("SELECT count(*) FROM title_search").fetchone()[0] == 0


def test_compliance_sees_every_search(db, app_db):
    """Somebody has to be able to answer a licence audit and a privacy
    complaint, and neither question is about one analyst's rows."""
    read_the_licence(db)
    a_search(db, requested_by=user_id(db, "analyst@crown.local"))
    db.commit()

    crown_db.set_identity(app_db, str(user_id(db, "compliance@crown.local")),
                          "COMPLIANCE")
    assert app_db.execute("SELECT count(*) FROM title_search").fetchone()[0] == 1


def test_the_spend_view_is_caller_scoped(db, app_db):
    """A total is a count of searches. One that ignores the policies tells a
    reader how many searches exist that they may not see."""
    read_the_licence(db)
    a_search(db, requested_by=user_id(db, "analyst@crown.local"))
    db.commit()

    crown_db.set_identity(app_db, str(user_id(db, "agent@crown.local")), "AGENT")
    assert title.spend(app_db) == []


# ------------------------------------------- the trap this migration fell into

def test_replacing_a_view_does_not_quietly_unprotect_it(db):
    """0031 adds a branch to retention_due, which means replacing it.

    CREATE OR REPLACE VIEW replaces the view's options as well as its query, so
    the first version of this migration silently dropped the security_invoker
    that 0029 had set on a view exposing a recipient's name. Nothing about the
    schema looked different; the suite caught it.

    test_views_and_policies.py holds the general invariant. This is the specific
    one, next to the migration that broke it, so the next person to add a
    retention category is told why the WITH clause is there.
    """
    options = db.execute(
        """SELECT coalesce((SELECT option_value FROM pg_options_to_table(reloptions)
                            WHERE option_name = 'security_invoker'), 'off')
           FROM pg_class WHERE relname = 'retention_due'""").fetchone()[0]
    assert options == "true", (
        "retention_due no longer runs as its caller. If a migration replaced "
        "it, restate WITH (security_invoker = true) — the option does not "
        "survive CREATE OR REPLACE.")
