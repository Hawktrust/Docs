-- CROWN AI — MIGRATION 0024: which channel, and may Crown use it
--
-- CONSENT-POSITION.md concluded that the lawful channel differs by audience:
-- post for a landholder found in a public register, email for a professional
-- contact at a published work address or a buyer under a mandate. The reason is
-- that APP 7 and the Spam Act are separate tests and only the first has an
-- impracticability escape. Inferred consent under the Spam Act needs the
-- address to have been published BY THE PERSON, in a work capacity, with the
-- message relevant to that work. A landholder's details on a planning permit
-- fail all three limbs.
--
-- That conclusion lived only in a document. outbound_artifact knew its type and
-- its recipient and not how it was going out, so the control was a paragraph
-- somebody had to remember. Everything else in this schema works the other way
-- round: the opt-out is a constraint, the sender identity is a constraint, the
-- approval is a NOT NULL. A rule that decides whether a message is lawful
-- should not be the one thing kept in prose.
--
-- ON PHONE. There is no PHONE channel here, and its absence is the point. The
-- Do Not Call Register Act requires numbers to be washed before telemarketing
-- and the wash is valid for 30 days. Crown has not built that. Adding PHONE to
-- the enum would create a channel the schema appears to bless and the law does
-- not, which is worse than having no value for it at all. Add it in the same
-- migration that adds the wash.

BEGIN;

-- ============================================================
-- EXPRESS CONSENT
--
-- The Spam Act route Crown can actually rely on for a landholder: they replied,
-- or they signed something. Not inferred, not impracticable — those are APP 7
-- arguments and the Spam Act does not accept them.
--
-- Separate from contact_suppression rather than a flag on it, because they are
-- not opposites. A suppression is a request to stop, which outranks everything.
-- A consent is permission to use one channel. Somebody can consent to email and
-- later ask to stop, and both facts have to survive.
-- ============================================================

CREATE TABLE contact_consent (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    scope          text NOT NULL CHECK (scope IN ('PERSON','ADDRESS','PARCEL','ORGANISATION')),
    identifier     text NOT NULL,
    normalised     text NOT NULL,          -- same blunt form as suppression
    basis          text NOT NULL CHECK (basis IN ('EXPRESS_REPLY','EXPRESS_WRITTEN','MANDATE')),
    -- What actually happened, in a sentence. A consent nobody can describe is
    -- one nobody can defend, and "they consented" is not a description.
    evidence       text NOT NULL,
    given_at       timestamptz NOT NULL,
    recorded_by    uuid NOT NULL REFERENCES app_user(id),
    withdrawn_at   timestamptz,
    withdrawn_by   uuid REFERENCES app_user(id),
    created_at     timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT consent_evidence_is_not_blank
        CHECK (length(btrim(evidence)) > 0),
    CONSTRAINT withdrawal_names_who
        CHECK (withdrawn_at IS NULL OR withdrawn_by IS NOT NULL)
);

CREATE INDEX consent_lookup_idx ON contact_consent (scope, normalised)
    WHERE withdrawn_at IS NULL;

COMMENT ON TABLE contact_consent IS
    'Express consent to a channel. Not a substitute for the opt-out: a '
    'suppression outranks a consent, because stopping is always available.';

-- RLS from the start. Three tables have now been added to this schema without
-- it — buyer_mandate_real in 0004, market_actor in 0013, outbound_identity in
-- 0016 — each caught afterwards by the test that checks for exactly this.
ALTER TABLE contact_consent ENABLE ROW LEVEL SECURITY;
ALTER TABLE contact_consent FORCE ROW LEVEL SECURITY;

CREATE POLICY consent_read_by_all ON contact_consent FOR SELECT
    USING (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE'));

CREATE POLICY consent_recorded_by_all ON contact_consent FOR INSERT
    WITH CHECK (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE'));

-- Withdrawing is not restricted to compliance: a person saying "stop emailing
-- me" should be actionable by whoever is reading the reply.
CREATE POLICY consent_withdrawn_by_all ON contact_consent FOR UPDATE
    USING (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE'));

GRANT SELECT, INSERT, UPDATE ON contact_consent TO crown_app;

-- ============================================================
-- THE CHANNEL, AND WHO IS BEING WRITTEN TO
-- ============================================================

ALTER TABLE outbound_artifact
    ADD COLUMN channel         text,
    ADD COLUMN recipient_class text;

ALTER TABLE outbound_artifact
    ADD CONSTRAINT channel_is_one_crown_can_lawfully_use
        CHECK (channel IS NULL OR channel IN ('POST','EMAIL')),

    ADD CONSTRAINT recipient_class_is_known
        CHECK (recipient_class IS NULL OR recipient_class IN
               ('LANDHOLDER_FROM_REGISTER','PROFESSIONAL_CONTACT','MANDATED_BUYER')),

    -- Same shape as a_message_to_a_person_identifies_sender_and_recipient: the
    -- requirement attaches to the artefact types that are messages to people,
    -- and an EXPORT is exempt because it is not addressed to anybody.
    ADD CONSTRAINT a_message_to_a_person_names_its_channel
        CHECK (artifact_type NOT IN ('OUTREACH_DRAFT', 'BUYER_BRIEF')
               OR (channel IS NOT NULL AND recipient_class IS NOT NULL));

-- ============================================================
-- THE RULE ITSELF
--
-- A CHECK cannot do this: whether an email is lawful depends on a row in
-- another table. So it is a trigger, and it runs on INSERT and on UPDATE,
-- because a channel changed after the fact is the obvious way around a rule
-- enforced only at insert.
--
-- The trigger is deliberately narrow. It refuses exactly one combination —
-- email to a landholder sourced from a register, with no express consent on
-- record — and says why in a sentence somebody can act on. It does not try to
-- encode the whole of APP 7; that belongs in the privacy basis on the source
-- and in a human's judgement.
-- ============================================================

-- The matching form has to be identical to crown/suppression.py's normalise(),
-- which is `" ".join(s.strip().lower().split())`: collapse any run of
-- whitespace to one space, trim, lowercase. If these two drift, the rule stops
-- firing and nothing announces it — a control that silently never triggers is
-- worse than no control, because it is believed. A test compares the two
-- implementations on the same inputs rather than trusting this comment.

CREATE OR REPLACE FUNCTION normalise_identifier(raw text)
RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT btrim(regexp_replace(lower(raw), '\s+', ' ', 'g'))
$$;

COMMENT ON FUNCTION normalise_identifier(text) IS
    'Matching form for contact identifiers. Must stay identical to '
    'crown.suppression.normalise(); tests/test_channel.py compares them.';

CREATE FUNCTION email_to_a_landholder_needs_express_consent()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    -- Narrow on purpose: one combination is refused, everything else passes
    -- through untouched. This does not try to encode the whole of APP 7 —
    -- that lives in the privacy basis on the source and in a person's
    -- judgement.
    IF NEW.artifact_type NOT IN ('OUTREACH_DRAFT', 'BUYER_BRIEF')
       OR NEW.channel IS DISTINCT FROM 'EMAIL'
       OR NEW.recipient_class IS DISTINCT FROM 'LANDHOLDER_FROM_REGISTER'
    THEN
        RETURN NEW;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM contact_consent c
        WHERE c.withdrawn_at IS NULL
          -- MANDATE is excluded deliberately. A buyer's mandate is consent
          -- from the buyer, and says nothing about a landholder.
          AND c.basis IN ('EXPRESS_REPLY', 'EXPRESS_WRITTEN')
          AND c.scope = NEW.contact_scope
          AND c.normalised = normalise_identifier(NEW.contact_identifier)
    ) THEN
        RAISE EXCEPTION
            'no express consent on record for % %: a landholder identified '
            'from a public register may be written to by post, but emailing '
            'them is a commercial electronic message and the Spam Act needs '
            'consent the register does not supply. Send this by post, or '
            'record the reply that gave consent.',
            NEW.contact_scope, NEW.contact_identifier
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$;

-- On UPDATE as well as INSERT: a channel changed after the fact is the obvious
-- way around a rule enforced only at insert.
CREATE TRIGGER outbound_channel_is_lawful
    BEFORE INSERT OR UPDATE ON outbound_artifact
    FOR EACH ROW EXECUTE FUNCTION email_to_a_landholder_needs_express_consent();

-- ============================================================
-- THE GATE REPORTS IT
--
-- A constraint stops the row. The gate is what somebody reads before deciding
-- to launch, and "no artefact took a channel it was not entitled to" is worth
-- being able to say out loud rather than inferring from an absence of errors.
-- ============================================================

CREATE OR REPLACE VIEW channel_exception AS
SELECT oa.id,
       oa.artifact_type,
       oa.channel,
       oa.recipient_class,
       oa.contact_scope,
       oa.contact_identifier,
       CASE
           WHEN oa.channel IS NULL OR oa.recipient_class IS NULL
               THEN 'addressed to a person without naming a channel'
           WHEN oa.channel = 'EMAIL'
                AND oa.recipient_class = 'LANDHOLDER_FROM_REGISTER'
               THEN 'emailed a register-sourced landholder'
       END AS problem
FROM outbound_artifact oa
WHERE oa.artifact_type IN ('OUTREACH_DRAFT', 'BUYER_BRIEF')
  AND (oa.channel IS NULL
       OR oa.recipient_class IS NULL
       OR (oa.channel = 'EMAIL'
           AND oa.recipient_class = 'LANDHOLDER_FROM_REGISTER'
           AND NOT EXISTS (
               SELECT 1 FROM contact_consent c
               WHERE c.withdrawn_at IS NULL
                 AND c.basis IN ('EXPRESS_REPLY', 'EXPRESS_WRITTEN')
                 AND c.scope = oa.contact_scope
                 AND c.normalised = normalise_identifier(oa.contact_identifier))));

COMMENT ON VIEW channel_exception IS
    'Messages whose channel Crown is not entitled to use. Should always be '
    'empty; the trigger refuses the row. This is what says so.';

COMMIT;
