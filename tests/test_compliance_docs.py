"""The cover note has to agree with the documents it covers.

`docs/compliance/README.md` tells a reviewer how many decisions are outstanding
and where. It said seven, split three/three/one, and the real numbers were six,
split three/two/one — wrong in the total and in one of the three parts. Nobody
noticed because nothing counted.

That is the same failure this project has written down twice before: a comment
in migration 0024 about having forgotten row-level security three times, written
immediately before forgetting it a fourth; and 0026's note that "the comment was
not the fix; the test is". A prose count is a comment about the documents. This
is the test.

It matters more here than most places, because the README is what a lawyer reads
first. A cover note that overstates what is outstanding sends them chasing an
item that does not exist; one that understates it lets them miss an item that
does.
"""
import os
import re

HERE = os.path.dirname(__file__)
COMPLIANCE = os.path.join(HERE, "..", "docs", "compliance")

# Every literal `[DECIDE` in each draft, including the ones that are not
# themselves an outstanding decision. Counting occurrences is the part a machine
# can do without judgement, so it is what gets asserted.
OCCURRENCES = {
    "PRIVACY-POLICY.draft.md": 3,
    "BREACH-RESPONSE.draft.md": 4,
    "COLLECTION-NOTICE.draft.md": 2,
    "CONSENT-POSITION.md": 0,
}

# Outstanding decisions, which is a smaller number than the occurrences, and the
# difference is where the old count went wrong. Per file:
#
#   PRIVACY-POLICY     3 = who ratified section 4 and when; whether hosting is
#                          onshore; the policy's URL. All three are real.
#   BREACH-RESPONSE    2 = the roster's mobile number, and the tabletop date.
#                          Its other two occurrences are the legend explaining
#                          the convention, and the note attached to the mobile
#                          blank explaining why email is the wrong channel for
#                          an incident — that note is not a second decision.
#   COLLECTION-NOTICE  1 = the policy's URL again. Its other occurrence is prose
#                          saying the marks below are details inside a settled
#                          shape.
#
# Six blanks over five facts, because the URL is asked for in two documents.
DECISIONS = {
    "PRIVACY-POLICY.draft.md": 3,
    "BREACH-RESPONSE.draft.md": 2,
    "COLLECTION-NOTICE.draft.md": 1,
}
DISTINCT_FACTS = 5

WORDS = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
         6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def read(name):
    with open(os.path.join(COMPLIANCE, name)) as handle:
        return handle.read()


def flat(name):
    """The text with runs of whitespace collapsed.

    These documents are hard-wrapped, so a phrase the README really does
    contain can straddle a newline — "one in the\ncollection notice". The
    first version of this test failed on exactly that and the document was
    correct, which is a test asserting its own formatting rather than the
    claim it means to check.
    """
    return " ".join(read(name).split())


def test_each_draft_carries_the_marks_the_test_says_it_does():
    """If a mark is added or filled, this fails and the next person has to
    recount and update both this test and the README — which is the whole
    point. Failing here is cheaper than a reviewer finding the discrepancy."""
    for name, expected in OCCURRENCES.items():
        actual = len(re.findall(r"\[DECIDE", read(name)))
        assert actual == expected, (
            f"{name} has {actual} `[DECIDE` occurrences, not {expected}. "
            "Recount the outstanding decisions, then update OCCURRENCES, "
            "DECISIONS and the README's stated numbers together.")


def test_the_readme_states_the_real_total():
    """The number a reviewer reads first."""
    readme = flat("README.md")
    total = sum(DECISIONS.values())
    assert f"**{WORDS[total].capitalize()} remain**" in readme, (
        f"the README does not say '**{WORDS[total].capitalize()} remain**', "
        f"and {total} is what the marks actually come to")


def test_the_readme_states_the_real_split():
    """The total being right is not enough — it was the per-document split that
    was wrong last time, with a correct-looking total beside it."""
    readme = flat("README.md")
    for name, count, where in (
        ("PRIVACY-POLICY.draft.md", DECISIONS["PRIVACY-POLICY.draft.md"],
         "in the privacy policy"),
        ("BREACH-RESPONSE.draft.md", DECISIONS["BREACH-RESPONSE.draft.md"],
         "in the breach plan"),
        ("COLLECTION-NOTICE.draft.md", DECISIONS["COLLECTION-NOTICE.draft.md"],
         "in the collection notice"),
    ):
        phrase = f"{WORDS[count]} {where}"
        assert phrase in readme, (
            f"the README does not say '{phrase}'. {name} has {count} "
            "outstanding decisions.")


def test_the_readme_does_not_undercount_the_review_set():
    """Every document in this folder plus the title search path turns on the
    same section 4 position, so a review of a subset is not a review."""
    readme = flat("README.md")
    drafts = [f for f in os.listdir(COMPLIANCE) if f != "README.md"]
    assert len(drafts) == 4, f"the folder now holds {len(drafts)} documents"
    assert "all five together" in readme, (
        "the README asks for a review of some other number of documents than "
        "the four here plus docs/TITLE-SEARCH-PATH.md")
    assert "TITLE-SEARCH-PATH.md" in readme


def test_the_url_is_the_one_fact_asked_for_twice():
    """Which is why six blanks are five facts. If the policy's URL stops
    appearing in both, the arithmetic in the README changes."""
    assert "[DECIDE: URL]" in read("PRIVACY-POLICY.draft.md")
    assert "[DECIDE: URL]" in read("COLLECTION-NOTICE.draft.md")
    assert str(DISTINCT_FACTS) == "5"
    assert "five facts" in flat("README.md")
