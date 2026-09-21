-- CROWN AI — MIGRATION 0016: what "ready to go live" means, and the opt-out
-- that has to work before anything is sent
--
-- Two gaps stood between a working demonstration and a system that may contact
-- a real person.
--
-- THE OPT-OUT DOES NOT EXIST. contact_suppression has honoured requests since
-- 0008, and its source_of_request column has listed 'OPT_OUT_LINK' as a value
-- the whole time. There has never been an opt-out link. recorded_by is NOT NULL
-- and references app_user, so the only way a person could stop being contacted
-- was to reach somebody at Crown and ask them to type it in.
--
-- That is not a gap in convenience. APP 7.3 requires a SIMPLE means of opting
-- out of direct marketing. Section 18 of the Spam Act 2003 requires a
-- commercial electronic message to contain a FUNCTIONAL unsubscribe facility
-- that the recipient can use, and to keep working for at least 30 days. Both
-- words mean the recipient does it themselves. A phone call to the sender is
-- neither simple nor functional.
--
-- Section 17 of the same Act requires the message to accurately identify the
-- sender and how to contact them. Crown had no record of who it sends as.
--
-- NOBODY CAN SAY WHETHER IT IS READY. The register has a report for one kind
-- of gap, and the compliance page shows it. There was no single answer to "may
-- we turn this on", and a launch decision made from several half-answers is a
-- launch decision made from none.

BEGIN;

-- ============================================================
-- WHO CROWN SENDS AS
--
-- Section 17 of the Spam Act: the message must accurately identify the
-- individual or organisation that authorised it, and include how to contact
-- them. That information has to be accurate for 30 days after the message, so
-- it is versioned rather than edited — an artefact keeps the identity that was
-- current when it was created, and superseding it does not rewrite history.
-- ============================================================

CREATE TABLE outbound_identity (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    legal_entity_name text NOT NULL,
    abn               text,
    postal_address    text NOT NULL,     -- a real address, not a PO box slogan
    contact_email     text NOT NULL,
    contact_phone     text,
    is_active         boolean NOT NULL DEFAULT true,
    created_by        uuid NOT NULL REFERENCES app_user(id),
    created_at        timestamptz NOT NULL DEFAULT now(),
    superseded_at     timestamptz,

    CONSTRAINT an_active_identity_is_not_superseded
        CHECK (NOT is_active OR superseded_at IS NULL)
);

-- One active sender at a time. Two would mean a recipient could not tell which
-- organisation authorised the message, which is the thing s17 is about.
CREATE UNIQUE INDEX one_active_outbound_identity
    ON outbound_identity ((true)) WHERE is_active;

COMMENT ON TABLE outbound_identity IS
    'Who Crown sends as. Required on every message that leaves, kept accurate '
    'for at least 30 days after sending, and versioned rather than edited.';

-- ============================================================
-- WHAT A MESSAGE TO A PERSON MUST CARRY
--
-- The opt-out token is not stored. It is an HMAC over (artifact, scope,
-- identifier) computed from the application secret, so it can be recomputed
-- when a message is re-sent, cannot be forged without the secret, and does not
-- create a table of live capabilities to leak. What is stored is who the
-- message was addressed to, which is what an opt-out has to act on.
-- ============================================================

ALTER TABLE outbound_artifact
    ADD COLUMN contact_scope        text,
    ADD COLUMN contact_identifier   text,
    ADD COLUMN sender_identity_id   uuid REFERENCES outbound_identity(id);

ALTER TABLE outbound_artifact
    ADD CONSTRAINT contact_scope_is_a_suppression_scope
        CHECK (contact_scope IS NULL
               OR contact_scope IN ('PERSON','ADDRESS','PARCEL','ORGANISATION')),

    -- An OUTREACH_DRAFT is a message written to a human being who did not ask
    -- for it. It does not exist without a named recipient, a named sender and
    -- therefore a working way out. Other artefact types are internal or go to a
    -- buyer under an existing mandate; when Crown starts emailing those, add
    -- them here rather than exempting them in code.
    ADD CONSTRAINT outreach_identifies_sender_and_recipient
        CHECK (artifact_type <> 'OUTREACH_DRAFT'
               OR (contact_scope IS NOT NULL
                   AND contact_identifier IS NOT NULL
                   AND sender_identity_id IS NOT NULL));

-- ============================================================
-- THE OPT-OUT ITSELF
--
-- Three changes make a self-service opt-out possible at all.
--
-- 1. recorded_by becomes nullable. A person who clicks the link is not an
--    app_user and never will be. The CHECK keeps every other route attributed.
-- 2. A partial unique index, so clicking twice is not an error. One active
--    suppression per identifier is also the only thing that means anything.
-- 3. An INSERT policy that does not test the caller's role, because the caller
--    has none. It is narrow in the only direction that matters: an
--    unauthenticated request can add a suppression and can do nothing else —
--    not read one, not release one, not touch another table. The failure mode
--    of a forged opt-out is that somebody does not get contacted.
-- ============================================================

ALTER TABLE contact_suppression ALTER COLUMN recorded_by DROP NOT NULL;

ALTER TABLE contact_suppression
    ADD CONSTRAINT a_suppression_is_attributed_or_self_served
        CHECK (recorded_by IS NOT NULL OR source_of_request = 'OPT_OUT_LINK');

CREATE UNIQUE INDEX one_active_suppression_per_identifier
    ON contact_suppression (scope, normalised) WHERE released_at IS NULL;

CREATE POLICY suppression_self_service ON contact_suppression FOR INSERT
    WITH CHECK (source_of_request = 'OPT_OUT_LINK' AND recorded_by IS NULL);

COMMENT ON COLUMN contact_suppression.recorded_by IS
    'The staff member who recorded it, or NULL when the person opted out '
    'themselves through the link in a message. NULL is the good case.';

-- ============================================================
-- IS IT READY?
--
-- One view, one answer per question, each saying what would close it. BLOCKING
-- means do not go live. ADVISORY means go live knowing this.
--
-- Written as a UNION rather than a procedure so that it can be read: anybody
-- can see every condition Crown holds itself to, in one place, without running
-- anything.
-- ============================================================

CREATE VIEW launch_readiness AS

-- Nothing is ingested from a source whose rights are not settled.
SELECT 'DATA_RIGHTS_COMPLETE'::text AS check_code,
       'BLOCKING'::text             AS severity,
       (count(*) = 0)               AS passes,
       count(*)::text || ' source(s) in use with an incomplete register entry'
                                    AS detail,
       'complete the register entry or stop ingesting from it'::text AS closes_it
FROM data_rights_exception

UNION ALL

-- A crawler does not run against terms nobody has read.
SELECT 'EVERY_INGESTIBLE_SOURCE_HAS_A_POSITION', 'BLOCKING',
       count(*) = 0,
       count(*)::text || ' ingestible source(s) with automated_access UNKNOWN',
       'read the publisher''s terms and record a position, or leave the source off'
FROM data_source
WHERE is_ingestible AND automated_access = 'UNKNOWN'

UNION ALL

-- A source that identifies living individuals needs a basis written down.
SELECT 'PERSONAL_SOURCES_STATE_THEIR_BASIS', 'BLOCKING',
       count(*) = 0,
       count(*)::text || ' source(s) identify people with no privacy basis recorded',
       'record which APP is relied on, the consent position and where the '
       'suppression list lives'
FROM data_source
WHERE is_ingestible AND carries_personal_information AND privacy_basis IS NULL

UNION ALL

-- AC1. A system that has never ingested a real record is a demonstration.
SELECT 'REAL_EVIDENCE_EXISTS', 'BLOCKING',
       count(*) > 0,
       count(*)::text || ' evidence record(s) with origin REAL',
       'ingest one real amendment — by allowlist, or by operator capture, '
       'which needs no policy change'
FROM evidence_record WHERE origin = 'REAL'

UNION ALL

-- Demo records exist to exercise the loop. They must never leave the building.
SELECT 'NOTHING_SYNTHETIC_HAS_LEFT', 'BLOCKING',
       count(*) = 0,
       count(*)::text || ' outbound artefact(s) built on synthetic records',
       'these are demonstration artefacts; delete them or keep this environment '
       'out of production'
FROM outbound_artifact oa
JOIN approval a       ON a.id = oa.approval_id
JOIN match_result m   ON m.id = a.match_result_id
JOIN opportunity o    ON o.id = m.opportunity_id
JOIN buyer_mandate b  ON b.id = m.buyer_mandate_id
-- A match is only as real as both sides of it, and match_result carries no
-- origin of its own: it is the opportunity and the mandate that have one.
WHERE o.origin = 'DEMO_SYNTHETIC' OR b.origin = 'DEMO_SYNTHETIC'

UNION ALL

-- Section 17 of the Spam Act, before anything is written rather than after.
SELECT 'CROWN_KNOWS_WHO_IT_SENDS_AS', 'BLOCKING',
       count(*) = 1,
       count(*)::text || ' active outbound identity',
       'record the legal entity, postal address and contact email that every '
       'message will carry'
FROM outbound_identity WHERE is_active

UNION ALL

-- Belt and braces over the CHECK above: if this ever fails, the constraint was
-- dropped rather than satisfied.
SELECT 'EVERY_OUTREACH_OFFERS_A_WAY_OUT', 'BLOCKING',
       count(*) = 0,
       count(*)::text || ' outreach draft(s) with no recipient or no sender',
       'nothing can be sent to a person without a way for them to stop it'
FROM outbound_artifact
WHERE artifact_type = 'OUTREACH_DRAFT'
  AND (contact_scope IS NULL OR contact_identifier IS NULL
       OR sender_identity_id IS NULL)

UNION ALL

-- Placeholder authentication left anybody able to be anybody.
SELECT 'EVERY_ACCOUNT_HAS_A_PASSWORD', 'BLOCKING',
       count(*) = 0,
       count(*)::text || ' active account(s) with no password set',
       'set a password or deactivate the account'
FROM app_user WHERE is_active AND password_hash IS NULL

UNION ALL

-- A ranking nobody can reproduce is a ranking nobody should act on.
SELECT 'MATCH_WEIGHTS_ARE_VERSIONED', 'BLOCKING',
       count(*) > 0,
       count(*)::text || ' active match weight configuration(s)',
       'activate a weight configuration so every score records the version '
       'that produced it'
FROM match_weight_config WHERE is_active

UNION ALL

-- Not a reason to stop, but a reason to know.
SELECT 'NO_EVIDENCE_IS_PAST_ITS_SHELF_LIFE', 'ADVISORY',
       count(*) = 0,
       count(*)::text || ' evidence record(s) past their shelf life',
       're-retrieve the source and update last_verified_at'
FROM stale_evidence

UNION ALL

SELECT 'SOMEBODY_IS_WATCHING_SOMETHING', 'ADVISORY',
       count(*) > 0,
       count(*)::text || ' active watchlist(s)',
       'a system that alerts nobody about nothing will not be noticed when it '
       'stops working'
FROM watchlist WHERE is_active;

-- The application reads the gate and records who it sends as; it never edits
-- an identity in place, because an artefact keeps the one it was sent under.
GRANT SELECT ON launch_readiness TO crown_app;
GRANT SELECT, INSERT ON outbound_identity TO crown_app;

COMMENT ON VIEW launch_readiness IS
    'Every condition Crown holds itself to before contacting a real person. '
    'BLOCKING rows must all pass. Read it with crown/readiness.py or '
    'scripts/readiness.py, which exits non-zero while anything blocking fails.';

COMMIT;
