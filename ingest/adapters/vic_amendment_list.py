"""Source adapter: DTP's official *List of Amendments* PDF, one per planning scheme.

WHAT THIS IS, AND WHAT IT IS NOT.

The planning schemes portal is a JavaScript app whose data comes from
api.app.planning.vic.gov.au, and that host is refused by network policy. This is
a different document by the same publisher: the per-scheme amendment list that
DTP generates and serves from its own production bucket, named by the portal's
own /config.json as `amendmentListUrl`. Each page is headed with the scheme name
and marked OFFICIAL, and each entry gives an amendment number, the date it came
into operation, and a description.

So a record from here is a real amendment, fetched by Crown from the publisher's
own origin, repeatable — DIRECT_FETCH, and eligible to be AUTHORITATIVE under
migration 0006. What it is NOT is the amendment's own page: source_url is the PDF
that was actually retrieved, never a portal URL that was not.

THE LIST IS BEHIND THE PRESENT, and every caller has to know it. At the time of
writing DTP's copies were last modified 2024-08-22 and their newest entry is
3 August 2023. The list is therefore good for amendments already in operation and
silent about everything since — including every amendment in seeds/relay_leads.json.
It cannot answer "what changed this month". `list_as_at` on each record carries
the document's own Last-Modified so a reader is never left to assume.

WHAT IT REFUSES TO DO. Three things this deliberately does not attempt, because
each would mean inventing something:

  * A geography finer than the LGA. The descriptions name streets and suburbs in
    prose. Pulling a suburb out of a sentence is inference, and ingestion
    concludes nothing — so geography is left absent and the opportunity rule
    falls back to the LGA.
  * A date it cannot read. A handful of entries in DTP's own text layer carry a
    malformed day: "218 NOV 2005" is 18 or 28 or 21 and nothing in the document
    says which. Those are counted and reported, never guessed. A wrong gazettal
    date is the exact failure the CONTRADICTED leads exist to warn about.
  * A scheme it was not given. The PDF's own header names the scheme; if it does
    not match the one asked for, the file is refused rather than attributed to
    the wrong council.
"""
import re
from datetime import date

# The scheme code in the object name, and the LGA it belongs to. The codes are
# the same ones DTP suffixes onto recent amendment numbers — C266wynd, C232melt,
# C272hume, C287wsea — so the mapping is checked against the document's own
# header at parse time rather than trusted.
SCHEMES = {
    "Wyndham": "wynd",
    "Melton": "melt",
    "Hume": "hume",
    "Whittlesea": "wsea",
}

LIST_URL = "https://prd-vicplanning-app.s3.ap-southeast-2.amazonaws.com/amlist/amlist_s_{code}.pdf"

# An amendment that has come into operation has been gazetted. This list is
# titled for exactly those, so the status is a property of the document rather
# than a reading of any one entry.
STATUS = "GAZETTED"

_MONTHS = {m: n for n, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
     "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}

# "C264wynd 25 NOV 2022 The Amendment alters ..." and the Part variants
# "C11 (Part 1) 1 NOV 2002 ..." / "C53 Part 1 31 MAY 2007 ...", which are real
# entries and were silently dropped by a first pattern that did not allow for them.
_ENTRY = re.compile(
    r"^(?P<number>(?:VC|GC|C|NPSA|NPS)\d+[A-Za-z]*)"
    r"(?:\s*\(?\s*Part\s*(?P<part>\d+)\s*\)?)?"
    r"\s+(?P<day>\d{1,2})\s+(?P<month>[A-Z]{3})\s+(?P<year>\d{4})"
    r"\s*(?P<text>.*)$")

# The same shape with an impossible day. Not a parse failure to swallow: these
# are real amendments whose date this document states ambiguously.
_MALFORMED_DATE = re.compile(
    r"^(?:VC|GC|C|NPSA|NPS)\d+[A-Za-z]*"
    r"(?:\s*\(?\s*Part\s*\d+\s*\)?)?"
    r"\s+\d{3,}\s+[A-Z]{3}\s+\d{4}\s")

_SCHEME_HEADER = re.compile(r"^(?P<scheme>[A-Z][A-Z \-']+?)\s+PLANNING SCHEME\s*$")

# A scheme-local amendment: "C266wynd", "C41". Everything else — VC, GC, NPS — is
# an amendment to the Victoria Planning Provisions or a combined amendment, and
# changes many schemes or all of them at once.
_SCHEME_LOCAL = re.compile(r"^C\d")


def _is_scheme_local(number: str) -> bool:
    return bool(_SCHEME_LOCAL.match(number))

# Repeated on every page by the generator. Dropping them by exact text rather
# than by position, because the number of header lines varies with the page.
_NOISE = {
    "OFFICIAL", "Amendment", "number", "In operation", "from",
    "Brief description", "LIST OF AMENDMENTS",
}
_PAGE_MARKER = re.compile(r"^LIST OF AMENDMENTS\s+PAGE \d+ OF \d+\s*$")


class ListFormatUnexpected(Exception):
    """The document is not the amendment list this adapter knows how to read.

    Raised rather than returning nothing, because an empty result is
    indistinguishable from "this scheme has no amendments" and would let a caller
    record that it checked.
    """


class Parsed:
    """What one list yielded, including what it could not read.

    The skipped entries are carried, not logged and forgotten: a caller that
    reports "412 amendments ingested" while four were dropped is telling the
    reader something false by omission.
    """

    def __init__(self, scheme: str, lga: str, records: list, skipped: list):
        self.scheme = scheme
        self.lga = lga
        self.records = records
        self.skipped = skipped

    def summary(self) -> str:
        line = f"{self.lga}: {len(self.records)} amendment(s) read from the list"
        if self.skipped:
            line += (f"; {len(self.skipped)} skipped for an unreadable date "
                     f"({', '.join(s.split()[0] for s in self.skipped[:5])}"
                     f"{'...' if len(self.skipped) > 5 else ''})")
        return line


def url_for(lga: str) -> str:
    """The exact object this adapter reads for one LGA."""
    try:
        return LIST_URL.format(code=SCHEMES[lga])
    except KeyError:
        raise ListFormatUnexpected(
            f"no planning scheme code known for {lga!r}; known: "
            f"{', '.join(sorted(SCHEMES))}") from None


def _pages(body) -> list[str]:
    """Text per page.

    A list is already-extracted pages, which is how the tests supply real text
    without carrying a PDF. Anything else is a PDF — a path or an open file. A
    plain string is NOT treated as text: a path read as though it were the
    document is the kind of mistake that reports "no amendments found" for a file
    that was never opened.
    """
    if isinstance(body, list):
        return body
    import pypdf                                   # imported here: only the PDF
    reader = pypdf.PdfReader(body)                 # path needs it
    return [page.extract_text() or "" for page in reader.pages]


def from_pdf(body, lga: str, *, list_as_at: str | None = None,
             scheme_local_only: bool = True) -> Parsed:
    """Read one scheme's amendment list.

    body is a file path, an open file, or a list of already-extracted pages.
    lga names the council the caller asked for, and is checked against the
    document's own header.

    scheme_local_only keeps the C-numbered amendments and drops the VC and GC
    ones. That is a judgement about what an amendment *signals*, and it is the
    default because getting it wrong the other way is loud: VC238 changed all 79
    planning schemes, so ingesting it would raise a CONFIRMED opportunity in
    every LGA in Victoria on the strength of a statewide provisions tweak that
    says nothing about anybody's land. The statewide ones are still real
    amendments, so this is a filter and not a denial — pass False for the
    complete list.
    """
    pages = _pages(body)
    if not pages:
        raise ListFormatUnexpected("the document has no pages")

    scheme = None
    for page in pages:
        for line in page.split("\n"):
            found = _SCHEME_HEADER.match(line.strip())
            if found:
                scheme = found.group("scheme").strip().title()
                break
        if scheme:
            break
    if scheme is None:
        raise ListFormatUnexpected(
            "no '<SCHEME> PLANNING SCHEME' header found; this is not the "
            "amendment list, and guessing which council it describes is how a "
            "record ends up attributed to the wrong one")
    if scheme.lower() != lga.strip().lower():
        raise ListFormatUnexpected(
            f"asked for {lga} and the document is headed {scheme}. Refusing: an "
            "amendment attributed to the wrong council is worse than none")

    records: list[dict] = []
    skipped: list[str] = []
    current: dict | None = None

    for page in pages:
        for raw in page.split("\n"):
            line = raw.rstrip()
            stripped = line.strip()
            if not stripped or stripped in _NOISE or _PAGE_MARKER.match(stripped):
                continue
            if _SCHEME_HEADER.match(stripped):
                continue

            entry = _ENTRY.match(stripped)
            if entry:
                if scheme_local_only and not _is_scheme_local(entry.group("number")):
                    # Still closes the current entry: a dropped amendment's
                    # description must not be glued onto the one before it.
                    current = None
                    continue
                current = _start(entry, lga)
                if current is None:            # a date the calendar rejects
                    skipped.append(stripped)
                else:
                    records.append(current)
                continue

            if _MALFORMED_DATE.match(stripped):
                # An entry whose day this document states ambiguously. Reported,
                # not guessed, and it closes the current entry so its
                # description does not absorb another amendment's text.
                skipped.append(stripped)
                current = None
                continue

            if current is not None:
                current["summary"] = f"{current['summary']} {stripped}".strip()

    if not records:
        raise ListFormatUnexpected(
            f"the {scheme} list parsed to no amendments at all, which means the "
            "document's shape has changed; a parser that silently returns nothing "
            "would look like a scheme with no history")

    for record in records:
        _finish(record, list_as_at)

    return Parsed(scheme=scheme, lga=lga, records=records, skipped=skipped)


def _start(entry, lga: str) -> dict | None:
    month = _MONTHS.get(entry.group("month"))
    if month is None:
        return None
    try:
        in_operation = date(int(entry.group("year")), month, int(entry.group("day")))
    except ValueError:
        # e.g. 31 FEB. The document says it; the calendar does not.
        return None

    printed = entry.group("number")
    part = entry.group("part")
    return {
        # What the document prints, kept verbatim so the record can be checked
        # against the page it came from.
        "printed_as": f"{printed} (Part {part})" if part else printed,
        "_printed_number": printed,
        "_part": part,
        "lga": lga,
        "status": STATUS,
        "observed_at": in_operation.isoformat(),
        "summary": entry.group("text").strip(),
    }


def _finish(record: dict, list_as_at: str | None) -> None:
    printed = record.pop("_printed_number")
    part = record.pop("_part")

    # The reference has to be unique, and only a scheme-local number is not.
    #
    # "C41" appears in every scheme's list and means a different amendment in
    # each, so the scheme code is appended where the document did not already
    # carry it — the same suffix DTP itself uses on recent numbers. It is Crown's
    # disambiguation, not a claim that the publisher writes older ones that way,
    # which is why printed_as keeps the document's own text.
    #
    # VC and GC numbers are left exactly as printed. VC238 is one amendment to the
    # Victoria Planning Provisions, not four; "VC238wynd" would invent a
    # per-scheme identifier that does not exist. It appears in four lists because
    # it changed four schemes, and four evidence records differing by lga is the
    # truthful way to record that.
    if _is_scheme_local(printed):
        code = SCHEMES[record["lga"]]
        reference = printed if printed.lower().endswith(code) else f"{printed}{code}"
    else:
        reference = printed
    if part:
        reference = f"{reference}-part{part}"
    record["amendment_number"] = reference

    summary = " ".join(record["summary"].split())
    record["summary"] = summary
    # A title has to fit a list on a page; the whole description stays in summary.
    record["title"] = summary if len(summary) <= 120 else summary[:117].rstrip() + "..."
    if list_as_at:
        # The document's own Last-Modified. Carried so nobody has to assume the
        # list is current — it is not, and it says so here.
        record["list_as_at"] = list_as_at
    # No detail_url on purpose: the pipeline falls back to the URL actually
    # retrieved, which is the PDF. A portal URL here would claim a page that was
    # never fetched.
    # No geography on purpose: see the module docstring.
