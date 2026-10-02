"""DTP's official List of Amendments, and what may be claimed from reading it.

Acceptance criterion 1 wants a real amendment from each of three LGAs with full
provenance. This is the path that supplies it: the per-scheme PDF DTP generates
and serves from its own production bucket, which is reachable where the portal's
JSON API is not.

The fixtures are excerpts of the real documents, not hand-written text. A parser
tested only against markup someone invented is the failure mode the vic_planning
adapter refuses to risk, and it would be no better here.

What these tests defend is mostly what the adapter must NOT do: invent a
geography, invent a date it cannot read, invent a per-scheme identifier for a
statewide amendment, or attribute a document to the wrong council.
"""
import os

import pytest

from ingest.adapters import vic_amendment_list as amendment_list

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
WYNDHAM = os.path.join(FIXTURES, "amlist_wynd_excerpt.pdf")
WHITTLESEA = os.path.join(FIXTURES, "amlist_wsea_excerpt.pdf")


# ------------------------------------------------------------------- it reads

def test_it_reads_real_amendments_from_the_real_document():
    parsed = amendment_list.from_pdf(WYNDHAM, "Wyndham")
    assert parsed.records, "the excerpt holds amendments"
    assert parsed.scheme == "Wyndham"

    by_reference = {r["amendment_number"]: r for r in parsed.records}
    # C10 is the first entry of the real Wyndham list, in operation 18 NOV 1999.
    record = by_reference["C10wynd"]
    assert record["observed_at"] == "1999-11-18"
    assert record["status"] == "GAZETTED"
    assert "Development Contributions Plan Overlay" in record["summary"]


def test_a_description_that_wraps_is_kept_whole():
    """Entries run to several lines; a summary cut at the line break would lose
    most of what the amendment says."""
    parsed = amendment_list.from_pdf(WYNDHAM, "Wyndham")
    longest = max(parsed.records, key=lambda r: len(r["summary"]))
    assert len(longest["summary"]) > 200
    assert "  " not in longest["summary"], "whitespace is normalised"


def test_the_title_is_short_and_the_summary_is_not_truncated():
    parsed = amendment_list.from_pdf(WYNDHAM, "Wyndham")
    for record in parsed.records:
        assert len(record["title"]) <= 120
        assert len(record["summary"]) >= len(record["title"]) - 3


def test_a_part_suffixed_entry_is_not_dropped():
    """"C11 (Part 1) 1 NOV 2002" is a real entry. A first pattern that did not
    allow for the Part suffix silently skipped 36 amendments across four lists."""
    parsed = amendment_list.from_pdf(WYNDHAM, "Wyndham")
    parts = [r for r in parsed.records if "-part" in r["amendment_number"]]
    assert parts, "the excerpt includes an entry with a Part suffix"
    assert parts[0]["printed_as"].startswith("C")
    assert "Part" in parts[0]["printed_as"]


# -------------------------------------------------------- it refuses to invent

def test_an_unreadable_date_is_skipped_and_counted_not_guessed():
    """DTP's own text layer states some days ambiguously — "218 NOV 2005" is 18
    or 28 or 21. A wrong gazettal date is the exact failure the CONTRADICTED
    leads exist to warn about."""
    parsed = amendment_list.from_pdf(WHITTLESEA, "Whittlesea")
    assert parsed.skipped, "the excerpt carries an entry with a malformed day"
    assert any("218 NOV 2005" in s for s in parsed.skipped)
    # and it is not in the records under any date
    assert not any(r["printed_as"] == "C64" for r in parsed.records)
    # and the run says so out loud
    assert "skipped" in parsed.summary()


def test_no_geography_finer_than_the_lga_is_claimed():
    """The descriptions name streets in prose. Pulling a suburb out of a sentence
    is inference, and ingestion concludes nothing."""
    parsed = amendment_list.from_pdf(WYNDHAM, "Wyndham")
    assert all("geography" not in r for r in parsed.records)


def test_a_statewide_amendment_is_left_out_by_default():
    """VC238 changed all 79 planning schemes. Ingesting it would raise a
    CONFIRMED opportunity in every LGA in Victoria on the strength of a
    provisions tweak that says nothing about anybody's land."""
    default = amendment_list.from_pdf(WYNDHAM, "Wyndham")
    assert not any(r["printed_as"].startswith(("VC", "GC"))
                   for r in default.records)

    everything = amendment_list.from_pdf(WYNDHAM, "Wyndham",
                                         scheme_local_only=False)
    assert len(everything.records) > len(default.records)
    assert any(r["printed_as"].startswith("VC") for r in everything.records)


def test_a_statewide_amendment_keeps_the_number_the_publisher_gave_it():
    """VC238 is one amendment, not one per scheme. "VC238wynd" would be an
    identifier that does not exist."""
    everything = amendment_list.from_pdf(WYNDHAM, "Wyndham",
                                         scheme_local_only=False)
    statewide = [r for r in everything.records if r["printed_as"].startswith("VC")]
    assert statewide
    for record in statewide:
        assert record["amendment_number"] == record["printed_as"]
        assert "wynd" not in record["amendment_number"]


def test_a_scheme_local_number_is_qualified_because_it_has_to_be():
    """"C41" is a different amendment in every scheme's list."""
    parsed = amendment_list.from_pdf(WYNDHAM, "Wyndham")
    bare = [r for r in parsed.records
            if not r["printed_as"].lower().endswith("wynd")
            and "Part" not in r["printed_as"]]
    assert bare, "the older entries print a bare number"
    for record in bare:
        assert record["amendment_number"] == record["printed_as"] + "wynd"
        # what the document actually printed is still recoverable
        assert "wynd" not in record["printed_as"]


def test_the_document_is_refused_if_it_names_a_different_council():
    """An amendment attributed to the wrong council is worse than none."""
    with pytest.raises(amendment_list.ListFormatUnexpected, match="Refusing"):
        amendment_list.from_pdf(WYNDHAM, "Whittlesea")


def test_a_document_with_no_scheme_header_is_refused():
    with pytest.raises(amendment_list.ListFormatUnexpected,
                       match="not the amendment list"):
        amendment_list.from_pdf(["some other document entirely"], "Wyndham")


def test_a_list_that_parses_to_nothing_is_an_error_not_an_empty_result():
    """An empty result is indistinguishable from a scheme with no history, and
    would let a caller record that it checked."""
    with pytest.raises(amendment_list.ListFormatUnexpected, match="no amendments at all"):
        amendment_list.from_pdf(["WYNDHAM PLANNING SCHEME\nOFFICIAL\n"], "Wyndham")


def test_an_unknown_lga_has_no_url_rather_than_a_guessed_one():
    with pytest.raises(amendment_list.ListFormatUnexpected, match="no planning scheme code"):
        amendment_list.url_for("Casey")


def test_the_url_is_the_publishers_own_object():
    assert amendment_list.url_for("Wyndham").endswith("/amlist/amlist_s_wynd.pdf")
    assert "planning" in amendment_list.url_for("Melton")


# ------------------------------------------------------- the staleness travels

def test_the_lists_own_date_is_carried_on_every_record():
    """The list is behind the present and a reader must never have to assume
    otherwise."""
    as_at = "Thu, 22 Aug 2024 01:09:47 GMT"
    parsed = amendment_list.from_pdf(WYNDHAM, "Wyndham", list_as_at=as_at)
    assert all(r["list_as_at"] == as_at for r in parsed.records)


def test_no_detail_url_is_claimed():
    """The pipeline falls back to the URL actually retrieved. A portal URL here
    would name a page that was never fetched."""
    parsed = amendment_list.from_pdf(WYNDHAM, "Wyndham")
    assert all("detail_url" not in r for r in parsed.records)


# ------------------------------------------------- it lands as real evidence

def test_ingesting_the_list_produces_authoritative_real_evidence(db):
    """End to end through the real pipeline: this is what makes AC1 pass."""
    from ingest import registry
    from ingest.fetch import Retrieval
    from ingest.pipeline import ingest
    from datetime import datetime, timezone

    source = registry.resolve(db, "VIC_PLANNING_AMENDMENTS")
    parsed = amendment_list.from_pdf(WYNDHAM, "Wyndham")
    url = amendment_list.url_for("Wyndham")
    retrieval = Retrieval(url=url, retrieved_at=datetime.now(timezone.utc),
                          status_code=200, body="", content_type="application/pdf")

    report = ingest(db, source, retrieval, parsed.records, "Wyndham")
    assert len(report.ingested) == len(parsed.records)
    assert not report.review_queued

    row = db.execute(
        """SELECT retrieval_method, reliability::text, evidence_class::text,
                  origin::text, source_url, geography
             FROM evidence_record WHERE source_reference = 'C10wynd'""").fetchone()
    assert row[0] == "DIRECT_FETCH"      # Crown fetched it and can fetch it again
    assert row[1] == "AUTHORITATIVE"     # 0006 permits it for a direct fetch
    assert row[2] == "FACT"              # in operation upstream, so settled
    assert row[3] == "REAL"
    assert row[4] == url, "the URL recorded is the document actually retrieved"
    assert row[5] is None, "no geography was invented"

    # AC2: a second run of the same document adds nothing.
    again = ingest(db, source, retrieval, parsed.records, "Wyndham")
    assert not again.ingested
    assert len(again.duplicates) == len(parsed.records)


def test_it_makes_the_readiness_gate_pass(db):
    """REAL_EVIDENCE_EXISTS is the check AC1 is measured by."""
    from crown import readiness
    from ingest import registry
    from ingest.fetch import Retrieval
    from ingest.pipeline import ingest
    from datetime import datetime, timezone

    before = {c.code: c for c in readiness.check(db).checks}
    assert not before["REAL_EVIDENCE_EXISTS"].passes

    source = registry.resolve(db, "VIC_PLANNING_AMENDMENTS")
    parsed = amendment_list.from_pdf(WYNDHAM, "Wyndham")
    ingest(db, source, Retrieval(url=amendment_list.url_for("Wyndham"),
                                 retrieved_at=datetime.now(timezone.utc),
                                 status_code=200, body="",
                                 content_type="application/pdf"),
           parsed.records, "Wyndham")

    after = {c.code: c for c in readiness.check(db).checks}
    assert after["REAL_EVIDENCE_EXISTS"].passes
