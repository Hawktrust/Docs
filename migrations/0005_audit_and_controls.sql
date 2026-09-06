-- CROWN AI — MIGRATION 0005: controls an auditor would ask for and could not get
--
-- Four questions the system could not answer, and now can.

BEGIN;

-- ============================================================
-- 1. "Show me an audit row and tell me who did it."
--
-- actor_user_id and actor_agent were both nullable with nothing requiring
-- either, so a row could record an action attributed to nobody at all. An
-- audit entry without an actor is not evidence of anything.
-- ============================================================

ALTER TABLE audit_event
    ADD CONSTRAINT audit_event_has_an_actor
        CHECK (actor_user_id IS NOT NULL OR actor_agent IS NOT NULL);

-- ============================================================
-- 2. "Who changed the scoring weights, and when?"
--
-- The five numbers in match_weight_config decide which buyer ranks first.
-- Ticket item 5 makes them configuration precisely so they can be changed
-- without a deploy — which means changing them left no trace at all. Anyone
-- with write access could reorder every buyer in the system silently.
--
-- A trigger, so this records the change whatever wrote it: application code,
-- a migration, or someone at a psql prompt.
-- ============================================================

CREATE OR REPLACE FUNCTION audit_weight_config_change() RETURNS trigger AS $$
DECLARE
    actor    text := nullif(current_setting('crown.user_id', true), '');
    previous jsonb := NULL;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        previous := to_jsonb(OLD);
    END IF;

    INSERT INTO audit_event (actor_user_id, actor_agent, action, object_table,
                             object_id, previous_state, new_state, correlation_id)
    VALUES (
        CASE WHEN actor IS NOT NULL THEN actor::uuid END,
        'db.match_weight_config',
        'SCORING_WEIGHTS_' || TG_OP,
        'match_weight_config',
        NEW.id::text,
        previous,
        to_jsonb(NEW),
        gen_random_uuid()
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER weight_config_audited
    AFTER INSERT OR UPDATE ON match_weight_config
    FOR EACH ROW EXECUTE FUNCTION audit_weight_config_change();

-- ============================================================
-- 3. "Who approved this, and was it their own work?"
--
-- Nothing connected approval.approver_id to opportunity.owner_user_id, so the
-- analyst who raised an opportunity could approve the match on it themselves.
-- "Nothing leaves without human approval" means little if the approver is the
-- author.
--
-- If this proves impractical at Crown's headcount, this trigger is the one
-- thing to drop — but drop it deliberately, having read this.
-- ============================================================

CREATE OR REPLACE FUNCTION approval_is_not_self_approval() RETURNS trigger AS $$
DECLARE
    owner_id uuid;
BEGIN
    SELECT o.owner_user_id INTO owner_id
    FROM match_result m JOIN opportunity o ON o.id = m.opportunity_id
    WHERE m.id = NEW.match_result_id;

    IF owner_id = NEW.approver_id THEN
        RAISE EXCEPTION
            'user % owns this opportunity and cannot approve its own match; '
            'a second named human must decide', NEW.approver_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER approval_no_self_approval
    BEFORE INSERT ON approval
    FOR EACH ROW EXECUTE FUNCTION approval_is_not_self_approval();

-- ============================================================
-- 4. "Which sources are we ingesting without a signed register entry?"
--
-- data_source carries register_confirmed_by, described in the schema as NULL
-- until a named adviser signs. Nothing checked it, and the one ingestible
-- source has been ingestible from the start with that column empty.
--
-- Blocking ingestion outright would brick the pipeline over a signature nobody
-- has been asked for yet. Instead the gap is made visible and countable, so it
-- shows up in a report rather than in an audit finding.
-- ============================================================

CREATE VIEW data_rights_exception AS
    SELECT id, code, display_name, provider, lane, is_ingestible,
           licence_reference, attribution_text, notes,
           CASE
               WHEN register_confirmed_by IS NULL AND is_ingestible
                   THEN 'ingestible, but no named adviser has confirmed the register entry'
               WHEN licence_reference IS NULL AND is_ingestible
                   THEN 'ingestible, but no licence reference is on file'
               WHEN attribution_text IS NULL AND is_ingestible
                   THEN 'ingestible, but no attribution wording is on file'
           END AS exception_reason
    FROM data_source
    WHERE is_ingestible
      AND (register_confirmed_by IS NULL
           OR licence_reference IS NULL
           OR attribution_text IS NULL);

-- 0002 granted on the tables that existed then; this view came later.
GRANT SELECT ON data_rights_exception TO crown_app;

COMMENT ON VIEW data_rights_exception IS
    'Sources being ingested without a complete data rights register entry. '
    'This should be empty before go-live.';

COMMIT;
