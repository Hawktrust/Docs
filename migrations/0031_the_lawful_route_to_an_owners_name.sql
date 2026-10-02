-- CROWN AI — MIGRATION 0031: the lawful route to an owner's name
--
-- The question this answers was asked plainly: the commercial platforms show
-- the registered proprietor, so how does Crown get there without a legal
-- problem. The answer is not a technique. It is that those platforms hold
-- commercial licences to state land registry data and Crown does not, and the
-- route open to Crown is the same register, searched one property at a time,
-- under its own licence, for a purpose it can state.
--
-- Victoria's Titles Register is the authoritative record of who owns a parcel.
-- Vicmap Property — which Crown already has in its register — is the cadastre,
-- and carries no owner at all; the two are separate systems and no amount of
-- joining one to itself produces a name. A registered proprietor comes from a
-- title search, obtained from Land Use Victoria through LANDATA or an
-- Information Broker, per property, for a fee.
--
-- WHY THIS IS A MIGRATION AND NOT A DOCUMENT.
--
-- seeds/003 already registers LANDATA_TITLES, with the note that holding a
-- licence settles whether Crown may HOLD this data and not whether Crown may
-- USE it to approach anybody. That note has been correct and inert since
-- 2026-09-20. It describes a sequence — read the licence, settle the APP 7
-- basis, then search — and nothing made the sequence happen in that order.
--
-- So the sequence becomes the table's own precondition. A title search cannot
-- be recorded against a source whose licence nobody has read. A proprietor's
-- name cannot be stored against a source with no privacy basis on file. Both
-- refuse with the sentence that says what is missing. The legal work still has
-- to be done by a person; what changes is that skipping it now stops the
-- system rather than producing a row.
--
-- WHAT THIS MIGRATION DOES NOT CLAIM.
--
-- It does not mark LANDATA_TITLES as licensed, read, or ingestible. This
-- environment cannot reach landata.online — egress is blocked — and asserting
-- a licence position from memory is the precise failure the provenance model
-- exists to prevent. terms_read_by stays NULL. The gate below is therefore
-- closed on the day it ships, which is the honest state: the path is built and
-- the first search is blocked until somebody reads the licence and signs for
-- it.
--
-- WHY PER-SEARCH AND NOT BULK.
--
-- A bulk extract of the register is a separate commercial arrangement, and the
-- Proprietor Name Search — searching by person rather than by property — is
-- available only through Information Brokers and is the shape most likely to
-- breach both a licence condition and APP 7. Crown does not need it. The
-- system already produces a shortlist; the lawful search is against the
-- parcels on it. That is enforced below: a prospecting search must name the
-- parcel or the opportunity it came from, so the register is read in answer to
-- a question Crown already had rather than swept for questions to ask.

BEGIN;

-- ============================================================
-- THE TOMBSTONE, AS A FUNCTION
--
-- 0026 writes '[removed: retention period expired]' into an expired artefact's
-- recipient, because de-identifying by replacement is more truthful than a
-- blank: the row still says a person was written to and no longer says which.
-- This migration needs the same marker in three more places — a retention
-- branch, a freeze trigger that must let a removal through, and a view that
-- must not re-offer an already-removed row.
--
-- Four copies of a string literal is three chances for one of them to drift,
-- and the one that drifts silently stops matching. So it gets a name.
-- ============================================================

CREATE FUNCTION retention_tombstone() RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT '[removed: retention period expired]'::text
$$;

COMMENT ON FUNCTION retention_tombstone() IS
    'What replaces personal information once its retention period expires. '
    'A marker rather than a blank, so the row says the name was removed on '
    'purpose instead of reading as though nobody was ever named.';

-- ============================================================
-- THE SEARCH
--
-- One row per search actually requested from the register. Not a cache of
-- owners — a record of a paid act: what was searched, by whom, why, what it
-- cost, and what came back.
--
-- The fee is here because a prospecting system that cannot say what a lead
-- costs will keep buying leads it cannot justify. Per-search cost is the one
-- number that makes the difference between working a shortlist and working
-- a hunch visible on an invoice.
-- ============================================================

CREATE TABLE title_search (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Which register, through which provider. NOT NULL and a real reference,
    -- so there is no such thing as a search whose licence position is unknown
    -- because no source was named.
    source_id           uuid NOT NULL REFERENCES data_source(id),

    -- What was searched, as submitted: an SPI, a street address, or a
    -- volume/folio from an earlier search. Kept verbatim because a search is
    -- defended by what was actually typed, not by a tidied version of it.
    searched_for        text NOT NULL,
    parcel_id           uuid REFERENCES parcel(id),
    opportunity_id      uuid REFERENCES opportunity(id),

    -- Why. APP 3 and APP 6 are both about purpose, and a search with no stated
    -- purpose cannot be shown to be within one. The list is short on purpose:
    -- there is no 'RESEARCH' and no 'GENERAL', because those are not purposes,
    -- they are the absence of one.
    purpose             text NOT NULL CHECK (purpose IN (
                            'OPPORTUNITY_SHORTLIST',  -- a parcel the system surfaced
                            'MANDATE_MATCH',          -- a buyer's brief needs the owner
                            'VENDOR_INSTRUCTION',     -- Crown acts for this vendor
                            'OWNER_REQUEST')),        -- the owner asked Crown to look

    requested_by        uuid NOT NULL REFERENCES app_user(id),
    requested_at        timestamptz NOT NULL DEFAULT now(),

    -- The provider's own reference for the search, so a line on a monthly
    -- invoice can be matched back to a parcel and a purpose. Nullable because
    -- some providers issue it only with the result.
    provider_reference  text,
    fee_cents           integer NOT NULL CHECK (fee_cents >= 0),

    -- The result. volume_folio and is_company are facts about land and a
    -- corporation; the other two are personal information about a person, and
    -- the trigger below will not let them be stored until there is a basis for
    -- holding them.
    volume_folio        text,
    registered_proprietor text,
    proprietor_address  text,
    is_company          boolean,
    result_retrieved_at timestamptz,

    -- Same vocabulary as evidence_record. A title search through a portal a
    -- person logs into is OPERATOR_CAPTURE, and 0006 caps what that can ever
    -- be relied on as. DIRECT_FETCH is permitted here but the trigger below
    -- requires the source's automated_access to allow it first, because a
    -- direct fetch IS automated access however it is labelled.
    retrieval_method    text NOT NULL CHECK (retrieval_method IN
                            ('DIRECT_FETCH','OPERATOR_CAPTURE','MANUAL_ENTRY')),
    origin              data_origin NOT NULL DEFAULT 'REAL',
    created_at          timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT a_search_names_what_it_searched
        CHECK (length(btrim(searched_for)) > 0),

    -- A result has a time. Without this, a proprietor could sit in the table
    -- with nothing saying when the register said so — and a registered
    -- proprietor is only true as at a date.
    CONSTRAINT a_result_is_dated
        CHECK ((registered_proprietor IS NULL
                AND proprietor_address IS NULL
                AND volume_folio IS NULL)
               OR result_retrieved_at IS NOT NULL),

    -- The anti-bulk control, as a constraint rather than a convention. A
    -- prospecting search points at something Crown already identified. The two
    -- exempt purposes are the cases where the property came to Crown instead:
    -- a vendor who instructed it, or an owner who asked.
    CONSTRAINT a_prospecting_search_comes_off_the_shortlist
        CHECK (purpose IN ('VENDOR_INSTRUCTION','OWNER_REQUEST')
               OR parcel_id IS NOT NULL
               OR opportunity_id IS NOT NULL)
);

CREATE INDEX title_search_parcel_idx ON title_search (parcel_id)
    WHERE parcel_id IS NOT NULL;
CREATE INDEX title_search_requested_idx ON title_search (requested_at);

COMMENT ON TABLE title_search IS
    'One row per title search actually requested from a land registry: what '
    'was searched, why, what it cost and what came back. Not a cache of '
    'owners — a record of a paid act, which is what a licence and APP 6 are '
    'both asked about afterwards.';

COMMENT ON COLUMN title_search.fee_cents IS
    'What this search cost. Here so the system can say what a lead costs; a '
    'prospecting tool that cannot answer that keeps buying leads nobody can '
    'justify.';

COMMENT ON COLUMN title_search.registered_proprietor IS
    'Personal information. Storable only where the source carries a privacy '
    'basis for the intended use — see proprietor_details_need_a_basis().';

-- ============================================================
-- GATE ONE: THE LICENCE HAS BEEN READ
--
-- A CHECK cannot do this; it depends on a row in data_source. So it is a
-- trigger, on INSERT and on UPDATE, because a source_id changed afterwards is
-- the obvious way around a rule enforced only at insert — the same reasoning
-- as 0024's channel trigger.
--
-- Four conditions, each the answer to a different question:
--
--   lane = A_LICENSED        a register is not open data. A row claiming
--                            otherwise is miscategorised, and the ingest gate
--                            treats lanes differently.
--   licence_reference        0001 already requires this of Lane A. Restated
--                            because a search is the moment it matters.
--   terms_reference +        somebody read the licence and their name is on
--   terms_read_by            it. This is the condition that is false today,
--                            and it is meant to be.
--   automated_access         only checked for DIRECT_FETCH, and then it must
--                            actually permit automation. A human logging in to
--                            a portal is ordinary permitted use and is not
--                            gated on this.
-- ============================================================

CREATE FUNCTION a_title_search_needs_the_licence_read()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE src record;
BEGIN
    SELECT * INTO src FROM data_source WHERE id = NEW.source_id;

    IF src.lane <> 'A_LICENSED' THEN
        RAISE EXCEPTION
            'title search refused: % is registered in lane %, and a land '
            'registry is licensed data, not open data. Either the register '
            'entry is wrong or this is not a registry.',
            src.code, src.lane;
    END IF;

    IF src.licence_reference IS NULL THEN
        RAISE EXCEPTION
            'title search refused: % has no licence reference on file. A '
            'per-search fee is not a licence; the licence is the document '
            'that says what Crown may do with what it gets back.',
            src.code;
    END IF;

    IF src.terms_reference IS NULL OR src.terms_read_by IS NULL THEN
        RAISE EXCEPTION
            'title search refused: nobody has read %''s terms. Read the '
            'licence, then record who read it — '
            'UPDATE data_source SET terms_reference = ..., terms_read_by = '
            '''<name>'', terms_read_at = now() WHERE code = ''%''. Searching '
            'first and reading later is how a condition gets breached by a '
            'system that could have known.',
            src.code, src.code;
    END IF;

    IF NEW.retrieval_method = 'DIRECT_FETCH'
       AND src.automated_access NOT IN ('PERMITTED','PUBLISHER_FEED') THEN
        RAISE EXCEPTION
            'title search refused: retrieval_method DIRECT_FETCH is automated '
            'access, and %''s automated_access is %. Record the search as '
            'OPERATOR_CAPTURE if a person obtained it through the portal, '
            'which is ordinary permitted use.',
            src.code, src.automated_access;
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER a_search_waits_for_the_licence
    BEFORE INSERT OR UPDATE ON title_search
    FOR EACH ROW EXECUTE FUNCTION a_title_search_needs_the_licence_read();

-- ============================================================
-- GATE TWO: THE NAME NEEDS A BASIS
--
-- Separate from gate one because they answer different questions and are
-- satisfied by different work. Reading the licence settles whether Crown may
-- obtain and hold the search. APP 7, plus any register-specific restriction on
-- marketing use, settles whether Crown may hold the owner's name for the use
-- it has in mind — and Victoria has previously varied LANDATA licence
-- conditions precisely to stop owner names being used for marketing.
--
-- So a search can be recorded, paid for and attached to a parcel with the
-- licence read and the privacy question still open. What cannot happen is the
-- name landing in the database before that question is answered. The search
-- result is then a volume/folio and a date, which is a fact about land.
--
-- And it stays that way. The freeze trigger below will not let a name be added
-- to a search already recorded without one, so there is no path where the gate
-- is closed, the search happens anyway, and the name is filled in once the
-- paperwork catches up. Settling the basis later means searching again.
--
-- A removal is always permitted: the retention sweep writes the tombstone over
-- a name, and must not be blocked by a basis that has since been withdrawn
-- from the register entry. Taking the name out is the thing this gate wants.
-- ============================================================

CREATE FUNCTION proprietor_details_need_a_basis()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE src record;
BEGIN
    IF NEW.registered_proprietor IS NULL AND NEW.proprietor_address IS NULL THEN
        RETURN NEW;
    END IF;

    IF NEW.registered_proprietor IS NOT DISTINCT FROM retention_tombstone()
       AND NEW.proprietor_address IS NOT DISTINCT FROM retention_tombstone()
    THEN
        RETURN NEW;      -- a removal, not a holding
    END IF;

    SELECT * INTO src FROM data_source WHERE id = NEW.source_id;

    IF NOT src.carries_personal_information THEN
        RAISE EXCEPTION
            'title search refused: % is registered as carrying no personal '
            'information, and this row stores a proprietor. One of the two is '
            'wrong, and the register entry is the one a person signed.',
            src.code;
    END IF;

    IF src.privacy_basis IS NULL THEN
        RAISE EXCEPTION
            'title search refused: % has no privacy basis on file, so the '
            'owner''s name cannot be stored. The fee and the volume/folio can '
            'be — record the search without the proprietor columns. To store '
            'the name, write down which APP is relied on for the intended use, '
            'the consent position, and where the suppression list lives: '
            'UPDATE data_source SET privacy_basis = ''...'' WHERE code = ''%''.',
            src.code, src.code;
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER a_name_waits_for_a_basis
    BEFORE INSERT OR UPDATE ON title_search
    FOR EACH ROW EXECUTE FUNCTION proprietor_details_need_a_basis();

-- ============================================================
-- WHAT THE REGISTER SAID IS NOT EDITABLE
--
-- The result is filled in after the search is requested, so the application
-- needs UPDATE. That makes a freeze trigger the thing which makes granting it
-- safe — the same shape as 0017's outbound identity.
--
-- Frozen from insert: the source, what was searched, why, who asked, and the
-- fee. An invoice line does not change retrospectively.
--
-- Frozen once recorded: the result. A registered proprietor edited after the
-- fact is either a transcription being quietly corrected — which should be a
-- fresh search, because the register may have moved — or evidence being
-- adjusted to suit a decision already taken.
--
-- The one permitted change to a recorded result is removal: the retention
-- sweep replaces a name with the tombstone.
-- ============================================================

CREATE FUNCTION a_title_search_is_not_rewritten()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.source_id, NEW.searched_for, NEW.purpose, NEW.requested_by,
        NEW.requested_at, NEW.fee_cents)
       IS DISTINCT FROM
       (OLD.source_id, OLD.searched_for, OLD.purpose, OLD.requested_by,
        OLD.requested_at, OLD.fee_cents)
    THEN
        RAISE EXCEPTION
            'a title search records what was asked for and what it cost. '
            'Those do not change after the fact — record a new search.';
    END IF;

    IF OLD.result_retrieved_at IS NOT NULL THEN
        IF (NEW.volume_folio, NEW.is_company, NEW.result_retrieved_at)
           IS DISTINCT FROM
           (OLD.volume_folio, OLD.is_company, OLD.result_retrieved_at)
        THEN
            RAISE EXCEPTION
                'this search already has a result as at %. The register''s '
                'answer is evidence; if it has changed, that is a new search '
                'on a new date.', OLD.result_retrieved_at;
        END IF;

        -- Adding a name to a search that was recorded without one. This is
        -- the sequence gate two produces when the privacy basis was not on
        -- file at the time, and it is refused on purpose: the name either was
        -- never captured, in which case it cannot be supplied now, or it was
        -- kept outside the system while the gate was closed, which is what
        -- the gate existed to prevent. Settle the basis, then search again —
        -- the register may have moved anyway.
        IF (OLD.registered_proprietor IS NULL AND NEW.registered_proprietor IS NOT NULL)
           OR (OLD.proprietor_address IS NULL AND NEW.proprietor_address IS NOT NULL)
        THEN
            RAISE EXCEPTION
                'this search was recorded on % without a proprietor, so one '
                'cannot be added to it now. Record a new search: a name that '
                'was not stored at the time was either not obtained, or was '
                'held somewhere this database could not account for.',
                OLD.result_retrieved_at;
        END IF;

        IF NEW.registered_proprietor IS DISTINCT FROM OLD.registered_proprietor
           AND NEW.registered_proprietor IS DISTINCT FROM retention_tombstone()
        THEN
            RAISE EXCEPTION
                'the registered proprietor on a completed search may be '
                'removed but not altered. Removal is the retention sweep''s '
                'job; a different name is a new search.';
        END IF;

        IF NEW.proprietor_address IS DISTINCT FROM OLD.proprietor_address
           AND NEW.proprietor_address IS DISTINCT FROM retention_tombstone()
        THEN
            RAISE EXCEPTION
                'the proprietor address on a completed search may be removed '
                'but not altered.';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER a_title_search_result_is_frozen
    BEFORE UPDATE ON title_search
    FOR EACH ROW EXECUTE FUNCTION a_title_search_is_not_rewritten();

-- ============================================================
-- ROW-LEVEL SECURITY, FROM THE START
--
-- This table holds the most sensitive thing in the schema: a named owner, an
-- address, and the fact that Crown was interested in their land. Five tables
-- have now been added here without policies on the first attempt and each was
-- caught afterwards by a test rather than by anyone remembering, so this is
-- written before the inserts below rather than after them.
--
-- The read rule defers to opportunity rather than restating it, for the reason
-- 0030 gives: one copy of the rule, and the second copy is the one that goes
-- stale. A search with no opportunity is visible to whoever asked for it, and
-- to the roles that answer for the spend and the privacy position.
-- ============================================================

ALTER TABLE title_search ENABLE ROW LEVEL SECURITY;
ALTER TABLE title_search FORCE ROW LEVEL SECURITY;

CREATE POLICY title_search_read ON title_search FOR SELECT
    USING (crown_role() IN ('ADMIN','COMPLIANCE')
           OR requested_by::text = crown_user_id()
           OR (opportunity_id IS NOT NULL
               AND EXISTS (SELECT 1 FROM opportunity o
                           WHERE o.id = opportunity_id)));

-- Any working role may request one; it is a paid act attributed to them, and
-- the gates above decide whether it is permitted at all.
CREATE POLICY title_search_requested_by_a_working_role ON title_search
    FOR INSERT WITH CHECK (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE')
                           AND requested_by::text = crown_user_id());

-- Recording the result is an update to a row the caller can already see; the
-- freeze trigger decides what may change.
CREATE POLICY title_search_result_recorded ON title_search FOR UPDATE
    USING (crown_role() IN ('ADMIN','COMPLIANCE')
           OR requested_by::text = crown_user_id());

GRANT SELECT, INSERT, UPDATE ON title_search TO crown_app;

-- ============================================================
-- WHAT IS STILL MISSING BEFORE THE FIRST SEARCH
--
-- The gates refuse with a sentence, which is the right thing at the moment
-- somebody tries. This is the same information before they try: read it and
-- the remaining legal work is a list rather than a surprise.
--
-- Caller-scoped. It reads data_source, which has no policies for anybody, so
-- this costs nothing — but a view that bypasses row-level security has to be a
-- decision somebody made, and the default answer is no.
-- ============================================================

CREATE VIEW title_search_readiness AS
SELECT ds.code,
       ds.display_name,
       ds.provider,
       ds.terms_read_by IS NOT NULL                       AS licence_read,
       ds.privacy_basis IS NOT NULL                       AS basis_for_the_name,
       ds.register_confirmed_by IS NOT NULL               AS entry_signed,
       CASE
           WHEN ds.licence_reference IS NULL
               THEN 'no licence reference on file: no search can be recorded'
           WHEN ds.terms_read_by IS NULL
               THEN 'nobody has read the licence: no search can be recorded'
           WHEN ds.privacy_basis IS NULL
               THEN 'searches can be recorded; the owner''s name cannot be '
                    'stored until a privacy basis for the intended use is on file'
           WHEN ds.register_confirmed_by IS NULL
               THEN 'usable, but no named adviser has signed the register entry'
       END                                                AS blocker
FROM data_source ds
WHERE ds.lane = 'A_LICENSED'
  AND ds.carries_personal_information;

ALTER VIEW title_search_readiness SET (security_invoker = true);

COMMENT ON VIEW title_search_readiness IS
    'The legal work outstanding before a land registry can be searched, and '
    'before a proprietor''s name may be stored. Empty blocker means done.';

GRANT SELECT ON title_search_readiness TO crown_app;

-- ============================================================
-- WHAT IT COSTS
--
-- Caller-scoped, so a spend figure cannot be used to count searches the reader
-- is not entitled to see.
-- ============================================================

CREATE VIEW title_search_spend AS
SELECT date_trunc('month', ts.requested_at)::date AS month,
       ts.purpose,
       count(*)                                   AS searches,
       sum(ts.fee_cents)                          AS fee_cents,
       count(*) FILTER (WHERE ts.result_retrieved_at IS NOT NULL) AS with_result
FROM title_search ts
WHERE ts.origin = 'REAL'
GROUP BY 1, 2;

ALTER VIEW title_search_spend SET (security_invoker = true);

COMMENT ON VIEW title_search_spend IS
    'Title search spend by month and purpose. A search with no result is still '
    'charged, which is the number worth watching.';

GRANT SELECT ON title_search_spend TO crown_app;

-- ============================================================
-- RETENTION
--
-- A proprietor's name obtained for one approach is not needed indefinitely,
-- and the register moves: a name two years old is both unnecessary and
-- probably wrong. Twelve months, de-identified not deleted — the search, its
-- fee and its purpose stay, because they are the record of Crown's own conduct
-- and the thing a licence audit would ask about.
--
-- The view and the sweep are replaced rather than extended in place, because
-- 0026 built them to take exactly the categories it knew about. A retention
-- rule with no branch in the sweep is a period nobody applies, which is the
-- failure 0026 was written to stop.
-- ============================================================

INSERT INTO retention_rule (category, period, applies_to, basis) VALUES
    ('TITLE_SEARCH_PROPRIETOR', interval '12 months',
     'title_search.registered_proprietor, title_search.proprietor_address',
     'a name obtained from the register for one approach has served that '
     'purpose within a year, and the register has moved on. The search, the '
     'fee and the purpose are kept: they are the record of Crown''s conduct '
     'under the licence, not personal information about the owner');

-- WITH (security_invoker = true) restated, not inherited. CREATE OR REPLACE
-- VIEW replaces the view's options as well as its query: 0029 set
-- security_invoker on this view precisely because it exposes a recipient's
-- name, and replacing it without the option here silently turned that off.
-- The suite caught it — test_the_three_that_expose_a_name_are_caller_scoped —
-- which is the fourth time in this project that the broken thing was a
-- protection nobody could see was missing.
CREATE OR REPLACE VIEW retention_due WITH (security_invoker = true) AS

SELECT 'ACTOR_NEVER_APPROACHED'::text AS category,
       ma.id::text                    AS object_id,
       'market_actor'::text           AS object_table,
       ma.created_at                  AS held_since
FROM market_actor ma
WHERE ma.created_at < now() - (SELECT period FROM retention_rule
                               WHERE category = 'ACTOR_NEVER_APPROACHED')
  AND NOT EXISTS (
      SELECT 1 FROM outbound_artifact oa
      WHERE oa.contact_identifier IS NOT NULL
        AND normalise_identifier(oa.contact_identifier) = ma.normalised)

UNION ALL

SELECT 'ARTEFACT_RECIPIENT',
       oa.id::text,
       'outbound_artifact',
       oa.created_at
FROM outbound_artifact oa
WHERE oa.contact_identifier IS NOT NULL
  AND oa.contact_identifier <> retention_tombstone()
  AND oa.created_at < now() - (SELECT period FROM retention_rule
                               WHERE category = 'ARTEFACT_RECIPIENT')

UNION ALL

-- Dated from when the result was obtained, not from when the search was
-- requested: the period is about how long the name has been held.
SELECT 'TITLE_SEARCH_PROPRIETOR',
       ts.id::text,
       'title_search',
       ts.result_retrieved_at
FROM title_search ts
WHERE ts.result_retrieved_at IS NOT NULL
  AND (ts.registered_proprietor IS NOT NULL OR ts.proprietor_address IS NOT NULL)
  AND coalesce(ts.registered_proprietor, '') <> retention_tombstone()
  AND ts.result_retrieved_at < now() - (SELECT period FROM retention_rule
                                        WHERE category = 'TITLE_SEARCH_PROPRIETOR');

COMMENT ON VIEW retention_due IS
    'Personal information past its retention period. Read it before running '
    'the sweep: this is what is about to be forgotten.';

CREATE OR REPLACE FUNCTION apply_retention(dry_run boolean DEFAULT true)
RETURNS TABLE (category text, object_table text, object_id text, acted boolean)
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    due record;
    correlation uuid := gen_random_uuid();
BEGIN
    FOR due IN SELECT * FROM retention_due LOOP
        IF NOT dry_run THEN
            IF due.category = 'ARTEFACT_RECIPIENT' THEN
                -- See 0026: a tombstone satisfies both 0018's requirement that
                -- a message name its recipient and APP 11.2's that the name go.
                UPDATE outbound_artifact
                SET contact_identifier = retention_tombstone()
                WHERE id = due.object_id::uuid;

            ELSIF due.category = 'TITLE_SEARCH_PROPRIETOR' THEN
                -- Only the two personal columns. The volume/folio is a fact
                -- about land, and the fee is what Crown spent.
                UPDATE title_search
                SET registered_proprietor =
                        CASE WHEN registered_proprietor IS NULL THEN NULL
                             ELSE retention_tombstone() END,
                    proprietor_address =
                        CASE WHEN proprietor_address IS NULL THEN NULL
                             ELSE retention_tombstone() END
                WHERE id = due.object_id::uuid;

            ELSIF due.category = 'ACTOR_NEVER_APPROACHED' THEN
                DELETE FROM market_actor WHERE id = due.object_id::uuid;
            END IF;

            INSERT INTO audit_event (actor_agent, action, object_table,
                                     object_id, new_state, correlation_id)
            VALUES ('crown.retention', 'RETENTION_APPLIED', due.object_table,
                    due.object_id,
                    jsonb_build_object(
                        'category', due.category,
                        'held_since', due.held_since,
                        'action', CASE due.category
                            WHEN 'ACTOR_NEVER_APPROACHED' THEN 'deleted'
                            ELSE 'de-identified' END),
                    correlation);
        END IF;

        category := due.category;
        object_table := due.object_table;
        object_id := due.object_id;
        acted := NOT dry_run;
        RETURN NEXT;
    END LOOP;
END;
$$;

REVOKE ALL ON FUNCTION apply_retention(boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION apply_retention(boolean) TO crown_app;

-- ============================================================
-- THE REGISTER ENTRY, SHARPENED — WITHOUT CLAIMING ANYTHING NEW
--
-- terms_read_by stays NULL. What changes is the note: it now says what the
-- path is and what the two remaining decisions are, so whoever reads the
-- register next is told where the work is rather than left to infer it.
-- ============================================================

UPDATE data_source SET
    notes = notes || ' PATH BUILT 0031: title_search records a per-property '
                     'search against this source. Two gates are closed until a '
                     'person acts: no search can be recorded until the licence '
                     'is read and terms_read_by names who read it, and no '
                     'proprietor name can be stored until privacy_basis states '
                     'which APP is relied on for the intended use. Read '
                     'title_search_readiness for the current state. This build '
                     'environment cannot reach landata.online, so nothing here '
                     'asserts a licence position.'
WHERE code = 'LANDATA_TITLES';

INSERT INTO audit_event (actor_agent, action, object_table, object_id, new_state)
SELECT 'migrations.0031', 'TITLE_SEARCH_PATH_BUILT', 'data_source', id::text,
       jsonb_build_object(
           'licence_read', terms_read_by IS NOT NULL,
           'basis_for_the_name', privacy_basis IS NOT NULL,
           'note', 'the path is built and both gates are closed until a person '
                   'reads the licence and settles the privacy basis')
FROM data_source WHERE code = 'LANDATA_TITLES';

COMMIT;
