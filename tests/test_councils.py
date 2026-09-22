"""The seven councils, one row each — and what reading their terms turned up.

Migration 0014 said COUNCIL_PLANNING_REGISTERS was not one source and should
become seven. 0015 does that, and records two things the split exposed: council
websites reserve their content rather than opening it, and the state already
aggregates the same data under terms Crown has cleared.

These tests hold the shape of that answer, not the answer itself. A position
recorded here can change the moment somebody reads a council's terms directly;
what must not change is that an unread source stays unread, that a source
nobody signed stays off, and that a relayed reading says so.
"""
import pytest

from ingest import registry

COUNCILS = (
    "COUNCIL_WYNDHAM", "COUNCIL_MELTON", "COUNCIL_HUME", "COUNCIL_WHITTLESEA",
    "COUNCIL_CASEY", "COUNCIL_GREATER_GEELONG", "COUNCIL_GREATER_SHEPPARTON",
)


def row(db, code):
    return db.execute(
        """SELECT lane::text, is_ingestible, automated_access::text,
                  terms_reference, terms_read_by, register_confirmed_by,
                  carries_personal_information, notes
           FROM data_source WHERE code = %s""", (code,)).fetchone()


# ------------------------------------------------------- one source, seven rows

def test_every_council_crown_works_has_its_own_entry(db):
    """Seventy-nine publishers cannot share one position, and the seven Crown
    actually works are the seven that need answering."""
    for code in COUNCILS:
        assert row(db, code) is not None, f"{code} is not in the register"


def test_splitting_the_source_did_not_switch_any_of_them_on(db):
    """A finer-grained register is not a more permissive one."""
    for code in COUNCILS:
        lane, ingestible, _, _, _, confirmed_by, _, _ = row(db, code)
        assert lane == "B_OPEN"
        assert ingestible is False
        assert confirmed_by is None


def test_the_row_they_replace_is_kept_and_marked(db):
    """A rights register records what was believed and when. The superseded row
    stays, so the reasoning that produced seven better ones is not erased."""
    _, ingestible, _, _, _, _, _, notes = row(db, "COUNCIL_PLANNING_REGISTERS")
    assert ingestible is False
    assert "SUPERSEDED" in notes
    for code in COUNCILS:
        assert code in notes


# ----------------------------------------------------- what the terms said

def test_a_council_whose_terms_were_not_read_stays_unknown(db):
    """For three of the seven, the relay returned a third-party engagement
    platform's terms instead of the council's own. A position taken on the wrong
    document is worse than no position, so these stay UNKNOWN."""
    for code in ("COUNCIL_WYNDHAM", "COUNCIL_MELTON", "COUNCIL_HUME",
                 "COUNCIL_WHITTLESEA", "COUNCIL_GREATER_SHEPPARTON"):
        _, _, access, _, read_by, _, _, _ = row(db, code)
        assert access == "UNKNOWN"
        assert read_by is None


def test_the_council_that_forbids_commercial_reuse_is_prohibited(db):
    """Greater Geelong's own terms page was the one relay did find: personal or
    internal business use only, nothing to third parties, no commercial purpose.
    Crown is commercial and its artefacts go to third-party buyers."""
    _, _, access, reference, read_by, _, _, _ = row(db, "COUNCIL_GREATER_GEELONG")
    assert access == "PROHIBITED"
    assert "commercial purpose" in reference
    assert read_by is not None


def test_the_council_that_publishes_a_feed_is_recorded_as_offering_one(db):
    """An open-data API is the publisher handing over the channel, which answers
    the scraping question by removing it."""
    _, _, access, reference, _, _, _, _ = row(db, "COUNCIL_CASEY")
    assert access == "PUBLISHER_FEED"
    assert "data.vic.gov.au" in reference


def test_every_position_in_the_register_says_how_it_was_read(db):
    """No Victorian host has been reachable from this environment on any day a
    position was recorded, so every one of them rests on a search relay. A
    register where some rows disclose that and others do not is worse than one
    where none do: the silence reads as a stronger reading rather than an older
    one. 0015 backfills the ones 0009 and 0014 left bare."""
    rows = db.execute(
        """SELECT code, terms_read_by FROM data_source
           WHERE automated_access <> 'UNKNOWN'""").fetchall()
    assert len(rows) >= 10
    for code, read_by in rows:
        assert read_by, f"{code} has a position and no reader"
        assert "relay" in read_by.lower(), f"{code} does not disclose how it was read"


def test_the_disclosure_is_not_stacked_twice(db):
    """The backfill is guarded, so applying it over an already-disclosed row is
    a no-op rather than a sentence repeated."""
    for (read_by,) in db.execute(
            """SELECT terms_read_by FROM data_source
               WHERE terms_read_by IS NOT NULL""").fetchall():
        assert read_by.lower().count("search relay") == 1


# --------------------------------------------------- the route that replaces them

def test_the_state_aggregation_is_registered(db):
    """Every responsible authority reports permit activity to PPARS monthly.
    One publisher, statewide, under DTP terms Crown already read in 0014."""
    lane, ingestible, access, _, _, confirmed_by, personal, notes = row(db, "VIC_PPARS")
    assert lane == "B_OPEN"
    assert access == "PERMITTED"
    assert ingestible is False        # permitted is not the same as signed
    assert confirmed_by is None
    assert personal is True
    assert "statistics" in notes      # says plainly what it does not give


def test_it_carries_the_attribution_the_licence_requires(db):
    """CC BY 4.0 is only satisfied if the notice travels with the data."""
    attribution, licence = db.execute(
        """SELECT attribution_text, licence_reference FROM data_source
           WHERE code = 'VIC_PPARS'""").fetchone()
    assert "Creative Commons Attribution 4.0" in attribution
    assert "State of Victoria" in attribution
    assert "creativecommons.org/licenses/by/4.0" in attribution
    assert "CC BY 4.0" in licence


def test_none_of_this_is_ingestible_yet(db):
    """The register gained nine rows and no new permission. If this ever fails,
    something was switched on without a signature."""
    ingestible = {r[0] for r in db.execute(
        """SELECT code FROM data_source
           WHERE is_ingestible AND code = ANY(%s)""",
        (list(COUNCILS) + ["VIC_PPARS", "COUNCIL_PLANNING_REGISTERS"],)).fetchall()}
    assert ingestible == set()


def test_the_crawler_refuses_every_one_of_them(db):
    """The register is only worth keeping if something reads it. Nothing here is
    ingestible, so the gate must refuse all nine by name — including the two
    whose terms do permit automated access, because permission to fetch is not
    permission to ingest."""
    for code in COUNCILS + ("VIC_PPARS", "COUNCIL_PLANNING_REGISTERS"):
        with pytest.raises(registry.SourceNotIngestible):
            registry.resolve(db, code, automated=True)


# ------------------------------------------------------------- the signature

def test_the_register_entry_is_signed_in_the_company_name(db):
    """Asked whose name should carry the attestation, Crown answered: the
    company's. 0019 made that the registered company rather than the trading
    name, because a register that says who is accountable has to name somebody
    a regulator can serve. Who did the reading stays recorded separately."""
    confirmed_by, confirmed_at, read_by = db.execute(
        """SELECT register_confirmed_by, register_confirmed_at, terms_read_by
           FROM data_source WHERE code = 'VIC_PLANNING_AMENDMENTS'""").fetchone()
    assert confirmed_by == ("Crown Real Estate Agents Pty Ltd "
                            "(ABN 86 690 344 597)")
    assert confirmed_at is not None
    assert read_by.startswith("Crown AI review 2026-09-20")
    assert "search relay" in read_by


def test_the_signature_names_the_same_entity_the_messages_do(db):
    """Two records name who is accountable: the register, for the lawfulness of
    a source, and outbound_identity, for who authorised a message built from
    it. Different names in them is a discrepancy that costs nothing to prevent
    and is unpleasant to explain."""
    confirmed_by = db.execute(
        """SELECT register_confirmed_by FROM data_source
           WHERE code = 'VIC_PLANNING_AMENDMENTS'""").fetchone()[0]
    entity, abn = db.execute(
        """SELECT legal_entity_name, abn FROM outbound_identity
           WHERE is_active""").fetchone()

    assert entity in confirmed_by
    assert abn.replace(" ", "") in confirmed_by.replace(" ", "")


def test_the_rename_did_not_erase_the_name_it_replaced(db):
    """A register signature that can be quietly reassigned is worth less than
    one that cannot. Both names are in the audit trail, and the newer row says
    what the older one said."""
    rows = db.execute(
        """SELECT new_state FROM audit_event
           WHERE action = 'SOURCE_REGISTER_CONFIRMED'
             AND new_state ->> 'code' = 'VIC_PLANNING_AMENDMENTS'
           ORDER BY occurred_at""").fetchall()
    names = [r[0]["confirmed_by"] for r in rows]

    assert "Crown Capital & Development" in names
    assert ("Crown Real Estate Agents Pty Ltd (ABN 86 690 344 597)"
            in names)
    assert rows[-1][0]["previously"] == "Crown Capital & Development"


def test_reassigning_the_signature_is_audited(db):
    """Changing who stands behind a source is itself an event worth keeping."""
    state = db.execute(
        """SELECT new_state FROM audit_event
           WHERE action = 'SOURCE_REGISTER_CONFIRMED'
             AND new_state ->> 'confirmed_by' = 'Crown Capital & Development'"""
    ).fetchone()[0]
    assert state["code"] == "VIC_PLANNING_AMENDMENTS"
    assert state["terms_read_by"].startswith("Crown AI review 2026-09-20")
    assert "unchanged" in state["basis"]


def test_the_register_still_shows_no_open_exception(db):
    """Nine new rows, none ingestible, so the compliance report stays empty."""
    from crown import reports
    assert reports.data_rights_exceptions(db) == []
