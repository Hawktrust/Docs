"""Source adapter: Victorian planning scheme amendments.

The adapter turns a retrieved payload into normalised amendment records. It is
the only part of the pipeline that knows anything about the shape of the source.

Two entry points:

  from_json(payload)  — the normalised interchange shape, defined below. Fully
                        implemented, and what the pipeline and tests run on.

  from_html(body)     — parsing the live amendments page. NOT IMPLEMENTED. The
                        page structure has never been observed from this
                        environment (egress to planning.vic.gov.au is denied by
                        policy), and a parser written against a guessed DOM
                        would produce plausible records with real-looking
                        provenance. That is exactly the silent failure the
                        ticket's human review is meant to catch, so it raises
                        instead.

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
    """The live page format has not been observed, so it cannot be parsed."""


def classify(status: str | None) -> str:
    return CLASSIFICATION_RULE.get((status or "").strip().upper(), DEFAULT_CLASS)


def from_html(body: str, source_url: str):
    raise SourceFormatUnknown(
        "The planning.vic.gov.au amendments page has not been observed from this "
        "environment, so there is no verified parser for it. Provide a saved "
        "response, or allowlist the host and write the parser against the real "
        "markup. Do not guess at the DOM: a wrong parser yields records that look "
        "correctly provenanced and are not."
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
