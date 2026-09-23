-- CROWN AI — MIGRATION 0019: who Crown actually is
--
-- Three records said who is accountable, and until now none of them named a
-- legal person. The seeded accounts are @crown.local, a demonstration domain.
-- The data rights register was signed "Crown Capital & Development", a trading
-- name rather than an entity. outbound_identity was empty, so nothing could be
-- addressed to anybody at all.
--
-- This fills all three with the same legal person, because a regulator or a
-- recipient pulling on any one of those threads should arrive at the same
-- place: Crown Real Estate Agents Pty Ltd, ABN 86 690 344 597.
--
-- ON THE ABN. 86690344597 passes the ATO's weighted-modulus check — eleven
-- digits, weighted sum 623, divisible by 89. That proves the number is
-- well formed. It does not prove it belongs to this entity, which only ABN
-- Lookup can, so confirm it there before the first message leaves. A wrong but
-- well formed ABN in a message is a false sender identification under s17,
-- which is worse than none.

BEGIN;

-- ============================================================
-- SOMEBODY WHO CAN ANSWER A PERSON
--
-- APP 1.4 wants a contactable person for access, correction and complaints,
-- and the readiness gate refuses a launch without a usable ADMIN or COMPLIANCE
-- account. Every seeded account is @crown.local and belongs to a demonstration.
-- This is the first real one.
--
-- password_hash stays NULL, which is what 0006 intends: an account nobody has
-- set a password on is an account nobody can be. Close it with
--
--     python scripts/set_password.py inder@crownrealestateagents.com.au
--
-- and EVERY_ACCOUNT_HAS_A_PASSWORD stops failing for this row.
-- ============================================================

INSERT INTO app_user (email, display_name, role)
VALUES ('inder@crownrealestateagents.com.au', 'Inder', 'ADMIN')
ON CONFLICT (email) DO NOTHING;

-- ============================================================
-- WHO EVERY MESSAGE SAYS IT IS FROM
--
-- Section 17 of the Spam Act: a commercial electronic message must accurately
-- identify the individual or organisation who authorised it and include how to
-- contact them, and that information has to stay accurate for 30 days after
-- sending. 0017 froze the content of this row for exactly that reason — it is
-- superseded, never edited.
--
-- The address is a real one. A PO box or a slogan fails the "how to contact
-- them" limb, and the point of the requirement is that a person who wants to
-- complain can find you.
-- ============================================================

INSERT INTO outbound_identity
    (legal_entity_name, abn, postal_address, contact_email, created_by)
SELECT 'Crown Real Estate Agents Pty Ltd',
       '86 690 344 597',
       '208/2 Infinity Drive, Truganina VIC 3029',
       'inder@crownrealestateagents.com.au',
       id
FROM app_user WHERE email = 'inder@crownrealestateagents.com.au'
ON CONFLICT DO NOTHING;

-- ============================================================
-- THE REGISTER SIGNED IN THE SAME NAME
--
-- 0014 signed VIC_PLANNING_AMENDMENTS as "Hawk (Crown Capital & Development)",
-- and 0015 reassigned that to "Crown Capital & Development" when Crown asked
-- for the company's name to carry the attestation.
--
-- That is the same business under a different name, confirmed 2026-09-22, and
-- "Crown Capital & Development" is not the legal person. The register says who
-- takes responsibility for the lawfulness of a source; outbound_identity says
-- who authorised the message built from it. Those being two different names was
-- a discrepancy waiting to be found by somebody less friendly than a reader of
-- this file.
--
-- Corrected rather than re-signed: the reading it rests on has not changed and
-- is still recorded in terms_read_by. Only the name of the party is now the
-- registered one.
-- ============================================================

UPDATE data_source SET
    register_confirmed_by = 'Crown Real Estate Agents Pty Ltd (ABN 86 690 344 597)',
    register_confirmed_at = now()
WHERE code = 'VIC_PLANNING_AMENDMENTS';

INSERT INTO audit_event (actor_agent, action, object_table, object_id,
                         new_state, correlation_id)
SELECT 'migrations.0019', 'SOURCE_REGISTER_CONFIRMED', 'data_source', id::text,
       jsonb_build_object(
           'code', code,
           'confirmed_by', register_confirmed_by,
           'previously', 'Crown Capital & Development',
           'terms_read_by', terms_read_by,
           'basis', 'the same business under its registered name, confirmed by '
                    'Crown 2026-09-22; the reading the signature rests on is '
                    'unchanged'),
       gen_random_uuid()
FROM data_source WHERE code = 'VIC_PLANNING_AMENDMENTS';

COMMIT;
