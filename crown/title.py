"""The lawful route to a registered proprietor.

Victoria's Titles Register is the authoritative record of who owns a parcel, and
it is not open data. The commercial platforms that show an owner's name hold
commercial licences to state land registry data; the route open to Crown is the
same register, searched one property at a time, through LANDATA or an
Information Broker, for a fee and for a purpose it can state.

So this module does not fetch anything. It records a paid act and refuses to
record one the register entry does not yet permit. The refusals come from the
database — migration 0031 holds them as triggers, so they apply to every writer
and not only to callers who come through here — and what this module adds is the
sentence before the attempt rather than after it, plus the audit row.

Two gates, satisfied by different work:

  the licence     somebody has read it and their name is on the register entry.
                  Until then no search can be recorded at all.
  the basis       APP 7, plus any register-specific restriction on marketing
                  use, settles whether Crown may hold the owner's name for the
                  use it has in mind. Until then a search can be recorded and
                  paid for, and its result is a volume/folio and a date.

A search recorded without a name cannot gain one later. That is deliberate: the
alternative is a workflow where the gate is closed, the search happens anyway,
and the name is filled in once the paperwork catches up.
"""
from . import audit

ACTOR_AGENT = "crown.title"

SOURCE_CODE = "LANDATA_TITLES"

# There is no 'RESEARCH' and no 'GENERAL'. Those are not purposes; they are the
# absence of one, and APP 3 and APP 6 are both questions about purpose.
PURPOSES = ("OPPORTUNITY_SHORTLIST", "MANDATE_MATCH",
            "VENDOR_INSTRUCTION", "OWNER_REQUEST")

# The two purposes where the property came to Crown rather than Crown going
# looking, so there is nothing on a shortlist to point at.
UNSOLICITED = ("VENDOR_INSTRUCTION", "OWNER_REQUEST")

# A person logging into the portal. 0006 caps what an operator capture can ever
# be relied on as, and that cap is correct here too.
METHODS = ("DIRECT_FETCH", "OPERATOR_CAPTURE", "MANUAL_ENTRY")


class TitleSearchRefused(Exception):
    """The search as offered is not one the register entry permits."""


def readiness(conn):
    """What is still outstanding before a registry can be searched.

    Rows for every licensed source that carries personal information, with the
    blocker spelled out. `blocker` is None when there is nothing left to do.
    """
    return conn.execute(
        """SELECT code, display_name, provider, licence_read,
                  basis_for_the_name, entry_signed, blocker
           FROM title_search_readiness ORDER BY code""").fetchall()


def blockers(conn, source_code: str = SOURCE_CODE) -> list[str]:
    """The outstanding work for one source, as sentences, or an empty list."""
    row = conn.execute(
        """SELECT licence_read, basis_for_the_name, entry_signed
           FROM title_search_readiness WHERE code = %s""",
        (source_code,)).fetchone()
    if row is None:
        raise TitleSearchRefused(
            f"{source_code} is not a licensed source carrying personal "
            "information, so it is not a land registry this module can record "
            "a search against")

    licence_read, basis, signed = row
    out = []
    if not licence_read:
        out.append(
            f"nobody has read {source_code}'s licence. No search can be "
            "recorded until terms_read_by names who read it.")
    if not basis:
        out.append(
            f"{source_code} has no privacy basis on file. A search can be "
            "recorded and paid for; the owner's name cannot be stored.")
    if not signed:
        out.append(
            f"no named adviser has signed {source_code}'s register entry.")
    return out


def request(conn, *, searched_for: str, purpose: str, fee_cents: int,
            requested_by, source_code: str = SOURCE_CODE, parcel_id=None,
            opportunity_id=None, provider_reference: str | None = None,
            retrieval_method: str = "OPERATOR_CAPTURE", origin: str = "REAL",
            correlation_id=None) -> str:
    """Record a search about to be made, and what it costs.

    The result is recorded separately, by `record_result`, because the search is
    paid for whether or not anything useful comes back — which is the number
    worth watching.
    """
    if purpose not in PURPOSES:
        raise TitleSearchRefused(
            f"unknown purpose {purpose}. A search with no stated purpose "
            "cannot be shown to be within one.")
    if retrieval_method not in METHODS:
        raise TitleSearchRefused(f"unknown retrieval method {retrieval_method}")
    if not searched_for or not searched_for.strip():
        raise TitleSearchRefused("a search records what was actually searched")
    if fee_cents is None or fee_cents < 0:
        raise TitleSearchRefused("a search records what it cost, including zero")
    if purpose not in UNSOLICITED and parcel_id is None and opportunity_id is None:
        raise TitleSearchRefused(
            f"a {purpose} search must name the parcel or the opportunity it "
            "came from. The register is read in answer to a question Crown "
            "already had; searching without one is the shape a licence "
            "condition and APP 7 are both aimed at.")

    source_id = conn.execute(
        "SELECT id FROM data_source WHERE code = %s", (source_code,)).fetchone()
    if source_id is None:
        raise TitleSearchRefused(f"{source_code} is not in the data rights register")

    search_id = conn.execute(
        """INSERT INTO title_search
               (source_id, searched_for, parcel_id, opportunity_id, purpose,
                requested_by, provider_reference, fee_cents, retrieval_method,
                origin)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (source_id[0], searched_for.strip(), parcel_id, opportunity_id, purpose,
         requested_by, provider_reference, fee_cents, retrieval_method, origin),
    ).fetchone()[0]

    audit.write(conn, correlation_id or audit.new_correlation_id(),
                "TITLE_SEARCH_REQUESTED", "title_search", search_id,
                new_state={"purpose": purpose, "fee_cents": fee_cents,
                           "source": source_code, "searched_for": searched_for.strip()},
                actor_user_id=requested_by, actor_agent=ACTOR_AGENT)
    return str(search_id)


def record_result(conn, search_id, *, retrieved_at, volume_folio=None,
                  registered_proprietor=None, proprietor_address=None,
                  is_company=None, provider_reference=None,
                  recorded_by=None, correlation_id=None) -> None:
    """What the register said, as at a date.

    Once recorded it is frozen: the register's answer is evidence, and if it has
    changed that is a new search on a new date. The one permitted later change
    is removal, which the retention sweep makes.

    Storing the proprietor columns will be refused by the database unless the
    source carries a privacy basis for the intended use. The volume/folio and
    the date are facts about land and are storable either way.
    """
    rows = conn.execute(
        """UPDATE title_search
           SET volume_folio = %s,
               registered_proprietor = %s,
               proprietor_address = %s,
               is_company = %s,
               provider_reference = coalesce(%s, provider_reference),
               result_retrieved_at = %s
           WHERE id = %s AND result_retrieved_at IS NULL""",
        (volume_folio, registered_proprietor, proprietor_address, is_company,
         provider_reference, retrieved_at, search_id)).rowcount
    if not rows:
        raise TitleSearchRefused(
            f"title search {search_id} is not on record, is not visible to "
            "this caller, or already has a result. A register answer that has "
            "changed is a new search on a new date.")

    audit.write(conn, correlation_id or audit.new_correlation_id(),
                "TITLE_SEARCH_RESULT_RECORDED", "title_search", search_id,
                new_state={"volume_folio": volume_folio,
                           "proprietor_stored": registered_proprietor is not None,
                           "is_company": is_company},
                actor_user_id=recorded_by, actor_agent=ACTOR_AGENT)


def spend(conn):
    """What searching has cost, by month and purpose.

    Caller-scoped by the view, so this is what the reader is entitled to see
    rather than the whole bill.
    """
    return conn.execute(
        """SELECT month, purpose, searches, fee_cents, with_result
           FROM title_search_spend ORDER BY month DESC, purpose""").fetchall()
