-- CROWN AI — MIGRATION 0020: an identity check that checks the identity
--
-- 0016 built `outbound_identity` and a readiness check for it. The check counts
-- rows: exactly one active identity and it passes. 0019 wrote that row, the
-- check went green, and it would have gone green just as readily on
--
--     legal_entity_name = 'TBD'
--     abn               = '00 000 000 000'
--     contact_email     = 'x'
--
-- because none of that is what it looks at. Section 17 does not ask whether a
-- sender identity exists. It asks that the message ACCURATELY identify who
-- authorised it and say HOW TO CONTACT THEM. A row of placeholders satisfies
-- the count and fails the Act, and the gate would have said nothing.
--
-- Three things a machine can actually decide, and one it cannot.
--
-- CAN: whether an ABN is well formed. The ATO's checksum is a pure function of
-- eleven digits, so a typo in the number Crown puts on every message is
-- catchable here rather than by a recipient.
--
-- CAN: whether a contact email is shaped like one. Weak, but it separates an
-- address from a note-to-self.
--
-- CAN: whether the two records that name who is accountable agree. The data
-- rights register says who stands behind a source being lawful to use;
-- `outbound_identity` says who authorised the message built from it. Nothing
-- structurally tied them together, so 0019 set both by hand and they happen to
-- match. "Happen to" is not a property.
--
-- CANNOT: whether the postal address is real, whether the ABN belongs to this
-- entity, or whether anybody reads the inbox. Those stay human, and the point
-- of checking what can be checked is to make the remaining judgements visible
-- rather than lost in a list of things that are all nominally fine.

BEGIN;

-- ============================================================
-- THE ABN CHECKSUM
--
-- Subtract 1 from the first digit, weight the eleven digits by
-- 10,1,3,5,7,9,11,13,15,17,19, and the sum is divisible by 89.
--
-- What this proves: the digits are internally consistent, so a transposition
-- or a mistyped digit is caught. 86690344597 passes — weighted sum 623, and
-- 623 = 7 x 89.
--
-- What it does NOT prove: that the ABN belongs to Crown Real Estate Agents Pty
-- Ltd. Only ABN Lookup can say that, and a well formed ABN belonging to
-- somebody else is a worse s17 breach than no ABN at all, because it is a
-- false identification rather than an absent one. This function cannot tell
-- those apart and does not claim to.
-- ============================================================

CREATE OR REPLACE FUNCTION abn_is_well_formed(candidate text)
RETURNS boolean
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE
    weights constant int[] := ARRAY[10,1,3,5,7,9,11,13,15,17,19];
    digits  text;
    total   int := 0;
    d       int;
BEGIN
    -- Digits and spaces only. Stripping punctuation out of anything at all
    -- would let 'ABN: 86 690 344 597 (unconfirmed)' pass as a stored value,
    -- and what is stored is what goes on the message.
    IF btrim(candidate) !~ '^[0-9][0-9 ]*[0-9]$' THEN
        RETURN false;
    END IF;

    digits := replace(btrim(candidate), ' ', '');
    IF length(digits) <> 11 THEN
        RETURN false;
    END IF;

    FOR i IN 1..11 LOOP
        d := substr(digits, i, 1)::int;
        IF i = 1 THEN
            d := d - 1;          -- yields -1 for a leading zero, which then
        END IF;                  -- fails the modulus, which is correct
        total := total + d * weights[i];
    END LOOP;

    RETURN total % 89 = 0;
END;
$$;

COMMENT ON FUNCTION abn_is_well_formed(text) IS
    'ATO weighted-modulus check. Proves the digits are consistent, not that '
    'the ABN belongs to anybody. Confirm ownership on ABN Lookup.';

-- The constraint is on the stored value rather than only in the readiness
-- view, because 0017 froze this table's content: a bad ABN cannot be edited
-- out, only superseded. Refusing it at write time is the cheaper moment.
ALTER TABLE outbound_identity
    ADD CONSTRAINT the_abn_is_well_formed
    CHECK (abn IS NULL OR abn_is_well_formed(abn));

-- ============================================================
-- THE READINESS VIEW
--
-- CROWN_KNOWS_WHO_IT_SENDS_AS is left exactly as it was. It answers "is there
-- one active identity", which is a real question with a clear answer, and
-- overloading it with quality checks would have made a failure ambiguous
-- between "none recorded" and "recorded badly" — two different problems with
-- two different fixes.
--
-- Two new checks instead, each with one meaning.
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

-- NEW. The identity exists; this asks whether it would survive being read by
-- the person it was sent to.
SELECT 'THE_SENDER_IDENTITY_IS_USABLE', 'BLOCKING',
       count(*) = 0,
       -- Worded so it stays true when there is no identity at all, which
       -- CROWN_KNOWS_WHO_IT_SENDS_AS is the check that reports.
       CASE count(*)
           WHEN 0 THEN 'no malformed field in the active sender identity'
           ELSE string_agg(problem, '; ')
       END,
       'supersede the row with a corrected one — 0017 freezes it, so this is '
       'a new row and not an edit'
FROM (
    SELECT CASE
               WHEN abn IS NOT NULL AND NOT abn_is_well_formed(abn)
                   THEN 'the ABN fails the ATO checksum'
               WHEN contact_email !~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'
                   THEN 'the contact email is not shaped like an address'
               WHEN btrim(postal_address) = ''
                   THEN 'the postal address is blank'
           END AS problem
    FROM outbound_identity WHERE is_active
) checked
WHERE problem IS NOT NULL

UNION ALL

-- NEW. Two records name who is accountable. A regulator pulling on either
-- thread should arrive at the same legal person; 0019 made that true by hand
-- and nothing kept it true.
SELECT 'ACCOUNTABILITY_NAMES_ONE_ENTITY', 'BLOCKING',
       count(*) = 0,
       count(*)::text || ' signed register entr(ies) naming somebody other '
                         'than the active sender',
       'the register says who stands behind a source and outbound_identity '
       'says who authorised the message; they must name the same person'
FROM data_source ds
WHERE ds.register_confirmed_by IS NOT NULL
  AND EXISTS (SELECT 1 FROM outbound_identity WHERE is_active)
  AND NOT EXISTS (
      SELECT 1 FROM outbound_identity oi
      WHERE oi.is_active
        -- position(), not ILIKE: a legal entity name is data, and data with a
        -- % in it should not become a wildcard.
        AND position(oi.legal_entity_name in ds.register_confirmed_by) > 0)

UNION ALL

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

SELECT 'SOMEBODY_CAN_ANSWER_A_PERSON', 'BLOCKING',
       count(*) > 0,
       count(*)::text || ' active ADMIN or COMPLIANCE account(s)',
       'APP 1.4 requires a contactable person for access, correction and '
       'complaints; create at least one account that can act on them'
FROM app_user
WHERE is_active AND password_hash IS NOT NULL
  AND role IN ('ADMIN', 'COMPLIANCE')

UNION ALL

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
