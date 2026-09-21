-- CROWN AI — MIGRATION 0008: the controls the prospecting product needs
--
-- Four gaps found reviewing the product vision (docs/PRODUCT-REVIEW.md). Each is
-- the kind of thing that is a policy document in most systems and therefore true
-- only while somebody remembers it.

BEGIN;

-- ============================================================
-- 1. SUPPRESSION — "do not contact me"
--
-- The vision describes alerts, outreach and briefs, and contained no mechanism
-- for a person who has asked not to be contacted. APP 7 requires a simple means
-- of opting out and requires it to work. This is the part a regulator checks
-- first, and it has to exist before the first outreach rather than after the
-- first complaint.
--
-- Deliberately not RLS-restricted for reading: every part of the system must be
-- able to see that someone is suppressed. Nobody is protected by a secret
-- do-not-contact list.
-- ============================================================

CREATE TABLE contact_suppression (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- what is suppressed. A request can name a person, an address, a parcel or
    -- a company, and the system should honour whichever it was given.
    scope           text NOT NULL CHECK (scope IN ('PERSON', 'ADDRESS', 'PARCEL', 'ORGANISATION')),
    identifier      text NOT NULL,
    normalised      text NOT NULL,          -- lowercased, trimmed, for matching
    reason          text NOT NULL,
    requested_at    timestamptz NOT NULL,
    recorded_by     uuid NOT NULL REFERENCES app_user(id),
    source_of_request text NOT NULL CHECK (source_of_request IN
                        ('OPT_OUT_LINK', 'EMAIL', 'PHONE', 'IN_PERSON', 'LEGAL', 'OTHER')),
    -- A suppression is not deleted when it expires; it is a permanent record
    -- that someone asked. released_at exists for the rare lawful case where a
    -- person later opts back in, and keeps the original request visible.
    released_at     timestamptz,
    released_by     uuid REFERENCES app_user(id),
    released_reason text,
    created_at      timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT release_is_explained
        CHECK (released_at IS NULL OR (released_by IS NOT NULL AND released_reason IS NOT NULL))
);

CREATE INDEX suppression_lookup_idx ON contact_suppression (scope, normalised)
    WHERE released_at IS NULL;

GRANT SELECT, INSERT, UPDATE ON contact_suppression TO crown_app;

COMMENT ON TABLE contact_suppression IS
    'People, addresses, parcels and organisations that have asked not to be '
    'contacted. Checked before any outbound artifact is created. A suppression '
    'is never deleted — releasing one records who released it and why.';

-- ============================================================
-- 2. PRINCIPAL — whose deal is this?
--
-- Crown invests for its own book, advises clients, and matches developers. Three
-- principals, one ranked pipeline. When a parcel scores well the system as
-- specified surfaces it to whoever opens the dashboard, which is a conflict of
-- interest running silently through the middle of the product.
--
-- Recording the principal does not resolve a conflict. It makes one visible, and
-- makes the disclosure a thing that exists rather than a thing someone meant to
-- do.
-- ============================================================

CREATE TYPE principal_kind AS ENUM ('CROWN_OWN_BOOK', 'CLIENT', 'DEVELOPER');

ALTER TABLE opportunity
    ADD COLUMN principal principal_kind,
    ADD COLUMN principal_label text;

COMMENT ON COLUMN opportunity.principal IS
    'Who this opportunity is being worked for. NULL until someone decides, which '
    'is honest: an opportunity raised by a rule has no principal yet.';

CREATE TABLE conflict_disclosure (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    opportunity_id   uuid NOT NULL REFERENCES opportunity(id),
    competing_opportunity_id uuid NOT NULL REFERENCES opportunity(id),
    disclosed_by     uuid NOT NULL REFERENCES app_user(id),
    disclosure       text NOT NULL,
    disclosed_at     timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT not_a_conflict_with_itself
        CHECK (opportunity_id <> competing_opportunity_id),
    CONSTRAINT one_disclosure_per_pair
        UNIQUE (opportunity_id, competing_opportunity_id)
);

GRANT SELECT, INSERT ON conflict_disclosure TO crown_app;

-- ============================================================
-- 3. RECOMMENDATIONS — an Acquire is a consequential output
--
-- Constitution §4: nothing consequential leaves without a stored approval id.
-- A recommendation that reaches a client or an investment committee is
-- consequential, so it goes through the same gate as an export.
--
-- The confidence is NOT a free field. It is derived from the evidence the
-- recommendation rests on — see crown/recommendation.py — because a separately
-- maintained confidence score drifts from the evidence classification within
-- weeks and then contradicts it in front of a client.
-- ============================================================

CREATE TYPE recommendation_decision AS ENUM
    ('ACQUIRE', 'NEGOTIATE', 'OPTION', 'JOINT_VENTURE', 'WATCH', 'AVOID');
CREATE TYPE recommendation_timing AS ENUM
    ('IMMEDIATE', 'ONE_TO_THREE_YEARS', 'THREE_TO_SEVEN_YEARS', 'LONG_TERM');
CREATE TYPE recommendation_confidence AS ENUM ('CONFIRMED', 'PROBABLE', 'SPECULATIVE');

CREATE TABLE recommendation (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    opportunity_id   uuid NOT NULL REFERENCES opportunity(id),
    approval_id      uuid NOT NULL REFERENCES approval(id),  -- the §4 gate
    principal        principal_kind NOT NULL,
    principal_label  text NOT NULL,

    decision         recommendation_decision NOT NULL,
    strategy         text NOT NULL,
    timing           recommendation_timing NOT NULL,
    confidence       recommendation_confidence NOT NULL,
    rationale        text NOT NULL,

    -- Economics, if any, and the assumptions that produced them. A figure
    -- without its assumptions is a liability: residual land value moves
    -- enormously on a small change to a sales rate, and printed beside
    -- provenanced planning evidence it borrows a credibility it has not earned.
    economics        jsonb,
    economics_assumptions jsonb,

    -- What the recommendation rested on, as it was, at the moment it was made.
    -- Six months later the zoning has changed and the comparables are different;
    -- without this the question "what did we know when we recommended this?"
    -- has no answer.
    evidence_snapshot jsonb NOT NULL,

    created_by       uuid NOT NULL REFERENCES app_user(id),
    created_at       timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT economics_ship_with_assumptions
        CHECK (economics IS NULL OR economics_assumptions IS NOT NULL),
    CONSTRAINT one_recommendation_per_approval UNIQUE (approval_id)
);

CREATE INDEX recommendation_opportunity_idx ON recommendation (opportunity_id);

GRANT SELECT, INSERT ON recommendation TO crown_app;

-- A recommendation is a permanent record, like attribution. It is what someone
-- relied on.
CREATE TRIGGER recommendation_no_update BEFORE UPDATE ON recommendation
    FOR EACH STATEMENT EXECUTE FUNCTION audit_append_only();
CREATE TRIGGER recommendation_no_delete BEFORE DELETE ON recommendation
    FOR EACH STATEMENT EXECUTE FUNCTION audit_append_only();

ALTER TABLE recommendation ENABLE ROW LEVEL SECURITY;
ALTER TABLE recommendation FORCE ROW LEVEL SECURITY;

CREATE POLICY recommendation_read ON recommendation FOR SELECT
    USING (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE'));

CREATE POLICY recommendation_insert ON recommendation FOR INSERT
    WITH CHECK (crown_role() IN ('ADMIN','ANALYST'));

-- ============================================================
-- 4. OUTBOUND now covers a recommendation and an IC brief
-- ============================================================

ALTER TABLE outbound_artifact DROP CONSTRAINT outbound_artifact_artifact_type_check;
ALTER TABLE outbound_artifact
    ADD CONSTRAINT outbound_artifact_artifact_type_check
        CHECK (artifact_type IN ('EXPORT', 'OUTREACH_DRAFT', 'BUYER_BRIEF',
                                 'RECOMMENDATION', 'IC_BRIEF', 'ALERT'));

COMMIT;
