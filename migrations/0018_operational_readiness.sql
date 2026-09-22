-- CROWN AI — MIGRATION 0018: the brief is a message too, and two more launch
-- conditions worth failing on
--
-- 0016 required a named recipient, a named sender and therefore a working
-- opt-out on an OUTREACH_DRAFT, and said in its own comment that a BUYER_BRIEF
-- sent by email is also a commercial electronic message and should be added
-- here rather than exempted in code. This adds it.
--
-- The distinction that made it tempting to leave out: a buyer has a mandate
-- with Crown, which supplies the consent a cold approach lacks. But consent is
-- only one of the Spam Act's three requirements. Sections 17 and 18 want the
-- message to identify its sender and carry a way to stop, consent or not. A
-- brief handed over in a meeting needs neither, and the schema cannot tell that
-- apart from one that was emailed — so it requires them of both, which costs a
-- contact field on an artefact that was going to name its recipient anyway.

BEGIN;

ALTER TABLE outbound_artifact
    DROP CONSTRAINT outreach_identifies_sender_and_recipient;

ALTER TABLE outbound_artifact
    ADD CONSTRAINT a_message_to_a_person_identifies_sender_and_recipient
        CHECK (artifact_type NOT IN ('OUTREACH_DRAFT', 'BUYER_BRIEF')
               OR (contact_scope IS NOT NULL
                   AND contact_identifier IS NOT NULL
                   AND sender_identity_id IS NOT NULL));

-- ============================================================
-- TWO MORE THINGS THAT SHOULD STOP A LAUNCH
--
-- The gate reads the database, so it can only ever check what the database
-- knows. Both of these are things it knows and was not asking.
-- ============================================================

CREATE OR REPLACE VIEW launch_readiness AS

SELECT 'DATA_RIGHTS_COMPLETE'::text AS check_code,
       'BLOCKING'::text             AS severity,
       (count(*) = 0)               AS passes,
       count(*)::text || ' source(s) in use with an incomplete register entry'
                                    AS detail,
       'complete the register entry or stop ingesting from it'::text AS closes_it
FROM data_rights_exception

UNION ALL

SELECT 'EVERY_INGESTIBLE_SOURCE_HAS_A_POSITION', 'BLOCKING',
       count(*) = 0,
       count(*)::text || ' ingestible source(s) with automated_access UNKNOWN',
       'read the publisher''s terms and record a position, or leave the source off'
FROM data_source
WHERE is_ingestible AND automated_access = 'UNKNOWN'

UNION ALL

SELECT 'PERSONAL_SOURCES_STATE_THEIR_BASIS', 'BLOCKING',
       count(*) = 0,
       count(*)::text || ' source(s) identify people with no privacy basis recorded',
       'record which APP is relied on, the consent position and where the '
       'suppression list lives'
FROM data_source
WHERE is_ingestible AND carries_personal_information AND privacy_basis IS NULL

UNION ALL

SELECT 'REAL_EVIDENCE_EXISTS', 'BLOCKING',
       count(*) > 0,
       count(*)::text || ' evidence record(s) with origin REAL',
       'ingest one real amendment — by allowlist, or by operator capture, '
       'which needs no policy change'
FROM evidence_record WHERE origin = 'REAL'

UNION ALL

SELECT 'NOTHING_SYNTHETIC_HAS_LEFT', 'BLOCKING',
       count(*) = 0,
       count(*)::text || ' outbound artefact(s) built on synthetic records',
       'these are demonstration artefacts; delete them or keep this environment '
       'out of production'
FROM outbound_artifact oa
JOIN approval a       ON a.id = oa.approval_id
JOIN match_result m   ON m.id = a.match_result_id
JOIN opportunity o    ON o.id = m.opportunity_id
JOIN buyer_mandate b  ON b.id = m.buyer_mandate_id
WHERE o.origin = 'DEMO_SYNTHETIC' OR b.origin = 'DEMO_SYNTHETIC'

UNION ALL

SELECT 'CROWN_KNOWS_WHO_IT_SENDS_AS', 'BLOCKING',
       count(*) = 1,
       count(*)::text || ' active outbound identity',
       'record the legal entity, postal address and contact email that every '
       'message will carry'
FROM outbound_identity WHERE is_active

UNION ALL

-- Now covers the brief as well as the cold approach.
SELECT 'EVERY_MESSAGE_OFFERS_A_WAY_OUT', 'BLOCKING',
       count(*) = 0,
       count(*)::text || ' message(s) with no recipient or no sender',
       'nothing can be sent to a person without a way for them to stop it'
FROM outbound_artifact
WHERE artifact_type IN ('OUTREACH_DRAFT', 'BUYER_BRIEF')
  AND (contact_scope IS NULL OR contact_identifier IS NULL
       OR sender_identity_id IS NULL)

UNION ALL

SELECT 'EVERY_ACCOUNT_HAS_A_PASSWORD', 'BLOCKING',
       count(*) = 0,
       count(*)::text || ' active account(s) with no password set',
       'set a password or deactivate the account'
FROM app_user WHERE is_active AND password_hash IS NULL

UNION ALL

SELECT 'MATCH_WEIGHTS_ARE_VERSIONED', 'BLOCKING',
       count(*) > 0,
       count(*)::text || ' active match weight configuration(s)',
       'activate a weight configuration so every score records the version '
       'that produced it'
FROM match_weight_config WHERE is_active

UNION ALL

-- NEW. Somebody has to be able to answer a person who asks what Crown holds
-- about them, and somebody has to be answerable when a suppression is lifted.
-- Neither works without an account that can do it.
SELECT 'SOMEBODY_CAN_ANSWER_A_PERSON', 'BLOCKING',
       count(*) > 0,
       count(*)::text || ' active ADMIN or COMPLIANCE account(s)',
       'APP 1.4 requires a contactable person for access, correction and '
       'complaints; create at least one account that can act on them'
FROM app_user
WHERE is_active AND password_hash IS NOT NULL
  AND role IN ('ADMIN', 'COMPLIANCE')

UNION ALL

-- NEW. A suppression that was released without a reason is a person who asked
-- not to be contacted and is being contacted again. The CHECK in 0008 requires
-- the reason; this reports the releases so a human reads them, because a
-- constraint cannot tell a good reason from a bad one.
SELECT 'RELEASED_SUPPRESSIONS_HAVE_BEEN_REVIEWED', 'ADVISORY',
       count(*) = 0,
       count(*)::text || ' suppression(s) released in the last 90 days',
       'read each release: somebody who asked not to be contacted is being '
       'contacted again, and only a person can judge whether that was right'
FROM contact_suppression
WHERE released_at IS NOT NULL AND released_at > now() - interval '90 days'

UNION ALL

SELECT 'NO_EVIDENCE_IS_PAST_ITS_SHELF_LIFE', 'ADVISORY',
       count(*) = 0,
       count(*)::text || ' evidence record(s) past their shelf life',
       're-retrieve the source and update last_verified_at'
FROM stale_evidence

UNION ALL

SELECT 'SOMEBODY_IS_WATCHING_SOMETHING', 'ADVISORY',
       count(*) > 0,
       count(*)::text || ' active watchlist(s)',
       'a system that alerts nobody about nothing will not be noticed when it '
       'stops working'
FROM watchlist WHERE is_active;

COMMIT;
