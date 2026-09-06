"""Constitution §2: every provenance field is mandatory.

A record that cannot fill all of them is a validation failure, not a warning.
It goes to the review queue; it does not enter the graph.

This mirrors the NOT NULL constraints on evidence_record deliberately. The
database is the backstop, but the pipeline must be able to say *which* fields
were missing, and a NOT NULL violation aborts the transaction without telling us.
"""

REQUIRED_FIELDS = (
    "source_reference",
    "source_url",
    "provider",
    "retrieved_at",
    "observed_at",
    "last_verified_at",
    "lane",
    "reliability",
    "evidence_class",
    "confidence",
    "lga",
    "title",
)


def missing_fields(record: dict) -> list[str]:
    """Return the required provenance fields this record cannot fill."""
    return [f for f in REQUIRED_FIELDS if record.get(f) in (None, "")]


def is_valid(record: dict) -> bool:
    return not missing_fields(record)
