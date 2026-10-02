"""Source adapter: Victorian planning scheme amendments.

The adapter turns a retrieved payload into normalised amendment records. It is
the only part of the pipeline that knows anything about the shape of the source.

Two entry points:

  from_json(payload)  — the normalised interchange shape, defined below. Fully
                        implemented, and what the pipeline and tests run on.

  from_html(body)     — parsing the live amendments page. NOT IMPLEMENTED, and
                        now for a better reason than not having seen the page.
                        The page WAS observed on 2026-09-27, once
                        planning-schemes.app.planning.vic.gov.au was
                        allowlisted: it is a 1.5 KB Vue shell that contains no
                        amendment content at all. Every path on that host
                        returns the same shell. The amendment data is served by
                        api.app.planning.vic.gov.au, a separate host that is
                        still denied by network policy at CONNECT.

                        So there is nothing in this body to parse, and no DOM a
                        parser could be written against. A parser that dug a
                        record out of it anyway would be inventing one — with a
                        real URL and a real retrieval timestamp wrapped around
                        content nobody ever served. That is exactly the silent
                        failure the ticket's human review is meant to catch, so
                        it raises instead.

Interchange shape — a JSON list of objects, each:

    {
      "amendment_number": "C123wynd",     # stable upstream id, required
      "lga":              "Wyndham",      # required
      "title":            "...",          # required
      "status":           "GAZETTED",     # GAZETTED | EXHIBITED | <other>
      "summary":          "...",          # optional
      "observed_at":      "2026-08-14",   # when the fact was true upstream, required
      "detail_url":       "https://...",  # exact page this record came from, required
      "geography":        {"suburbs": ["Tarneit"]}   # optional
    }
"""
from datetime import datetime, timezone

# Constitution §2 / ticket item 2, stated once, in code, where it can be read:
#
#   a gazetted amendment is settled law upstream          -> FACT
#   an exhibited-but-undecided amendment is not yet settled -> HYPOTHESIS
#   anything else we have not established                   -> UNKNOWN
#
# Nothing here produces INFERENCE. An inference is something Crown concluded,
# and ingestion concludes nothing — it only records what the source said.
CLASSIFICATION_RULE = {
    "GAZETTED": "FACT",
    "EXHIBITED": "HYPOTHESIS",
}
DEFAULT_CLASS = "UNKNOWN"

# The provider is the State Government of Victoria publishing its own statutory
# instrument, so the source is authoritative for what the amendment says.
RELIABILITY = "AUTHORITATIVE"

# Confidence describes our reading of the record, not the model's enthusiasm.
# A gazetted amendment read straight off the register is not a guess; an
# unrecognised status is.
CONFIDENCE = {"FACT": 1.0, "HYPOTHESIS": 0.9}
DEFAULT_CONFIDENCE = 0.5


class SourceFormatUnknown(NotImplementedError):
    """The retrieved body carries no amendment content, so it cannot be parsed.

    Raised, rather than returning an empty list, because an empty result is
    indistinguishable from "this LGA has no amendments" and would let the
    pipeline resolve a lead as though it had been checked.
    """


def classify(status: str | None) -> str:
    return CLASSIFICATION_RULE.get((status or "").strip().upper(), DEFAULT_CLASS)


def from_html(body: str, source_url: str):
    raise SourceFormatUnknown(
        f"no verified parser exists for {source_url} ({len(body)} bytes "
        "retrieved). Observed 2026-09-27: planning-schemes.app.planning.vic.gov.au "
        "serves the same 1.5 KB Vue shell for every path, amendment pages "
        "included, so there is no amendment markup on it to write a parser "
        "against. The data comes from api.app.planning.vic.gov.au, which network "
        "policy still denies at CONNECT — allowlisting the portal alone is not "
        "enough. Until that host is open, use an operator capture "
        "(tools/collector.html), which renders the page in a real browser. Do not "
        "guess at the DOM: a wrong parser yields records that look correctly "
        "provenanced and are not."
    )


def from_json(payload: list[dict], retrieval, source) -> list[dict]:
    """Normalise interchange records into evidence_record field dicts.

    Missing fields are left absent rather than filled in. The provenance
    validator decides what happens next; this function never invents a value to
    make a record pass.
    """
    records = []
    for item in payload:
        evidence_class = classify(item.get("status"))
        records.append(
            {
                "source_reference": item.get("amendment_number"),
                "source_url": item.get("detail_url") or retrieval.url,
                "provider": source.provider,
                "retrieved_at": retrieval.retrieved_at,
                "observed_at": _parse_date(item.get("observed_at")),
                "last_verified_at": retrieval.retrieved_at,
                "lane": source.lane,
                "reliability": RELIABILITY,
                "evidence_class": evidence_class,
                "confidence": CONFIDENCE.get(evidence_class, DEFAULT_CONFIDENCE),
                "lga": item.get("lga"),
                "title": item.get("title"),
                "summary": item.get("summary"),
                "amendment_status": item.get("status"),
                "geography": item.get("geography"),
                # the stable upstream id, used for idempotency
                "source_ref": item.get("amendment_number"),
            }
        )
    return records


def _parse_date(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
