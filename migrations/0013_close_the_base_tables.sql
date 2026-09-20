-- CROWN AI — MIGRATION 0013: the control has to hold on the base table too
--
-- Found reviewing 0011. "Elected officials are never named" was enforced by a
-- view and by Python, and an analyst could read the name straight off
-- market_actor. Exactly the failure buyer_mandate_real had in 0004: a control
-- that lives in a view is a control that lives in one query path.
--
-- While here: several tables added since 0002 never had row-level security at
-- all, because each migration added a table and none went back to check.

BEGIN;

-- ============================================================
-- 1. An actor who may not be named is not visible to the people who write
--    outbound artifacts. Not filtered later — not readable.
--
--    COMPLIANCE can see them because somebody has to be able to audit what the
--    system is counting. ADMIN can, because somebody has to enter them.
--    An ANALYST or an AGENT, who between them write every brief, export and
--    outreach draft, cannot read the name at all.
-- ============================================================

ALTER TABLE market_actor ENABLE ROW LEVEL SECURITY;
ALTER TABLE market_actor FORCE ROW LEVEL SECURITY;

CREATE POLICY market_actor_read ON market_actor FOR SELECT
    USING (publishable_by_name
           OR crown_role() IN ('ADMIN', 'COMPLIANCE'));

CREATE POLICY market_actor_write ON market_actor FOR INSERT
    WITH CHECK (crown_role() IN ('ADMIN', 'ANALYST'));

COMMENT ON COLUMN market_actor.name IS
    'For an actor with publishable_by_name = false this should be a '
    'non-identifying descriptor, not a person''s name: the safest way to not '
    'publish an identity is not to hold one. Row-level security is the backstop '
    'for where one has been held anyway.';

-- ============================================================
-- 2. Tables that were never given a policy.
--
--    parcel had RLS from 0010 and its children did not, so a role denied the
--    parcel could still read its zoning and dwelling observations.
-- ============================================================

ALTER TABLE actor_signal        ENABLE ROW LEVEL SECURITY;
ALTER TABLE actor_signal        FORCE ROW LEVEL SECURITY;
ALTER TABLE parcel_planning     ENABLE ROW LEVEL SECURITY;
ALTER TABLE parcel_planning     FORCE ROW LEVEL SECURITY;
ALTER TABLE parcel_dwelling     ENABLE ROW LEVEL SECURITY;
ALTER TABLE parcel_dwelling     FORCE ROW LEVEL SECURITY;
ALTER TABLE conflict_disclosure ENABLE ROW LEVEL SECURITY;
ALTER TABLE conflict_disclosure FORCE ROW LEVEL SECURITY;
ALTER TABLE capture_artifact    ENABLE ROW LEVEL SECURITY;
ALTER TABLE capture_artifact    FORCE ROW LEVEL SECURITY;

CREATE POLICY actor_signal_read ON actor_signal FOR SELECT
    USING (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE'));
CREATE POLICY actor_signal_write ON actor_signal FOR INSERT
    WITH CHECK (crown_role() IN ('ADMIN','ANALYST'));

CREATE POLICY parcel_planning_read ON parcel_planning FOR SELECT
    USING (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE'));
CREATE POLICY parcel_planning_write ON parcel_planning FOR INSERT
    WITH CHECK (crown_role() IN ('ADMIN','ANALYST'));

CREATE POLICY parcel_dwelling_read ON parcel_dwelling FOR SELECT
    USING (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE'));
CREATE POLICY parcel_dwelling_write ON parcel_dwelling FOR INSERT
    WITH CHECK (crown_role() IN ('ADMIN','ANALYST'));

-- A conflict disclosure exists to be found. Everyone reads it; only the people
-- who can approve can record one.
CREATE POLICY conflict_disclosure_read ON conflict_disclosure FOR SELECT
    USING (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE'));
CREATE POLICY conflict_disclosure_write ON conflict_disclosure FOR INSERT
    WITH CHECK (crown_role() IN ('ADMIN','COMPLIANCE'));

CREATE POLICY capture_artifact_read ON capture_artifact FOR SELECT
    USING (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE'));
CREATE POLICY capture_artifact_write ON capture_artifact FOR INSERT
    WITH CHECK (crown_role() IN ('ADMIN','ANALYST'));

-- ============================================================
-- 3. Suppression stays readable to everyone on purpose — nobody is protected by
--    a secret do-not-contact list, and every path that might contact someone
--    has to be able to see it. Writing is another matter: lifting a suppression
--    is a compliance act.
-- ============================================================

ALTER TABLE contact_suppression ENABLE ROW LEVEL SECURITY;
ALTER TABLE contact_suppression FORCE ROW LEVEL SECURITY;

CREATE POLICY suppression_read_by_all ON contact_suppression FOR SELECT
    USING (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE'));
CREATE POLICY suppression_record ON contact_suppression FOR INSERT
    WITH CHECK (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE'));
CREATE POLICY suppression_release ON contact_suppression FOR UPDATE
    USING (crown_role() IN ('ADMIN','COMPLIANCE'));

COMMIT;
