"""AC8: nothing may be exported, emailed or drafted for outreach without a
stored approval id.

The database enforces this with a NOT NULL foreign key. This module is the
server-side gate in front of it, and it checks more than the column can: that
the approval exists, and that it says APPROVED rather than REJECTED.
"""
from psycopg.types.json import Jsonb

from . import audit, suppression

ACTOR_AGENT = "crown.outbound"

ARTIFACT_TYPES = ("EXPORT", "OUTREACH_DRAFT", "BUYER_BRIEF",
                  "RECOMMENDATION", "IC_BRIEF", "ALERT")

# Artefact types that are a message written to a person who did not ask for it.
# These carry the Spam Act's requirements: an accurate sender, and a working way
# to stop. Everything else is internal or goes to a buyer under a mandate they
# signed — when Crown starts emailing those, add them here rather than
# exempting them somewhere else.
# A BUYER_BRIEF goes to a buyer under a mandate they signed, which supplies the
# consent an OUTREACH_DRAFT lacks — but consent is only one of the Spam Act's
# three requirements. A brief sent by email is still a commercial electronic
# message, and sections 17 and 18 want it to identify its sender and carry a way
# to stop. Handing one over in a meeting needs neither; the schema cannot tell
# the difference, so it requires them of both.
ADDRESSED_TO_A_PERSON = ("OUTREACH_DRAFT", "BUYER_BRIEF")

# How a message goes out. There is no PHONE: the Do Not Call Register Act wants
# numbers washed before telemarketing and Crown has not built that, so a value
# the schema appears to bless and the law does not would be worse than no value.
CHANNELS = ("POST", "EMAIL")

# Who is being written to. The distinction is not decoration — it decides which
# channels are lawful, because the Spam Act asks whether the address was
# published by the person in a work capacity, and a landholder on a planning
# permit was not.
RECIPIENT_CLASSES = ("LANDHOLDER_FROM_REGISTER", "PROFESSIONAL_CONTACT",
                     "MANDATED_BUYER")

# The one combination the Spam Act refuses outright. See
# docs/compliance/CONSENT-POSITION.md.
NEEDS_EXPRESS_CONSENT = ("EMAIL", "LANDHOLDER_FROM_REGISTER")


class ApprovalRequired(Exception):
    """No usable approval id, so nothing leaves."""


class ChannelNotPermitted(Exception):
    """This recipient may be written to, but not by this route.

    Distinct from NoWayOut because the fix is different: NoWayOut means name a
    recipient, this means change the channel or record the consent that opens
    it.
    """


class NoWayOut(Exception):
    """A message to a person with no named sender or no means of opting out.

    Refused before it is written rather than caught in review, because a draft
    that exists is a draft somebody can send.
    """


class NoSenderIdentity(Exception):
    """Crown has no active outbound identity, so nothing can say who sent it."""


class ConflictNotDisclosed(Exception):
    """The same parcel is being worked for two principals with nothing on record."""


def build_content(conn, approval_id, *, note: str = "") -> dict:
    """Assemble what actually goes out.

    An outreach draft that says only "note: hi" is gated but useless. What
    leaves carries the chain that justifies it: the geography and the rule that
    staged it, the evidence with its provenance, the buyer, the score with every
    factor, and the approval. Anyone receiving it can check the reasoning, and
    anyone auditing it can retrace the decision from the artifact alone.

    Returns an empty envelope when there is no approval to build from; create()
    refuses it a moment later.
    """
    if approval_id is None or str(approval_id).strip() == "":
        return {"note": note}

    header = conn.execute(
        """SELECT o.lga, o.geography_label, o.stage::text, o.stage_rule,
                  b.buyer_label, b.origin::text, m.total_score,
                  m.geographic_fit_score, m.asset_fit_score, m.price_fit_score,
                  m.size_fit_score, m.freshness_score, m.weight_config_version,
                  a.decision::text, a.reason, u.display_name, a.decided_at
           FROM approval a
           JOIN match_result m  ON m.id = a.match_result_id
           JOIN opportunity o   ON o.id = m.opportunity_id
           JOIN buyer_mandate b ON b.id = m.buyer_mandate_id
           JOIN app_user u      ON u.id = a.approver_id
           WHERE a.id = %s""",
        (approval_id,),
    ).fetchone()
    if header is None:
        return {"note": note}

    evidence = conn.execute(
        """SELECT e.source_reference, e.title, e.evidence_class::text,
                  e.reliability::text, e.retrieval_method, e.source_url,
                  e.retrieved_at, e.observed_at, e.origin::text
           FROM approval a
           JOIN match_result m          ON m.id = a.match_result_id
           JOIN opportunity_evidence oe ON oe.opportunity_id = m.opportunity_id
           JOIN evidence_record e       ON e.id = oe.evidence_id
           WHERE a.id = %s
           ORDER BY e.observed_at DESC""",
        (approval_id,),
    ).fetchall()

    return {
        "note": note,
        "approval": {
            "id": str(approval_id),
            "decision": header[13],
            "reason": header[14],
            "approved_by": header[15],
            "decided_at": header[16].isoformat(),
        },
        "opportunity": {
            "lga": header[0],
            "geography": header[1],
            "stage": header[2],
            "stage_rule": header[3],
        },
        "buyer": {"label": header[4], "origin": header[5]},
        "score": {
            "total": float(header[6]),
            "weight_config_version": header[12],
            "contributions": {
                "geographic_fit": float(header[7]),
                "asset_fit": float(header[8]),
                "price_fit": float(header[9]),
                "size_fit": float(header[10]),
                "mandate_freshness": float(header[11]),
            },
        },
        "evidence": [
            {
                "reference": row[0], "title": row[1], "class": row[2],
                "reliability": row[3], "retrieval_method": row[4],
                "source_url": row[5],
                "retrieved_at": row[6].isoformat(),
                "observed_at": row[7].isoformat(),
                "origin": row[8],
            }
            for row in evidence
        ],
    }


def _conflicting_principals(conn, approval_id):
    """Other opportunities on the same geography being worked for someone else.

    Crown invests for its own book, advises clients and matches developers. When
    the same parcel is being worked for two of them, that is a conflict, and it
    is disclosed before anything goes out or it does not go out.
    """
    return conn.execute(
        """
        SELECT other.id, other.principal::text, other.principal_label
        FROM approval a
        JOIN match_result m ON m.id = a.match_result_id
        JOIN opportunity mine ON mine.id = m.opportunity_id
        JOIN opportunity other
          ON other.lga = mine.lga
         AND other.geography_label = mine.geography_label
         AND other.id <> mine.id
        WHERE a.id = %s
          AND other.principal IS NOT NULL
          AND mine.principal IS NOT NULL
          AND other.principal <> mine.principal
          AND NOT EXISTS (
                SELECT 1 FROM conflict_disclosure d
                WHERE (d.opportunity_id = mine.id AND d.competing_opportunity_id = other.id)
                   OR (d.opportunity_id = other.id AND d.competing_opportunity_id = mine.id))
        """,
        (approval_id,),
    ).fetchall()


def active_identity(conn):
    """Who Crown sends as today. One row, or nothing has been decided."""
    return conn.execute(
        """SELECT id, legal_entity_name, abn, postal_address, contact_email,
                  contact_phone
           FROM outbound_identity WHERE is_active"""
    ).fetchone()


def has_express_consent(conn, scope: str, identifier: str) -> bool:
    """Did this person actually say yes to being emailed?

    Express only. A mandate is consent from a buyer and says nothing about a
    landholder, and impracticability is an APP 7 argument the Spam Act does not
    accept.
    """
    row = conn.execute(
        """SELECT EXISTS (
               SELECT 1 FROM contact_consent
               WHERE withdrawn_at IS NULL
                 AND basis IN ('EXPRESS_REPLY', 'EXPRESS_WRITTEN')
                 AND scope = %s
                 AND normalised = %s)""",
        (scope, suppression.normalise(identifier)),
    ).fetchone()
    return bool(row[0]) if row else False


def create(conn, approval_id, artifact_type: str, content: dict, created_by,
           *, contact=None, channel=None, recipient_class=None,
           correlation_id=None) -> str:
    if approval_id is None or str(approval_id).strip() == "":
        raise ApprovalRequired(
            f"a {artifact_type} needs a stored approval id; refusing to create one"
        )
    if artifact_type not in ARTIFACT_TYPES:
        raise ValueError(f"unknown artifact type {artifact_type}")

    row = conn.execute(
        "SELECT decision::text FROM approval WHERE id = %s", (approval_id,)
    ).fetchone()
    if row is None:
        raise ApprovalRequired(f"approval {approval_id} does not exist")
    if row[0] != "APPROVED":
        raise ApprovalRequired(
            f"approval {approval_id} is {row[0]}; a rejected match produces nothing"
        )

    # Nobody who asked not to be contacted is contacted, whatever the approval
    # says. An approval permits an action; it does not override a person's
    # request. `contact` is whatever is known about the target — person,
    # address, parcel, organisation — and all of it is checked.
    if contact:
        suppression.assert_not_suppressed(conn, contact)

    conflicts = _conflicting_principals(conn, approval_id)
    if conflicts:
        raise ConflictNotDisclosed(
            "the same geography is being worked for a different principal "
            + "; ".join(f"{row[1]} ({row[2]})" for row in conflicts)
            + ". Record a conflict_disclosure first.")

    # A message to a person needs a person to be addressed to, a sender who can
    # be identified, and therefore a way out. The database CHECK refuses the row
    # either way; these say which of the three is missing, because "constraint
    # violated" is not an instruction.
    scope = identifier = None
    sender_identity_id = None
    if artifact_type in ADDRESSED_TO_A_PERSON:
        if not contact:
            raise NoWayOut(
                f"a {artifact_type} is a message to a person: name who it is "
                "addressed to, so they can be given a way to stop it")
        scope, identifier = _single_contact(contact)
        sender = active_identity(conn)
        if sender is None:
            raise NoSenderIdentity(
                "no active outbound_identity: the Spam Act requires a message "
                "to identify who authorised it and how to reach them. Record "
                "one before writing anything addressed to a person.")
        sender_identity_id = sender[0]

        # How it goes out is part of whether it may go out at all. The trigger
        # in 0024 refuses the unlawful row either way; these say what to do
        # about it, because "check_violation" is not an instruction.
        if channel not in CHANNELS:
            raise ChannelNotPermitted(
                f"a {artifact_type} needs a channel, one of "
                f"{', '.join(CHANNELS)}. Whether Crown may send it at all "
                "depends on which, so it is not a detail to fill in later.")
        if recipient_class not in RECIPIENT_CLASSES:
            raise ChannelNotPermitted(
                f"a {artifact_type} needs a recipient class, one of "
                f"{', '.join(RECIPIENT_CLASSES)}. It decides which channels "
                "are lawful for this person.")

        if (channel, recipient_class) == NEEDS_EXPRESS_CONSENT \
                and not has_express_consent(conn, scope, identifier):
            raise ChannelNotPermitted(
                f"{identifier} was identified from a public register, and "
                "emailing them is a commercial electronic message. The Spam "
                "Act needs consent that a register does not supply — a "
                "council published the address under a statute, not the "
                "person in a work capacity. Send this by post, or record the "
                "reply that gave consent. See "
                "docs/compliance/CONSENT-POSITION.md.")

    correlation_id = correlation_id or audit.new_correlation_id()
    artifact_id = conn.execute(
        """INSERT INTO outbound_artifact (approval_id, artifact_type, content,
                   created_by, contact_scope, contact_identifier,
                   sender_identity_id, channel, recipient_class)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (approval_id, artifact_type, Jsonb(content), created_by,
         scope, identifier, sender_identity_id, channel, recipient_class),
    ).fetchone()[0]

    said = {"artifact_type": artifact_type}
    if channel is not None:
        said["channel"] = channel
    if recipient_class is not None:
        said["recipient_class"] = recipient_class
    audit.write(conn, correlation_id, "OUTBOUND_CREATED", "outbound_artifact",
                artifact_id, new_state=said,
                approval_id=approval_id, actor_user_id=created_by,
                actor_agent=ACTOR_AGENT)
    return artifact_id


def _single_contact(contact):
    """The one recipient an addressed message is for.

    `contact` is the same mapping the suppression check takes — everything known
    about the target. A message, unlike a suppression check, goes to exactly one
    of them, so the most specific known identity is chosen rather than guessed
    at send time. A person is more specific than the organisation they work for,
    which is more specific than the address, which is more specific than a
    parcel identifier nobody reads.
    """
    for scope in ("PERSON", "ORGANISATION", "ADDRESS", "PARCEL"):
        value = contact.get(scope) if hasattr(contact, "get") else None
        if value and str(value).strip():
            return scope, str(value).strip()
    raise NoWayOut(
        "the contact names nobody: a message needs a person, an organisation, "
        "an address or a parcel to be addressed to")


def opt_out_link(secret: str, base_url: str, artifact_id, scope: str,
                 identifier: str) -> str:
    """The URL that goes in the message.

    Recomputed rather than stored, so re-sending a message produces the same
    link and no table of live capabilities accumulates anywhere to be leaked.
    """
    from . import optout
    token = optout.issue(secret, artifact_id=artifact_id, scope=scope,
                         identifier=identifier)
    return f"{base_url.rstrip('/')}/opt-out/{token}"
