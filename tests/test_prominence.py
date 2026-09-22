"""A way out that a reader would have to hunt for is not a way out.

APP 7.3(c) wants the opt-out drawn to the reader's attention, not merely
present. 0016 made it exist, 0024 made the channel lawful, and neither looked
at the message — so an artefact could carry its way out in the twelfth line of
a footer and pass everything.
"""
import psycopg
import pytest

from crown import message, outbound
from crown.message import OPT_OUT_MARKER
from tests.conftest import a_body, approved_match
from tests.test_optout import an_identity

POST = {"channel": "POST", "recipient_class": "LANDHOLDER_FROM_REGISTER"}


def draft(db, body):
    an_identity(db)
    approval_id, creator = approved_match(db)
    return outbound.create(db, approval_id, "OUTREACH_DRAFT", {"body": body},
                           creator, contact={"PERSON": "A. Landholder"}, **POST)


# ------------------------------------------------------- what is refused

def test_a_message_with_no_way_out_is_refused(db):
    with pytest.raises(message.NotProminent, match="does not say how to stop"):
        draft(db, "Hello. Crown would like to buy your land.")


def test_a_way_out_buried_under_the_message_is_refused(db):
    """The realistic failure: an opt-out early on, then pages of content. It is
    present, and nobody would ever reach back up to it."""
    body = (f"Please stop hearing from us here: {OPT_OUT_MARKER}\n\n"
            + "Lorem ipsum about your property. " * 40)
    with pytest.raises(message.NotProminent, match="characters after it"):
        draft(db, body)


def test_a_way_out_inside_a_paragraph_is_refused(db):
    """On its own line or it gets read past."""
    body = ("Crown has been looking at land in your area and thought of you, "
            "and if you would rather we stopped you can " + OPT_OUT_MARKER +
            " although we hope you will read on because there is more to say "
            "about the amendment and what it might mean for the block.")
    with pytest.raises(message.NotProminent, match="inside a paragraph"):
        draft(db, body)


def test_a_bare_link_with_no_explanation_is_refused(db):
    """A link draws attention to nothing. Something near it has to say what it
    does — otherwise it reads as one more footer URL."""
    body = f"Hello. Crown is writing about your land.\n\n{OPT_OUT_MARKER}\n"
    with pytest.raises(message.NotProminent, match="tells the reader what it does"):
        draft(db, body)


def test_two_ways_out_are_refused(db):
    """One is a way out. Several is a choice to make, which is the opposite of
    simple."""
    body = (f"To stop, use this: {OPT_OUT_MARKER}\n"
            f"Or this one instead: {OPT_OUT_MARKER}\n")
    with pytest.raises(message.NotProminent, match="ways out"):
        draft(db, body)


def test_an_empty_body_is_refused(db):
    with pytest.raises(message.NotProminent):
        draft(db, "")


# ------------------------------------------------------- what is accepted

def test_a_findable_way_out_is_accepted(db):
    assert draft(db, a_body())


def test_a_long_message_is_fine_if_the_way_out_is_at_the_end(db):
    """Length is not the problem. Position is."""
    body = ("Lorem ipsum about your property. " * 40
            + f"\n\nIf you would rather not hear from us:\n{OPT_OUT_MARKER}\n")
    assert draft(db, body)


def test_an_export_is_not_a_message_and_needs_none(db):
    approval_id, creator = approved_match(db)
    assert outbound.create(db, approval_id, "EXPORT", {"rows": []}, creator)


# ------------------------------------------- the constraint under the advice

def test_the_database_refuses_it_even_if_the_code_is_bypassed(db):
    an_identity(db)
    approval_id, creator = approved_match(db)
    sender = outbound.active_identity(db)[0]

    with pytest.raises(psycopg.errors.CheckViolation,
                       match="does not say how to stop"):
        db.execute(
            """INSERT INTO outbound_artifact
                   (approval_id, artifact_type, content, created_by,
                    contact_scope, contact_identifier, sender_identity_id,
                    channel, recipient_class)
               VALUES (%s,'OUTREACH_DRAFT','{"body": "hi"}',%s,'PERSON',
                       'A. Landholder',%s,'POST','LANDHOLDER_FROM_REGISTER')""",
            (approval_id, creator, sender))
    db.rollback()


def test_the_body_cannot_be_stripped_afterwards(db):
    """A rule enforced only at insert is one you get around with an UPDATE."""
    artifact_id = draft(db, a_body())
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("""UPDATE outbound_artifact SET content = '{"body": "hi"}'
                      WHERE id = %s""", (artifact_id,))
    db.rollback()


def test_the_gate_view_is_empty_because_the_trigger_refuses_the_row(db):
    draft(db, a_body())
    assert db.execute(
        "SELECT count(*) FROM opt_out_prominence_exception").fetchone()[0] == 0


# ------------------------------------------- rendering, at send time

def test_rendering_substitutes_the_real_link(db):
    body = a_body()
    rendered = message.render(body, "https://crown.example/opt-out/abc")
    assert OPT_OUT_MARKER not in rendered
    assert "https://crown.example/opt-out/abc" in rendered


def test_rendering_refuses_a_body_it_would_not_have_accepted(db):
    with pytest.raises(message.NotProminent):
        message.render("hi", "https://crown.example/opt-out/abc")


# ------------------------------------------- the two implementations agree

CORPUS = [
    None,
    "",
    "hi",
    "no marker at all, just words about land",
    a_body(),
    f"stop here:\n{OPT_OUT_MARKER}\n",
    f"{OPT_OUT_MARKER}",
    f"unsubscribe: {OPT_OUT_MARKER}",
    f"To stop: {OPT_OUT_MARKER}\nOr: {OPT_OUT_MARKER}",
    f"stop here: {OPT_OUT_MARKER}" + "x" * 500,
    "a " * 150 + f"stop {OPT_OUT_MARKER}",
    f"Opt out here:\n{OPT_OUT_MARKER}\n",
    f"Opt-out here:\n{OPT_OUT_MARKER}\n",
    f"remove me:\n{OPT_OUT_MARKER}\n",
    f"no longer wish to hear:\n{OPT_OUT_MARKER}\n",
    f"Māori text about land\nstop:\n{OPT_OUT_MARKER}\n",
    f"stop\ttabbed:\n{OPT_OUT_MARKER}\n",
]


@pytest.mark.parametrize("body", CORPUS)
def test_sql_and_python_agree_on_every_body(db, body):
    """Two implementations of one rule. If they drift, the control silently
    stops firing on the side that matters, and nothing announces it."""
    from_sql = db.execute(
        "SELECT opt_out_is_prominent(%s)", (body,)).fetchone()[0]
    assert from_sql == message.fault(body)
