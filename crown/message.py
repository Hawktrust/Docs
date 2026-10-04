"""Whether a message draws attention to the way out, or merely contains one.

APP 7.3(c) requires each direct marketing message to **prominently** draw
attention to the opt-out, and s18 of the Spam Act wants an unsubscribe facility
that is clear. 0016 made the opt-out exist and 0024 made the channel lawful;
neither looked at the message itself, so a compliant artefact could carry its
way out in the twelfth line of a footer and nothing would object.

The link cannot be in the body when the body is written: it is an HMAC over the
artefact id, and the artefact does not exist yet. So the body carries a marker
where the link goes, and `render()` substitutes it at send time. Prominence is
then a property of where that marker sits, which is decidable.

WHAT THESE RULES CANNOT DECIDE, and it is most of what "prominent" means to a
person: font size, colour, contrast, whether the mail client renders it, and
whether a human actually notices. What they can decide is whether the way out
was put somewhere a reader would find it, and that is worth having as a
constraint rather than as an intention.

The same rules exist in SQL, as `opt_out_is_prominent()` in migration 0025.
They are compared against each other by tests/test_prominence.py, because two
implementations that drift leave a control that silently stops firing.
"""
import re

OPT_OUT_MARKER = "{{opt-out}}"

# How much message may follow the way out. A footer is fine; pages are not.
TRAILING_ALLOWANCE = 400

# The marker's own line. Longer than this and it is inside a paragraph rather
# than standing on its own, which is how an opt-out gets read past.
LINE_LIMIT = 200

# How far back to look for words telling the reader what the link is for.
LEAD_IN = 200

# A bare link draws attention to nothing. One of these has to be near it.
INVITATION = re.compile(r"stop|unsubscribe|opt[ -]?out|remove|no longer|"
                        r"leave you alone|hear from us")


class NotProminent(Exception):
    """The message contains a way out that a reader would have to hunt for."""


def fault(body) -> str | None:
    """Why this body's opt-out is not prominent, or None if it is.

    Returns a sentence rather than raising, because the same wording is used by
    the readiness view and by the exception, and a caller reporting on many
    messages should not have to catch its way through them.
    """
    if body is None:
        return "the message has no body"
    body = str(body)

    pos = body.find(OPT_OUT_MARKER)
    if pos < 0:
        return "the message does not say how to stop it"

    occurrences = body.count(OPT_OUT_MARKER)
    if occurrences > 1:
        return (f"the message offers {occurrences} ways out; one is a way out, "
                "several is a maze")

    trailing = len(body) - (pos + len(OPT_OUT_MARKER))
    if trailing > TRAILING_ALLOWANCE:
        return (f"the way out has {trailing} characters after it; a reader "
                "would have to hunt for it")

    marker_line = next(l for l in body.split("\n") if OPT_OUT_MARKER in l)
    if len(marker_line) > LINE_LIMIT:
        return ("the way out is inside a paragraph rather than on a line of "
                "its own")

    # Only what comes BEFORE the marker. The marker is literally "{{opt-out}}",
    # so a window including it always matches `opt[ -]?out` and the rule would
    # be satisfied by its own subject — inert, and inert in the direction that
    # passes everything. A test caught that; it is the kind of mistake a rule
    # about its own name invites.
    lead_in = body[max(0, pos - LEAD_IN):pos].lower()
    if not INVITATION.search(lead_in):
        return "nothing near the link tells the reader what it does"

    return None


def check(body) -> None:
    """Raise if the way out would not be found."""
    problem = fault(body)
    if problem is not None:
        raise NotProminent(
            f"{problem}. APP 7.3(c) wants the opt-out drawn to the reader's "
            f"attention, not merely present. Put {OPT_OUT_MARKER} on its own "
            "line near the end, introduced by a sentence saying what it does.")


def render(body: str, link: str) -> str:
    """Substitute the real link for the marker, at send time."""
    check(body)
    return body.replace(OPT_OUT_MARKER, link)


def standard_body(note: str = "") -> str:
    """A body that says why Crown is writing and how to stop it.

    Composed rather than left to each caller, because "remember to include the
    opt-out prominently" is exactly the instruction that gets forgotten on the
    one message that matters. Every artefact `build_content()` assembles is
    compliant by construction; a caller who wants different words can write
    them, and `check()` will tell them if they have buried the way out.
    """
    opening = note.strip() or "Crown is writing to you about land you own."
    return (f"{opening}\n"
            "\n"
            "You can stop hearing from us at any time, immediately, without "
            "an account and without contacting anybody:\n"
            f"{OPT_OUT_MARKER}\n")
