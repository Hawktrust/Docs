-- CROWN AI — MIGRATION 0026: the retention rule, as a behaviour
--
-- The privacy policy now states retention periods. Until this migration
-- nothing expired, so the policy described an intention and a person reading
-- it would have been told something untrue about the system. APP 11.2 requires
-- personal information to be destroyed or de-identified once it is no longer
-- needed for any permitted purpose; a published period nobody implements is
-- worse than an admitted absence, because it is relied on.
--
-- DESTROY OR DE-IDENTIFY, AND WHY THE SECOND ONE MOSTLY.
--
-- Two obligations pull against each other here. APP 11.2 says stop holding it.
-- The audit trail says a decision taken must remain visible — and 0005 made
-- audit_event append-only precisely so that nobody could quietly erase what
-- was done. Deleting an outbound_artifact to satisfy the first would defeat
-- the second and leave Crown unable to show what it sent and why.
--
-- The Act permits either. So: the PERSON is removed and the DECISION stays.
-- An expired artefact keeps its approval, its score, its evidence chain and
-- the fact that a message was sent; it loses the name and the address it was
-- sent to. What remains is a record of Crown's conduct, which is not personal
-- information about the recipient.
--
-- WHAT IS NEVER EXPIRED, and each for a reason rather than by omission:
--
--   contact_suppression   a request not to be contacted must outlive the data
--                         it protects, or honouring it becomes impossible and
--                         the person is contacted again by a system that
--                         forgot. This is the one place where keeping data is
--                         the privacy-protective choice.
--   audit_event           it exists to show what was done. A retention rule
--                         over it is a deletion schedule for evidence.
--   app_user              attribution of decisions already taken. Closing an
--                         account is a separate act from forgetting who made
--                         a decision.

BEGIN;

-- ============================================================
-- THE PERIODS, AS DATA
--
-- In a table rather than hard-coded in a function, so that changing one is a
-- recorded act with a reason attached rather than an edit to a query nobody
-- reviews. The privacy policy quotes these; if they disagree, the policy is
-- making a promise the system does not keep.
-- ============================================================

CREATE TABLE retention_rule (
    category    text PRIMARY KEY,
    period      interval,          -- NULL means never expires
    applies_to  text NOT NULL,     -- the table and column, for a reader
    basis       text NOT NULL,     -- why this period and not another
    set_at      timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE retention_rule IS
    'How long each category of personal information is kept. Quoted by the '
    'privacy policy; if the two disagree the policy is promising something '
    'the system does not do.';

INSERT INTO retention_rule (category, period, applies_to, basis) VALUES
    ('ACTOR_NEVER_APPROACHED', interval '12 months', 'market_actor.name',
     'a name taken from a register and never used in an approach has had a '
     'year for its purpose to arise; if it has not, the reason for holding it '
     'has lapsed'),

    ('ARTEFACT_RECIPIENT', interval '7 years', 'outbound_artifact.contact_identifier',
     'the ordinary limitation period for a dispute about the approach. The '
     'artefact is not deleted — the decision stays and the person is removed'),

    ('SUPPRESSION', NULL, 'contact_suppression',
     'a request not to be contacted must outlive the data it protects, or it '
     'cannot be honoured. Keeping this is the privacy-protective choice'),

    ('AUDIT', NULL, 'audit_event',
     'it exists to show what was done; a retention rule over it is a deletion '
     'schedule for evidence'),

    ('ACCOUNT', NULL, 'app_user',
     'attribution of decisions already taken. Closing an account is a '
     'separate act from forgetting who decided');

-- RLS and FORCE. This is the fifth table added to this schema without them
-- on the first attempt — buyer_mandate_real in 0004, market_actor in 0013,
-- outbound_identity in 0016, and this one, each caught by
-- test_every_table_added_since_the_policies_has_one. I wrote a comment about
-- the pattern in 0024 and then repeated it here, which says the comment was
-- not the fix. The test is.
--
-- Reading the periods is ordinary: the sweep and the policy both need them.
-- Changing one is a decision about how long Crown keeps personal information,
-- which belongs with the roles that answer for that.
ALTER TABLE retention_rule ENABLE ROW LEVEL SECURITY;
ALTER TABLE retention_rule FORCE ROW LEVEL SECURITY;

CREATE POLICY retention_rule_read_by_all ON retention_rule FOR SELECT
    USING (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE'));

CREATE POLICY retention_rule_set_by_compliance ON retention_rule FOR INSERT
    WITH CHECK (crown_role() IN ('ADMIN','COMPLIANCE'));

CREATE POLICY retention_rule_changed_by_compliance ON retention_rule FOR UPDATE
    USING (crown_role() IN ('ADMIN','COMPLIANCE'));

GRANT SELECT ON retention_rule TO crown_app;

-- ============================================================
-- WHAT IS DUE
--
-- A view rather than a job that decides for itself, so that what is about to
-- be forgotten can be read before it is. A retention sweep nobody can preview
-- is one nobody runs.
-- ============================================================

CREATE OR REPLACE VIEW retention_due AS

SELECT 'ACTOR_NEVER_APPROACHED'::text AS category,
       ma.id::text                    AS object_id,
       'market_actor'::text           AS object_table,
       ma.created_at                  AS held_since
FROM market_actor ma
WHERE ma.created_at < now() - (SELECT period FROM retention_rule
                               WHERE category = 'ACTOR_NEVER_APPROACHED')
  -- Never used in an approach. Once a name has been written to, the artefact
  -- period governs it instead and this one does not apply.
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
  AND oa.contact_identifier <> '[removed: retention period expired]'
  AND oa.created_at < now() - (SELECT period FROM retention_rule
                               WHERE category = 'ARTEFACT_RECIPIENT');

COMMENT ON VIEW retention_due IS
    'Personal information past its retention period. Read it before running '
    'the sweep: this is what is about to be forgotten.';

-- ============================================================
-- THE SWEEP
--
-- SECURITY DEFINER because de-identifying an expired artefact is exactly the
-- kind of write the application role should not be able to make ad hoc, and
-- because outbound_artifact is otherwise written only through the gate. The
-- function is the one sanctioned route, it does one thing, and it writes an
-- audit row for every record it touches.
--
-- It does not delete the artefact. See the header: the person is removed and
-- the decision stays.
-- ============================================================

CREATE FUNCTION apply_retention(dry_run boolean DEFAULT true)
RETURNS TABLE (category text, object_table text, object_id text, acted boolean)
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    due record;
    correlation uuid := gen_random_uuid();
BEGIN
    FOR due IN SELECT * FROM retention_due LOOP
        IF NOT dry_run THEN
            IF due.category = 'ARTEFACT_RECIPIENT' THEN
                -- De-identify by replacing, not by nulling.
                --
                -- 0018 requires a message to a person to name its recipient,
                -- because a message with no named recipient cannot be given a
                -- way out. 0026 requires the name to be gone after seven
                -- years. Both are right, at different times — the first is
                -- about creating a message, the second about holding one.
                --
                -- NULL would satisfy the second by breaking the first, and
                -- weakening the 0018 constraint to allow it would trade a
                -- live control for a dead one. A tombstone satisfies both:
                -- the row still says a person was written to, and no longer
                -- says which. That is also more truthful than a blank, which
                -- reads as "nobody was named" rather than "the name was
                -- removed on purpose".
                --
                -- The opt-out link for this artefact stops verifying, because
                -- the token is an HMAC over the identifier. Seven years after
                -- sending, the thirty days s18 requires are long past.
                UPDATE outbound_artifact
                SET contact_identifier = '[removed: retention period expired]'
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
                            WHEN 'ARTEFACT_RECIPIENT' THEN 'de-identified'
                            ELSE 'deleted' END),
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

COMMENT ON FUNCTION apply_retention(boolean) IS
    'Destroy or de-identify what is past its period. Defaults to a dry run '
    'because a sweep that acts by default is one somebody runs by accident.';

COMMIT;
