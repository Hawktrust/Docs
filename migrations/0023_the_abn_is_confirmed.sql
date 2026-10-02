-- CROWN AI — MIGRATION 0023: somebody checked the ABN
--
-- 0020 added a checksum constraint and was careful to say what it does not
-- prove: that the number belongs to this entity. Only ABN Lookup can settle
-- that, and a well formed ABN belonging to somebody else is a false sender
-- identification under s17 — worse than omitting it, because it misidentifies
-- rather than merely omits.
--
-- Crown checked it on 2026-09-22 and confirmed 86 690 344 597 is Crown Real
-- Estate Agents Pty Ltd's. That closes the last thing standing between the
-- recorded sender identity and one that can be relied on.
--
-- Recorded as an audit event rather than a column, because it is a fact about
-- who checked what and when, not a property of the ABN. The value does not
-- change, so outbound_identity is not superseded: there is nothing to correct.
--
-- WHAT THIS ROW ASSERTS, PRECISELY. That Crown states it checked ABN Lookup on
-- this date and found the number registered to this entity. Not that this
-- migration verified it — the environment cannot reach ABN Lookup, and a
-- record claiming otherwise would be the kind of provenance the rest of this
-- schema exists to prevent. The distinction is the same one evidence_record
-- draws between DIRECT_FETCH and OPERATOR_CAPTURE: who looked matters as much
-- as what they saw.

BEGIN;

INSERT INTO audit_event (actor_agent, action, object_table, object_id,
                         new_state, correlation_id)
SELECT 'migrations.0023', 'SENDER_ABN_CONFIRMED', 'outbound_identity',
       id::text,
       jsonb_build_object(
           'legal_entity_name', legal_entity_name,
           'abn', abn,
           'confirmed_by', 'Crown',
           'confirmed_on', '2026-09-22',
           'method', 'OPERATOR_CAPTURE — checked against ABN Lookup by a '
                     'person, reported to this system rather than retrieved '
                     'by it; the build environment cannot reach abr.business '
                     '.gov.au',
           'checksum', 'independently satisfied by abn_is_well_formed() since '
                       '0020, which proves the digits and not the ownership'),
       gen_random_uuid()
FROM outbound_identity WHERE is_active;

COMMIT;
