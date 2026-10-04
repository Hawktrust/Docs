-- CROWN AI — MIGRATION 0029: which views may see past a policy, and why
--
-- Found by auditing rather than by a failure, and the finding is not a hole.
-- The system is sound today. What it is, is sound by accident in two places.
--
-- A view without security_invoker runs with its OWNER's privileges and its
-- owner's row-level security context. Since the owner is the schema owner,
-- such a view sees every row regardless of the caller's policies. Eleven views
-- exist; four set security_invoker and seven do not, and nothing anywhere says
-- which is intended.
--
-- Three of the seven expose row-level data:
--
--   channel_exception             contact_identifier — a person's NAME
--   opt_out_prominence_exception  contact_identifier — the same
--   retention_due                 the ids of artefacts past their retention
--
-- Today crown_app has no SELECT grant on any of them, so the bypass is not
-- reachable from the application. That is the accident. The protection is a
-- GRANT that was never made, not the control the schema is built on — and the
-- obvious next change, granting one of these so an exception can be surfaced in
-- the interface, would silently turn it into a way to read a landholder's name
-- past the policy meant to protect it. Nobody making that change would have any
-- reason to suspect it.
--
-- So: belt and braces. They become caller-scoped, which costs nothing because
-- nothing reads them as crown_app, and a later GRANT then stays safe.
--
-- launch_readiness IS NOT CHANGED, and that is deliberate. It is the launch
-- gate, and its whole job is to count rows across the entire database — "0
-- outbound artefact(s) built on synthetic records" has to mean zero anywhere,
-- not zero among the rows this caller happens to see. Made caller-scoped it
-- would report comfortable numbers computed over a subset and call the system
-- ready. A gate that sees less than the whole is not a gate.
--
-- data_rights_exception, parcel_planning_current and parcel_dwelling_current
-- are left as they are too. The first reads data_source, which has no policies
-- for anyone; the other two read parcels, which carry no personal information
-- at all. Naming them here so the next reader knows they were considered rather
-- than missed.

BEGIN;

ALTER VIEW channel_exception            SET (security_invoker = true);
ALTER VIEW opt_out_prominence_exception SET (security_invoker = true);
ALTER VIEW retention_due                SET (security_invoker = true);

COMMENT ON VIEW launch_readiness IS
    'The launch gate. Deliberately NOT security_invoker: it counts rows across '
    'the whole database, and a caller-scoped version would compute every check '
    'over a subset and report the system ready on the strength of rows the '
    'caller cannot see. Do not "fix" this to match the others.';

COMMENT ON VIEW channel_exception IS
    'Messages whose channel Crown is not entitled to use. security_invoker, '
    'because it exposes contact_identifier and a view is otherwise a way '
    'around the policy protecting it.';

COMMENT ON VIEW opt_out_prominence_exception IS
    'Messages whose way out a reader would have to hunt for. security_invoker, '
    'for the same reason as channel_exception.';

COMMIT;
