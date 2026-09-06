"""The data rights register, enforced in code as well as in the schema.

Constitution §1: a source with no row in data_source cannot be ingested from,
and a source whose row says is_ingestible = false must not be touched at all.
The database CHECK constraint stops a BLOCKED source being marked ingestible;
this module stops the pipeline reaching for one in the first place.
"""
from dataclasses import dataclass


class SourceNotRegistered(Exception):
    """No row in the data rights register for this source code."""


class SourceNotIngestible(Exception):
    """The register has a row, and it forbids ingestion."""


@dataclass(frozen=True)
class RegisteredSource:
    id: str
    code: str
    provider: str
    lane: str
    licence_reference: str | None
    attribution_text: str | None
    register_confirmed_by: str | None


def resolve(conn, code: str) -> RegisteredSource:
    """Look up a source and refuse to return one that may not be ingested."""
    row = conn.execute(
        """
        SELECT id, code, provider, lane, licence_reference, attribution_text,
               register_confirmed_by, is_ingestible
        FROM data_source WHERE code = %s
        """,
        (code,),
    ).fetchone()

    if row is None:
        raise SourceNotRegistered(
            f"{code} has no row in the data rights register. "
            "Register the source and have a named adviser confirm it before ingesting."
        )

    *fields, is_ingestible = row
    if not is_ingestible:
        raise SourceNotIngestible(
            f"{code} is registered as lane {fields[3]} with is_ingestible = false. "
            "Do not ingest, cache or redistribute it."
        )

    return RegisteredSource(*fields)
