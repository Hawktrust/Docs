"""The channel is part of whether a message may be sent at all.

CONSENT-POSITION.md concluded that APP 7 and the Spam Act are separate tests
and only the first has an impracticability escape. Inferred consent under the
Spam Act needs the address published BY THE PERSON, in a work capacity, with
the message relevant to that work. A landholder's details on a planning permit
fail all three limbs, so the lawful channel differs by audience.

That conclusion used to live only in a document. These are the tests of it
living in the schema.
"""
import psycopg
import pytest
from psycopg.types.json import Jsonb

from crown import consent, outbound, suppression
from tests.conftest import a_body, approved_match, user_id
from tests.test_optout import an_identity

LANDHOLDER = {"PERSON": "A. Landholder"}


def a_consent(db, identifier="A. Landholder", basis="EXPRESS_REPLY",
              scope="PERSON"):
    from datetime import datetime, timezone
    return consent.record(
        db, scope=scope, identifier=identifier, basis=basis,
        evidence="replied to the letter of 1 March asking to be emailed",
        given_at=datetime.now(timezone.utc),
        recorded_by=user_id(db, "analyst@crown.local"))


# ------------------------------------------------ the rule the analysis found

def test_a_landholder_from_a_register_cannot_be_emailed(db):
    """The whole point. A council published the address under a statute; the
    person did not publish it in a work capacity, so inferred consent fails and
    the Spam Act has no impracticability escape to fall back on."""
    an_identity(db)
    approval_id, creator = approved_match(db)

    with pytest.raises(outbound.ChannelNotPermitted, match="Send this by post"):
        outbound.create(db, approval_id, "OUTREACH_DRAFT", {"body": a_body()},
                        creator, contact=LANDHOLDER, channel="EMAIL",
                        recipient_class="LANDHOLDER_FROM_REGISTER")


def test_the_same_landholder_can_be_written_to(db):
    """Post is not a commercial electronic message. The Spam Act does not reach
    it, and APP 5 and APP 7 are satisfied by the notice and the opt-out."""
    an_identity(db)
    approval_id, creator = approved_match(db)

    assert outbound.create(db, approval_id, "OUTREACH_DRAFT", {"body": a_body()},
                           creator, contact=LANDHOLDER, channel="POST",
                           recipient_class="LANDHOLDER_FROM_REGISTER")


def test_a_reply_opens_the_channel(db):
    """Express consent is the route the Spam Act does accept."""
    an_identity(db)
    a_consent(db)
    approval_id, creator = approved_match(db)

    assert outbound.create(db, approval_id, "OUTREACH_DRAFT", {"body": a_body()},
                           creator, contact=LANDHOLDER, channel="EMAIL",
                           recipient_class="LANDHOLDER_FROM_REGISTER")


def test_withdrawing_the_consent_closes_it_again(db):
    an_identity(db)
    consent_id = a_consent(db)
    approval_id, creator = approved_match(db)
    consent.withdraw(db, consent_id,
                     withdrawn_by=user_id(db, "analyst@crown.local"))

    with pytest.raises(outbound.ChannelNotPermitted):
        outbound.create(db, approval_id, "OUTREACH_DRAFT", {"body": a_body()},
                        creator, contact=LANDHOLDER, channel="EMAIL",
                        recipient_class="LANDHOLDER_FROM_REGISTER")


def test_a_buyers_mandate_is_not_a_landholders_consent(db):
    """MANDATE is storable, and is consent — from a buyer, about a different
    thing. Accepting it here would let a mandate signed by one person authorise
    emailing another."""
    an_identity(db)
    a_consent(db, basis="MANDATE")
    approval_id, creator = approved_match(db)

    with pytest.raises(outbound.ChannelNotPermitted):
        outbound.create(db, approval_id, "OUTREACH_DRAFT", {"body": a_body()},
                        creator, contact=LANDHOLDER, channel="EMAIL",
                        recipient_class="LANDHOLDER_FROM_REGISTER")


def test_a_professional_contact_can_be_emailed_without_one(db):
    """A work address published by the firm, about work. All three limbs of
    conspicuous publication are satisfied, so no express consent is needed."""
    an_identity(db)
    approval_id, creator = approved_match(db)

    assert outbound.create(db, approval_id, "OUTREACH_DRAFT", {"body": a_body()},
                           creator, contact={"ORGANISATION": "A Firm Pty Ltd"},
                           channel="EMAIL",
                           recipient_class="PROFESSIONAL_CONTACT")


# ------------------------------------------- the constraint under the advice

def test_the_database_refuses_it_even_if_the_code_is_bypassed(db):
    """The application says what to do about it; the trigger is what makes that
    advice rather than the control."""
    an_identity(db)
    approval_id, creator = approved_match(db)
    sender = outbound.active_identity(db)[0]

    with pytest.raises(psycopg.errors.CheckViolation, match="no express consent"):
        db.execute(
            """INSERT INTO outbound_artifact
                   (approval_id, artifact_type, content, created_by,
                    contact_scope, contact_identifier, sender_identity_id,
                    channel, recipient_class)
               VALUES (%s,'OUTREACH_DRAFT',%s,%s,'PERSON','A. Landholder',%s,
                       'EMAIL','LANDHOLDER_FROM_REGISTER')""",
            (approval_id, Jsonb({"body": a_body()}), creator, sender))
    db.rollback()


def test_the_channel_cannot_be_switched_afterwards(db):
    """A rule enforced only at insert is a rule you get around with an UPDATE.
    The trigger runs on both."""
    an_identity(db)
    approval_id, creator = approved_match(db)
    artifact_id = outbound.create(
        db, approval_id, "OUTREACH_DRAFT", {"body": a_body()}, creator,
        contact=LANDHOLDER, channel="POST",
        recipient_class="LANDHOLDER_FROM_REGISTER")

    with pytest.raises(psycopg.errors.CheckViolation, match="no express consent"):
        db.execute("UPDATE outbound_artifact SET channel = 'EMAIL' WHERE id = %s",
                   (artifact_id,))
    db.rollback()


def test_a_message_to_a_person_must_name_a_channel(db):
    an_identity(db)
    approval_id, creator = approved_match(db)
    sender = outbound.active_identity(db)[0]

    with pytest.raises(psycopg.errors.CheckViolation,
                       match="a_message_to_a_person_names_its_channel"):
        db.execute(
            """INSERT INTO outbound_artifact
                   (approval_id, artifact_type, content, created_by,
                    contact_scope, contact_identifier, sender_identity_id)
               VALUES (%s,'OUTREACH_DRAFT',%s,%s,'PERSON','A. Landholder',%s)""",
            (approval_id, Jsonb({"body": a_body()}), creator, sender))
    db.rollback()


def test_an_export_still_needs_neither(db):
    """An EXPORT is not addressed to anybody. Requiring a channel of it would be
    ceremony, and ceremony is what people learn to work around."""
    approval_id, creator = approved_match(db)
    assert outbound.create(db, approval_id, "EXPORT", {"rows": []}, creator)


def test_there_is_no_phone_channel(db):
    """Its absence is deliberate. The Do Not Call Register Act wants numbers
    washed before telemarketing and Crown has not built that, so a value the
    schema appears to bless and the law does not would be worse than none."""
    assert "PHONE" not in outbound.CHANNELS
    an_identity(db)
    approval_id, creator = approved_match(db)
    sender = outbound.active_identity(db)[0]

    with pytest.raises(psycopg.errors.CheckViolation,
                       match="channel_is_one_crown_can_lawfully_use"):
        db.execute(
            """INSERT INTO outbound_artifact
                   (approval_id, artifact_type, content, created_by,
                    contact_scope, contact_identifier, sender_identity_id,
                    channel, recipient_class)
               VALUES (%s,'OUTREACH_DRAFT',%s,%s,'PERSON','A. Landholder',%s,
                       'PHONE','LANDHOLDER_FROM_REGISTER')""",
            (approval_id, Jsonb({"body": a_body()}), creator, sender))
    db.rollback()


# --------------------------------------------- the two normalisations agree

@pytest.mark.parametrize("raw", [
    "A. Landholder", "  A. Landholder  ", "a. landholder",
    "A.   LANDHOLDER", "A.\tLandholder", "A.\nLandholder",
    "Māori Name", "O'Brien & Sons Pty Ltd", "",
])
def test_sql_and_python_normalise_identically(db, raw):
    """If these drift, the consent lookup silently stops matching and the rule
    never fires. A control that quietly never triggers is worse than no
    control, because it is believed."""
    from_sql = db.execute(
        "SELECT normalise_identifier(%s)", (raw,)).fetchone()[0]
    assert from_sql == suppression.normalise(raw)


def test_consent_matching_survives_a_differently_typed_name(db):
    """The point of normalising at all: somebody types the name with different
    spacing and case, and the consent still applies to the same person."""
    an_identity(db)
    a_consent(db, identifier="  a.   LANDHOLDER ")
    approval_id, creator = approved_match(db)

    assert outbound.create(db, approval_id, "OUTREACH_DRAFT", {"body": a_body()},
                           creator, contact=LANDHOLDER, channel="EMAIL",
                           recipient_class="LANDHOLDER_FROM_REGISTER")


# ----------------------------------------------- what a consent has to say

def test_a_consent_records_what_actually_happened(db):
    """'They consented' is a conclusion. The sentence stored here is the one
    read back if it is ever questioned."""
    from datetime import datetime, timezone
    with pytest.raises(consent.ConsentRefused, match="conclusion, not evidence"):
        consent.record(db, scope="PERSON", identifier="A. Landholder",
                       basis="EXPRESS_REPLY", evidence="   ",
                       given_at=datetime.now(timezone.utc),
                       recorded_by=user_id(db, "analyst@crown.local"))


def test_a_suppression_still_outranks_a_consent(db):
    """They are not opposites. Somebody who agreed to email and later asked to
    stop has done two things, and the stop wins."""
    from datetime import datetime, timezone
    an_identity(db)
    a_consent(db)
    suppression.record(
        db, scope="PERSON", identifier="A. Landholder",
        reason="asked to be left alone", requested_at=datetime.now(timezone.utc),
        recorded_by=user_id(db, "analyst@crown.local"),
        source_of_request="EMAIL")
    approval_id, creator = approved_match(db)

    with pytest.raises(suppression.Suppressed):
        outbound.create(db, approval_id, "OUTREACH_DRAFT", {"body": a_body()},
                        creator, contact=LANDHOLDER, channel="EMAIL",
                        recipient_class="LANDHOLDER_FROM_REGISTER")


def test_the_gate_view_is_empty_because_the_trigger_refuses_the_row(db):
    assert db.execute("SELECT count(*) FROM channel_exception").fetchone()[0] == 0
