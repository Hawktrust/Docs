-- CROWN AI — MIGRATION 0002: complete the row-level security policies
--
-- 0001 enabled RLS on five tables and left two policies behind as "example
-- policy shape". That is not a working state: a table with RLS enabled and no
-- policy denies everything to a non-owner role, so buyer_mandate, match_result
-- and outbound_artifact were unreadable and unwritable by the application.
--
-- This migration writes the remaining policies, and closes the hole that made
-- the policies decorative: RLS does not apply to a table's owner unless the
-- table is set to FORCE. Without FORCE, an application connecting as the schema
-- owner bypasses every policy below and AC9 cannot hold.
--
-- The role and user id still come from session variables set server-side
-- immediately after authentication — never from a client header.

BEGIN;

-- ============================================================
-- The application role. It owns nothing, so RLS always applies to it.
-- ============================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'crown_app') THEN
        CREATE ROLE crown_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO crown_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO crown_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO crown_app;

-- AC10, defence in depth. The append-only trigger is the enforcement; taking
-- the privilege away as well means application code cannot even reach it.
REVOKE UPDATE ON audit_event   FROM crown_app;
REVOKE UPDATE ON attribution   FROM crown_app;
REVOKE DELETE ON ALL TABLES IN SCHEMA public FROM crown_app;
REVOKE TRUNCATE ON ALL TABLES IN SCHEMA public FROM crown_app;

-- ============================================================
-- Helper: the authenticated role, as established server-side.
-- Returns '' when unset, so an unauthenticated connection matches no policy.
-- ============================================================

CREATE OR REPLACE FUNCTION crown_role() RETURNS text AS $$
    SELECT coalesce(current_setting('crown.user_role', true), '');
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION crown_user_id() RETURNS text AS $$
    SELECT coalesce(current_setting('crown.user_id', true), '');
$$ LANGUAGE sql STABLE;

-- ============================================================
-- OPPORTUNITY — 0001 gave it a SELECT policy; it still needs write policies.
-- ============================================================

CREATE POLICY opportunity_insert ON opportunity FOR INSERT
    WITH CHECK (crown_role() IN ('ADMIN','ANALYST'));

CREATE POLICY opportunity_update ON opportunity FOR UPDATE
    USING (crown_role() IN ('ADMIN','ANALYST')
           OR owner_user_id::text = crown_user_id());

-- ============================================================
-- BUYER MANDATE — readable by everyone who works a deal, writable by ADMIN.
-- ============================================================

CREATE POLICY buyer_mandate_read ON buyer_mandate FOR SELECT
    USING (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE'));

CREATE POLICY buyer_mandate_insert ON buyer_mandate FOR INSERT
    WITH CHECK (crown_role() = 'ADMIN');

CREATE POLICY buyer_mandate_update ON buyer_mandate FOR UPDATE
    USING (crown_role() = 'ADMIN');

-- ============================================================
-- MATCH RESULT — the scoring output. Analysts compute it, everyone reads it.
-- ============================================================

CREATE POLICY match_result_read ON match_result FOR SELECT
    USING (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE'));

CREATE POLICY match_result_insert ON match_result FOR INSERT
    WITH CHECK (crown_role() IN ('ADMIN','ANALYST'));

-- Recomputing a ranking rewrites the stored row for the same weight config
-- version, so the same roles that may compute must also be able to update.
CREATE POLICY match_result_update ON match_result FOR UPDATE
    USING (crown_role() IN ('ADMIN','ANALYST'))
    WITH CHECK (crown_role() IN ('ADMIN','ANALYST'));

-- ============================================================
-- APPROVAL — 0001 restricted INSERT to ADMIN/COMPLIANCE. Reading is wider:
-- an analyst must be able to see whether their match was approved.
-- ============================================================

CREATE POLICY approval_read ON approval FOR SELECT
    USING (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE'));

-- ============================================================
-- OUTBOUND ARTIFACT — the approval_id NOT NULL is the real control; this
-- decides who may create one at all.
-- ============================================================

CREATE POLICY outbound_read ON outbound_artifact FOR SELECT
    USING (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE'));

CREATE POLICY outbound_insert ON outbound_artifact FOR INSERT
    WITH CHECK (crown_role() IN ('ADMIN','ANALYST','AGENT'));

-- ============================================================
-- ATTRIBUTION — a permanent record. Readable widely, written by the approver's
-- side of the house, never updated or deleted (trigger from 0001).
-- ============================================================

ALTER TABLE attribution ENABLE ROW LEVEL SECURITY;

CREATE POLICY attribution_read ON attribution FOR SELECT
    USING (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE'));

CREATE POLICY attribution_insert ON attribution FOR INSERT
    WITH CHECK (crown_role() IN ('ADMIN','COMPLIANCE'));

-- ============================================================
-- FORCE — without this every policy above is advisory for the owner.
-- ============================================================

ALTER TABLE opportunity       FORCE ROW LEVEL SECURITY;
ALTER TABLE buyer_mandate     FORCE ROW LEVEL SECURITY;
ALTER TABLE match_result      FORCE ROW LEVEL SECURITY;
ALTER TABLE approval          FORCE ROW LEVEL SECURITY;
ALTER TABLE outbound_artifact FORCE ROW LEVEL SECURITY;
ALTER TABLE attribution       FORCE ROW LEVEL SECURITY;

COMMIT;
