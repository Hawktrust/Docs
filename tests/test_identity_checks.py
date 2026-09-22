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


# ------------------------------------- changing the address Crown is reached at

def test_the_active_identity_carries_the_current_address(db):
    email = db.execute(
        "SELECT contact_email FROM outbound_identity WHERE is_active"
    ).fetchone()[0]
    assert email == "info@crownrea.com.au"


def test_the_retired_identity_keeps_the_address_it_sent_under(db):
    """0021 changed Crown's contact address. The old row is retired, not
    corrected: a message sent under it said inder@crownrealestateagents.com.au,
    and that is what it said. s17 requires the sender's contact details to stay
    accurate for 30 days after sending, which is a statement about the message
    rather than about the company's current address."""
    rows = db.execute(
        """SELECT contact_email FROM outbound_identity
           WHERE NOT is_active AND superseded_at IS NOT NULL""").fetchall()
    assert ("inder@crownrealestateagents.com.au",) in rows
    assert ("inder@crownrea.com.au",) in rows


def test_only_one_of_them_is_active(db):
    """Two would mean a recipient could not tell which organisation authorised
    the message, which is the thing s17 is about. The unique index enforces it;
    this says the migration respected it rather than working around it."""
    active = db.execute(
        "SELECT count(*) FROM outbound_identity WHERE is_active").fetchone()[0]
    total = db.execute(
        "SELECT count(*) FROM outbound_identity").fetchone()[0]
    assert active == 1
    assert total >= 2          # the supersede kept the old row


def test_the_change_of_address_is_in_the_audit_trail(db):
    """Both halves. Somebody asking why two identities exist, or why an old
    email appears in a message, should find the answer without asking a
    person."""
    actions = {r[0] for r in db.execute(
        """SELECT action FROM audit_event
           WHERE actor_agent = 'migrations.0021'""").fetchall()}
    assert actions == {"USER_EMAIL_CHANGED", "OUTBOUND_IDENTITY_SUPERSEDED"}

    superseded = db.execute(
        """SELECT new_state FROM audit_event
           WHERE action = 'OUTBOUND_IDENTITY_SUPERSEDED'""").fetchone()[0]
    assert superseded["previously"] == "inder@crownrealestateagents.com.au"
    assert superseded["contact_email"] == "inder@crownrea.com.au"


def test_the_account_kept_its_id_through_the_rename(db):
    """app_user is edited in place rather than replaced, so audit_event,
    approval and every created_by reference stay attached to the person who
    actually did those things. A new account would have orphaned that history
    behind an inactive row."""
    created_by, = db.execute(
        """SELECT created_by FROM outbound_identity WHERE is_active""").fetchone()
    email, = db.execute(
        "SELECT email FROM app_user WHERE id = %s", (created_by,)).fetchone()
    assert email == "inder@crownrea.com.au"

    # And the rename is recorded against that same row.
    changed = db.execute(
        """SELECT object_id FROM audit_event
           WHERE action = 'USER_EMAIL_CHANGED'""").fetchone()[0]
    assert changed == str(created_by)


def test_the_old_address_is_gone_from_the_accounts(db):
    """Nobody signs in as the old address. It survives only where it is a
    historical fact: the retired identity row and the audit trail."""
    assert db.execute(
        """SELECT count(*) FROM app_user
           WHERE email = 'inder@crownrealestateagents.com.au'""").fetchone()[0] == 0


def test_the_new_identity_carries_everything_else_unchanged(db):
    """Only the email changed. An entity name or ABN that drifted during a
    supersede would be a different company sending the messages."""
    entity, abn, address = db.execute(
        """SELECT legal_entity_name, abn, postal_address
           FROM outbound_identity WHERE is_active""").fetchone()
    assert entity == "Crown Real Estate Agents Pty Ltd"
    assert abn == "86 690 344 597"
    assert address == "208/2 Infinity Drive, Truganina VIC 3029"


# ------------------------------- the published inbox is not the login

def test_the_login_and_the_published_address_are_different(db):
    """0019 set both from the one address Crown gave; they were never the same
    kind of thing. The login identifies a human and never leaves the system.
    The published address goes on every message to a stranger and has to keep
    working when that human is on leave."""
    login, = db.execute(
        "SELECT email FROM app_user WHERE role = 'ADMIN'").fetchone()
    published, = db.execute(
        "SELECT contact_email FROM outbound_identity WHERE is_active").fetchone()

    assert login == "inder@crownrea.com.au"
    assert published == "info@crownrea.com.au"
    assert login != published


def test_the_login_is_not_an_outbound_identity_at_all(db):
    """A personal address that reached an active outbound identity would be on
    every cold approach Crown sends. It may appear in the retired rows, which
    are history, but never in the one that messages carry."""
    active, = db.execute(
        "SELECT contact_email FROM outbound_identity WHERE is_active").fetchone()
    logins = {r[0] for r in db.execute("SELECT email FROM app_user").fetchall()}
    assert active not in logins


def test_superseding_twice_leaves_one_active_and_keeps_both_retired(db):
    """0021 and 0022 both superseded. The chain is the record of what each
    message could have said, so neither retired row may be collapsed away."""
    rows = db.execute(
        """SELECT contact_email, is_active FROM outbound_identity
           ORDER BY created_at""").fetchall()
    assert [r[0] for r in rows] == ["inder@crownrealestateagents.com.au",
                                    "inder@crownrea.com.au",
                                    "info@crownrea.com.au"]
    assert [r[1] for r in rows] == [False, False, True]


def test_the_split_is_in_the_audit_trail(db):
    """Somebody asking why the address on a message is not the address of the
    person who authorised it should find the answer without asking a person."""
    state = db.execute(
        """SELECT new_state FROM audit_event
           WHERE actor_agent = 'migrations.0022'
             AND action = 'OUTBOUND_IDENTITY_SUPERSEDED'""").fetchone()[0]
    assert state["contact_email"] == "info@crownrea.com.au"
    assert state["previously"] == "inder@crownrea.com.au"
    assert "login" in state["basis"]


def test_the_entity_survived_a_second_supersede(db):
    """Two supersedes are two chances for the company to quietly change."""
    entity, abn, address = db.execute(
        """SELECT legal_entity_name, abn, postal_address
           FROM outbound_identity WHERE is_active""").fetchone()
    assert entity == "Crown Real Estate Agents Pty Ltd"
    assert abn == "86 690 344 597"
    assert address == "208/2 Infinity Drive, Truganina VIC 3029"


# ------------------------------------------- somebody checked the ABN

def test_the_abn_confirmation_is_recorded(db):
    """0020 proved the digits are consistent and said plainly that it could not
    prove ownership. This is the other half, and it could only ever arrive from
    a person."""
    state = db.execute(
        """SELECT new_state FROM audit_event
           WHERE action = 'SENDER_ABN_CONFIRMED'""").fetchone()[0]
    assert state["abn"] == "86 690 344 597"
    assert state["legal_entity_name"] == "Crown Real Estate Agents Pty Ltd"
    assert state["confirmed_by"] == "Crown"


def test_the_record_says_a_person_checked_and_not_this_system(db):
    """The build environment cannot reach ABN Lookup. A record implying it did
    would be exactly the provenance failure evidence_record's retrieval_method
    exists to prevent — who looked matters as much as what they saw."""
    state = db.execute(
        """SELECT new_state FROM audit_event
           WHERE action = 'SENDER_ABN_CONFIRMED'""").fetchone()[0]
    assert state["method"].startswith("OPERATOR_CAPTURE")
    assert "cannot reach" in state["method"]


def test_the_confirmation_points_at_the_identity_it_confirms(db):
    """Not at the previous one. Two supersedes have happened since the ABN was
    first recorded, and a confirmation attached to a retired row would say
    nothing about what Crown sends as now."""
    object_id = db.execute(
        """SELECT object_id FROM audit_event
           WHERE action = 'SENDER_ABN_CONFIRMED'""").fetchone()[0]
    active = db.execute(
        "SELECT id FROM outbound_identity WHERE is_active").fetchone()[0]
    assert object_id == str(active)
