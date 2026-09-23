-- CROWN AI — MIGRATION 0021: Crown's contact address changes
--
-- inder@crownrealestateagents.com.au becomes inder@crownrea.com.au. Crown
-- asked for it 2026-09-22; same person, same company, shorter domain.
--
-- Two records carry that address and they change in two different ways,
-- because they mean two different things.
--
-- app_user is WHO SIGNS IN. It is edited in place, keeping the same id, so
-- every audit row, approval and created_by reference stays attached to the
-- person who actually did those things. Replacing the account instead would
-- orphan the history of a real person behind an inactive row, which is the
-- opposite of what an audit trail is for.
--
-- outbound_identity is WHAT THE MESSAGES SAID. 0017 freezes its content and
-- names the reason in the exception text: messages already sent record this
-- row as their sender, and s17 of the Spam Act requires that to stay accurate
-- for 30 days after sending. So the old row is not corrected. It is retired,
-- and a new one takes over from today.
--
-- That distinction is the whole design. An address a person can be reached at
-- is a fact about now; an address a message claimed is a fact about when it
-- was sent, and those stop being the same thing the moment one of them
-- changes.

BEGIN;

-- ============================================================
-- THE ACCOUNT
--
-- Same row, same uuid, new address. Nothing references app_user by email —
-- audit_event.actor_user_id, approval and created_by are all uuids — so the
-- history follows the person rather than the string.
-- ============================================================

INSERT INTO audit_event (actor_agent, action, object_table, object_id,
                         previous_state, new_state, correlation_id)
SELECT 'migrations.0021', 'USER_EMAIL_CHANGED', 'app_user', id::text,
       jsonb_build_object('email', email),
       jsonb_build_object('email', 'inder@crownrea.com.au'),
       gen_random_uuid()
FROM app_user WHERE email = 'inder@crownrealestateagents.com.au';

UPDATE app_user SET email = 'inder@crownrea.com.au'
WHERE email = 'inder@crownrealestateagents.com.au';

-- ============================================================
-- THE SENDER IDENTITY
--
-- Retire, then insert. In that order, because one_active_outbound_identity is
-- a unique index over the active rows and two would collide — which is itself
-- deliberate: a recipient must not have to guess which of two organisations
-- authorised the message.
--
-- Everything but the email carries over unchanged. The ABN still passes the
-- 0020 checksum constraint; the entity and address were never in question.
--
-- The retired row keeps its own contact_email. A message sent yesterday said
-- inder@crownrealestateagents.com.au, and that is what it said. Whether that
-- address still reaches somebody is a question for Crown, not for this
-- migration: s18 gives an unsubscribe facility thirty days, and s17 wants the
-- sender's contact details accurate for thirty days after sending, so the old
-- mailbox needs to keep receiving for at least that long after the last
-- message that named it.
-- ============================================================

UPDATE outbound_identity
SET is_active = false, superseded_at = now()
WHERE is_active;

INSERT INTO outbound_identity
    (legal_entity_name, abn, postal_address, contact_email,
     contact_phone, created_by)
SELECT old.legal_entity_name,
       old.abn,
       old.postal_address,
       'inder@crownrea.com.au',
       old.contact_phone,
       (SELECT id FROM app_user WHERE email = 'inder@crownrea.com.au')
FROM outbound_identity old
WHERE old.superseded_at IS NOT NULL
ORDER BY old.superseded_at DESC, old.created_at DESC
LIMIT 1;

INSERT INTO audit_event (actor_agent, action, object_table, object_id,
                         new_state, correlation_id)
SELECT 'migrations.0021', 'OUTBOUND_IDENTITY_SUPERSEDED', 'outbound_identity',
       id::text,
       jsonb_build_object(
           'legal_entity_name', legal_entity_name,
           'contact_email', contact_email,
           'previously', 'inder@crownrealestateagents.com.au',
           'basis', 'Crown changed its contact address 2026-09-22; same '
                    'person and same entity, so the identity is superseded '
                    'rather than edited and the retired row keeps the address '
                    'the messages sent under it actually carried'),
       gen_random_uuid()
FROM outbound_identity WHERE is_active;

COMMIT;
