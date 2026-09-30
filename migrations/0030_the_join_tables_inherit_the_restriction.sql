-- CROWN AI — MIGRATION 0030: a join table is a way around a row policy
--
-- Ten tables carried no row-level security. Nine of them are deliberate and are
-- now recorded as such. Two were a leak, and this is the proof that produced
-- this migration:
--
--   as crown_app, role AGENT, owning one of two opportunities
--     opportunity visible          : 1     <- correct
--     opportunity_evidence visible : 2
--     links to opportunities it cannot see : 1     <- the leak
--
-- opportunity restricts by ROW: 0002 lets an AGENT read only the opportunities
-- they own. opportunity_evidence and opportunity_parcel reference it and had no
-- policies at all, so an agent could enumerate them and learn which evidence
-- and which parcels belong to every other agent's work. The restriction on the
-- parent was real and the link tables walked around it.
--
-- THE POLICY IS WRITTEN AS A SUBQUERY ON PURPOSE. "You may see this link if you
-- may see its opportunity" — and because opportunity's own policies apply inside
-- that subquery, the link table inherits whatever opportunity decides, now and
-- after anybody changes it. Restating opportunity's rule here would create two
-- copies of one decision, and the second copy is the one that goes stale.
--
-- FORCE, like the other twenty, so a table's owner is not exempt from it.

BEGIN;

ALTER TABLE opportunity_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE opportunity_evidence FORCE ROW LEVEL SECURITY;

CREATE POLICY opportunity_evidence_follows_its_opportunity
    ON opportunity_evidence FOR SELECT
    USING (EXISTS (SELECT 1 FROM opportunity o WHERE o.id = opportunity_id));

CREATE POLICY opportunity_evidence_linked_by_a_working_role
    ON opportunity_evidence FOR INSERT
    WITH CHECK (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE'));

ALTER TABLE opportunity_parcel ENABLE ROW LEVEL SECURITY;
ALTER TABLE opportunity_parcel FORCE ROW LEVEL SECURITY;

CREATE POLICY opportunity_parcel_follows_its_opportunity
    ON opportunity_parcel FOR SELECT
    USING (EXISTS (SELECT 1 FROM opportunity o WHERE o.id = opportunity_id));

CREATE POLICY opportunity_parcel_linked_by_a_working_role
    ON opportunity_parcel FOR INSERT
    WITH CHECK (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE'));

-- ============================================================
-- THE NINE THAT STAY OPEN, AND WHY
--
-- Recorded as comments because the alternative is that the next auditor finds
-- the same list and has to work out from scratch whether each one is a decision
-- or an oversight. tests/test_views_and_policies.py holds the same list and
-- fails if a table joins or leaves it without one.
-- ============================================================

COMMENT ON TABLE app_user IS
    'No row-level security, deliberately. Authentication has to read a row by '
    'email BEFORE any role is known, so a policy gated on crown_role() would '
    'refuse every login. A policy permitting unauthenticated reads would be the '
    'current behaviour with extra steps. What protects this table is that '
    'UPDATE on password_hash goes through auth.set_password and the column is '
    'never returned to a client.';

COMMENT ON TABLE audit_event IS
    'No row-level security, deliberately. It exists so that any decision can be '
    'traced by anybody entitled to audit, and a policy narrowing who may read '
    'it would defeat that. UPDATE and DELETE are revoked from crown_app and the '
    '0005 trigger refuses both regardless, so the exposure is read-only.';

COMMENT ON TABLE evidence_record IS
    'No row-level security, deliberately. Evidence is the shared graph — the '
    'point is that every role reasons over the same facts. Separation that does '
    'matter is by ORIGIN, not by role, and the parcel_real and buyer_mandate_real '
    'views carry it.';

COMMENT ON TABLE data_source IS
    'No row-level security, deliberately. The data rights register is read by '
    'every role and by the crawler gate on every fetch; restricting it would '
    'mean a role that cannot check whether a source is lawful to use.';

COMMENT ON TABLE evidence_review_queue IS
    'No row-level security, deliberately. A work queue every analyst works; it '
    'is not owned by whoever happened to queue the lead.';

COMMENT ON TABLE match_weight_config IS
    'No row-level security, deliberately. Every score records the weight '
    'version that produced it, so the weights have to be readable by anybody '
    'who can read a score.';

COMMENT ON TABLE signal_weight_config IS
    'No row-level security, deliberately. Same reason as match_weight_config.';

COMMENT ON TABLE opportunity_parcel IS
    'Links an opportunity to a parcel. Row-level security since 0030: it '
    'follows its opportunity, because an agent who cannot see an opportunity '
    'could otherwise read which parcels it concerns.';

COMMENT ON TABLE opportunity_evidence IS
    'Links an opportunity to the evidence behind it. Row-level security since '
    '0030 for the same reason as opportunity_parcel, and the leak was measured '
    'rather than assumed.';

COMMENT ON TABLE raw_ingest IS
    'No row-level security, deliberately — but the weakest of the nine. It holds '
    'bodies as fetched, before anything is concluded from them, and a body from '
    'a source carrying personal information holds that too. Nothing reads it at '
    'run time; it exists so a parse can be re-run against what was actually '
    'served. If anything ever surfaces it to a user, it needs a policy first.';

COMMIT;
