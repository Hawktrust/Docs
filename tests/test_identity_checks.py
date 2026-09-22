"""The identity check that checks the identity.

0016 asked whether an active sender identity exists. It does, since 0019, and
the check went green — as it would have on a row reading 'TBD' with an ABN of
eleven zeroes, because counting rows is not reading them.

Section 17 of the Spam Act does not ask whether a sender identity exists. It
asks that the message accurately identify who authorised it and say how to
contact them. Three parts of that a machine can decide, and this is where it
decides them.
"""
import psycopg
import pytest

from tests.test_optout import insert_an_identity, no_active_identity


def readiness(db, code):
    """One check by name, or None if the view does not have it."""
    row = db.execute(
        "SELECT passes, detail FROM launch_readiness WHERE check_code = %s",
        (code,)).fetchone()
    return row


# ------------------------------------------------------------ the checksum

# 86 690 344 597 is Crown's own, recorded in 0019. The rest are constructed:
# a transposition, a mistyped digit, the wrong length, and eleven zeroes —
# which is the value a placeholder most often takes.
@pytest.mark.parametrize("candidate,expected", [
    ("86690344597",       True),   # Crown's, unspaced
    ("86 690 344 597",    True),   # Crown's, as stored
    (" 86 690 344 597 ",  True),   # surrounding whitespace is not a typo
    ("68690344597",       False),  # first two digits transposed
    ("86690344598",       False),  # last digit mistyped
    ("8669034459",        False),  # ten digits
    ("866903445970",      False),  # twelve digits
    ("00000000000",       False),  # the placeholder
    ("",                  False),
    ("not an abn",        False),
    ("86-690-344-597",    False),  # punctuation is not stripped; see below
    ("ABN 86 690 344 597", False),
])
def test_the_checksum_agrees_with_the_ato(db, candidate, expected):
    assert db.execute("SELECT abn_is_well_formed(%s)",
                      (candidate,)).fetchone()[0] is expected


def test_punctuation_is_refused_rather_than_stripped(db):
    """Stripping non-digits out of anything at all would let
    'ABN 86 690 344 597 (unconfirmed)' pass as a stored value. What is stored
    is what goes on the message, so the stored form has to be the clean one."""
    assert db.execute(
        "SELECT abn_is_well_formed('86 690 344 597 (unconfirmed)')"
    ).fetchone()[0] is False


def test_a_null_abn_is_not_an_answer(db):
    """STRICT: NULL in, NULL out. An absent ABN is a different thing from a
    wrong one, and the constraint treats it as such."""
    assert db.execute("SELECT abn_is_well_formed(NULL)").fetchone()[0] is None


# ------------------------------------------------------- the constraint

def test_a_malformed_abn_cannot_be_stored(db):
    """0017 freezes this table's content, so a bad ABN could never be edited
    out — only superseded, leaving the wrong one in the history of what Crown
    sent as. Refusing it at write time is the cheaper moment."""
    no_active_identity(db)
    with pytest.raises(psycopg.errors.CheckViolation,
                       match="the_abn_is_well_formed"):
        insert_an_identity(db, abn="00 000 000 000")
    db.rollback()


def test_an_identity_with_no_abn_is_still_allowed(db):
    """Not every sender has one. A sole trader without an ABN must still be
    able to identify itself, and s17 wants the name and the contact rather than
    the ABN specifically."""
    no_active_identity(db)
    assert insert_an_identity(db, abn=None)


def test_crowns_own_abn_passes_the_constraint(db):
    """The row 0019 wrote is in the database this test runs against. If the
    constraint and the seeded value ever disagree, every test in the suite
    fails at migration time — but this says which one was wrong."""
    abn = db.execute(
        "SELECT abn FROM outbound_identity WHERE is_active").fetchone()[0]
    assert abn == "86 690 344 597"
    assert db.execute("SELECT abn_is_well_formed(%s)", (abn,)).fetchone()[0]


# ------------------------------------------------- the readiness checks

def test_the_seeded_identity_is_usable(db):
    passes, detail = readiness(db, "THE_SENDER_IDENTITY_IS_USABLE")
    assert passes, detail
    assert detail == "no malformed field in the active sender identity"


def test_an_unshaped_contact_email_is_blocking(db):
    """Weak, deliberately: it separates an address from a note-to-self. A
    recipient who cannot reply has not been told how to contact anybody."""
    no_active_identity(db)
    insert_an_identity(db, contact_email="ask Inder")

    passes, detail = readiness(db, "THE_SENDER_IDENTITY_IS_USABLE")
    assert not passes
    assert "not shaped like an address" in detail


def test_a_blank_postal_address_is_blocking(db):
    no_active_identity(db)
    insert_an_identity(db, postal_address="   ")

    passes, detail = readiness(db, "THE_SENDER_IDENTITY_IS_USABLE")
    assert not passes
    assert "postal address is blank" in detail


def test_the_two_checks_fail_for_different_reasons(db):
    """CROWN_KNOWS_WHO_IT_SENDS_AS answers 'is there one'. This one answers
    'is it any good'. Overloading the first would have made a failure ambiguous
    between two problems with two different fixes."""
    no_active_identity(db)

    exists, _ = readiness(db, "CROWN_KNOWS_WHO_IT_SENDS_AS")
    usable, detail = readiness(db, "THE_SENDER_IDENTITY_IS_USABLE")

    assert not exists                  # there is none
    assert usable, detail              # and so nothing is malformed


# -------------------------------------------- the two records agreeing

def test_the_register_and_the_sender_name_the_same_entity(db):
    passes, detail = readiness(db, "ACCOUNTABILITY_NAMES_ONE_ENTITY")
    assert passes, detail


def test_a_register_signed_by_somebody_else_is_blocking(db):
    """The register says who stands behind a source being lawful to use;
    outbound_identity says who authorised the message built from it. 0019 set
    both by hand and they happen to match. This is what keeps it true."""
    db.execute("""UPDATE data_source
                  SET register_confirmed_by = 'Somebody Else Pty Ltd'
                  WHERE code = 'VIC_PLANNING_AMENDMENTS'""")

    passes, detail = readiness(db, "ACCOUNTABILITY_NAMES_ONE_ENTITY")
    assert not passes
    assert detail.startswith("1 ")
    db.rollback()


def test_an_unsigned_register_entry_is_not_a_disagreement(db):
    """Most sources are unsigned. Silence is not a contradiction, and a check
    that treated it as one would make signing a source the thing that fixes
    it — exactly backwards."""
    unsigned = db.execute(
        """SELECT count(*) FROM data_source
           WHERE register_confirmed_by IS NULL""").fetchone()[0]
    assert unsigned > 0

    passes, _ = readiness(db, "ACCOUNTABILITY_NAMES_ONE_ENTITY")
    assert passes


def test_with_no_sender_there_is_nothing_to_disagree_with(db):
    """Vacuous rather than failing. CROWN_KNOWS_WHO_IT_SENDS_AS already reports
    the missing identity, and two checks failing for one cause is how a
    readiness list becomes something people skim."""
    no_active_identity(db)

    passes, _ = readiness(db, "ACCOUNTABILITY_NAMES_ONE_ENTITY")
    assert passes


def test_a_legal_entity_name_is_data_and_not_a_pattern(db):
    """position(), not ILIKE. A name containing % would otherwise become a
    wildcard that matches any signature at all — an injection into the check
    that is supposed to catch a mismatch."""
    no_active_identity(db)
    insert_an_identity(db, legal_entity_name="% Pty Ltd")
    db.execute("""UPDATE data_source
                  SET register_confirmed_by = 'Somebody Else Pty Ltd'
                  WHERE code = 'VIC_PLANNING_AMENDMENTS'""")

    passes, _ = readiness(db, "ACCOUNTABILITY_NAMES_ONE_ENTITY")
    assert not passes
    db.rollback()
