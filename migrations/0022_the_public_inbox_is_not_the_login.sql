-- CROWN AI — MIGRATION 0022: the address on the messages is not the login
--
-- 0019 set both of Crown's email fields from the one address Crown gave, and
-- 0021 moved both to the new domain. They were never the same kind of thing.
--
--   app_user.email                  a username. How a person signs in. Never
--                                   leaves the system; nobody outside sees it.
--
--   outbound_identity.contact_email  a published contact point. The s17 "how to
--                                   contact them" limb, printed on every
--                                   commercial message to a stranger and in
--                                   the privacy policy and collection notice.
--
-- The second one goes to people who did not ask to hear from Crown. It
-- receives opt-out replies, APP 12 and 13 access and correction requests, and
-- complaints. It gets scraped and it gets angry replies. Crown chose
-- info@crownrea.com.au for it, 2026-09-22.
--
-- The login stays inder@crownrea.com.au. Keeping a personal address off every
-- cold approach is the smaller reason. The larger one is that a published
-- contact point has to keep working when the person behind it is on leave, and
-- an address tied to one human does not.
--
-- WHAT THIS MIGRATION CANNOT DO. It cannot check that info@crownrea.com.au
-- exists or that anybody reads it. 0020's THE_SENDER_IDENTITY_IS_USABLE
-- checks the address is shaped like one, which is the most a query can decide.
-- A published address nobody reads satisfies s17's letter and defeats its
-- purpose, and APP 1.4 wants a contactable person rather than a contactable
-- string.

BEGIN;

-- Retire, then insert: one_active_outbound_identity is a unique index over the
-- active rows, and two active senders would leave a recipient unable to tell
-- which organisation authorised the message.
--
-- The retired row keeps inder@crownrea.com.au, because 0017 freezes content
-- and that is what any message sent under it carried. Nothing has been sent,
-- so nothing is owed the thirty days s17 and s18 require — but the row is
-- superseded rather than corrected anyway, because the day that stops being
-- true is not the day to start doing it properly.

UPDATE outbound_identity
SET is_active = false, superseded_at = now()
WHERE is_active;

INSERT INTO outbound_identity
    (legal_entity_name, abn, postal_address, contact_email,
     contact_phone, created_by)
SELECT old.legal_entity_name,
       old.abn,
       old.postal_address,
       'info@crownrea.com.au',
       old.contact_phone,
       old.created_by
FROM outbound_identity old
WHERE old.superseded_at IS NOT NULL
ORDER BY old.superseded_at DESC, old.created_at DESC
LIMIT 1;

INSERT INTO audit_event (actor_agent, action, object_table, object_id,
                         new_state, correlation_id)
SELECT 'migrations.0022', 'OUTBOUND_IDENTITY_SUPERSEDED', 'outbound_identity',
       id::text,
       jsonb_build_object(
           'legal_entity_name', legal_entity_name,
           'contact_email', contact_email,
           'previously', 'inder@crownrea.com.au',
           'basis', 'Crown separated the published contact point from the '
                    'login 2026-09-22. The address on a message is read by '
                    'people who did not ask to hear from Crown and must keep '
                    'working when one person is away; the login identifies '
                    'one human and should not.'),
       gen_random_uuid()
FROM outbound_identity WHERE is_active;

COMMIT;
