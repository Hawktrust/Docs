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


class AutomatedAccessNotPermitted(Exception):
    """The publisher's terms do not permit a crawler, or nobody has read them.

    This is separate from ingestibility on purpose. A person opening the page in
    their own browser is ordinary permitted use — that is what operator capture
    is. A program fetching it on a schedule is what terms speak to.
    """


@dataclass(frozen=True)
class RegisteredSource:
    id: str
    code: str
    provider: str
    lane: str
    licence_reference: str | None
    attribution_text: str | None
    register_confirmed_by: str | None
    automated_access: str = "UNKNOWN"


def resolve(conn, code: str, *, automated: bool = False) -> RegisteredSource:
    """Look up a source and refuse to return one that may not be ingested.

    Pass automated=True from anything that fetches on its own — a poller, a
    crawler, a scheduled job. That path additionally requires the publisher's
    terms to permit it. An operator capture passes automated=False, because a
    person reading a page in a browser is not a crawler.
    """
    row = conn.execute(
        """
        SELECT id, code, provider, lane, licence_reference, attribution_text,
               register_confirmed_by, automated_access::text, is_ingestible
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

    access = fields[7]
    if automated and access not in ("PERMITTED", "PUBLISHER_FEED"):
        raise AutomatedAccessNotPermitted(
            f"{code} has automated_access = {access}. "
            + ("The publisher's terms prohibit automated retrieval; a person may "
               "still open the page themselves."
               if access == "PROHIBITED" else
               "Nobody has read the publisher's terms, so the crawler does not run. "
               "Record a position with a name against it first.")
        )

    return RegisteredSource(*fields)
