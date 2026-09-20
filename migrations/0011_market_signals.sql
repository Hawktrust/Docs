-- CROWN AI — MIGRATION 0011: who is moving, and where
--
-- Three questions, three different answers.
--
-- BIG FIRMS. Listed developers must disclose material acquisitions to the ASX,
-- and publish landbank tables by region in their investor presentations. They
-- lodge planning permits, appear at panels and make PSP submissions. All public,
-- all free, and all earlier than a title transfer.
--
-- GOVERNMENT. Already in the data. A Public Acquisition Overlay is a planning
-- control used by a Minister, authority or council to identify land proposed to
-- be acquired for a public purpose. It sits in the overlay list Crown already
-- ingests — so "where is government acquiring" is a query against
-- parcel_planning.overlay_codes, not a new source.
--
-- BUYER AGENTS. Their buying is client-confidential and not public, and will
-- not become public. Their recommendations are: commentary, hotspot lists,
-- media. That is opinion rather than action, and it is weighted accordingly —
-- lowest of every signal type here, because by the time a suburb is on a
-- hotspot list the move has happened.
--
-- ELECTED OFFICIALS. Registers of interests are published for scrutiny of the
-- people in them. Using them to notice that a region attracts investment is one
-- thing; naming an individual politician in a prospecting brief is another, and
-- it is both a misuse of a transparency mechanism and reputationally
-- indefensible. The schema enforces the difference: such an actor counts toward
-- a geography and can never be published by name.

BEGIN;

CREATE TYPE actor_kind AS ENUM (
    'LISTED_DEVELOPER', 'PRIVATE_DEVELOPER', 'FUND', 'BUYER_AGENT',
    'GOVERNMENT_BODY', 'ELECTED_OFFICIAL', 'OTHER');

CREATE TYPE signal_kind AS ENUM (
    'ASX_ANNOUNCEMENT',          -- a listed entity disclosing an acquisition
    'LANDBANK_DISCLOSURE',       -- investor presentation, pipeline by region
    'PERMIT_APPLICATION',        -- lodged with a council, public register
    'PANEL_SUBMISSION',          -- a party to an amendment at Panels Victoria
    'PSP_SUBMISSION',            -- a party to a precinct structure plan
    'INFRASTRUCTURE_COMMITMENT', -- a funded project in a published pipeline
    'PUBLIC_ACQUISITION_OVERLAY',-- government has flagged intent to acquire
    'INTEREST_REGISTER',         -- a published register of interests
    'PUBLIC_COMMENTARY');        -- opinion: hotspot lists, media, podcasts

CREATE TABLE market_actor (
    id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name      text NOT NULL,
    normalised text NOT NULL UNIQUE,
    kind      actor_kind NOT NULL,
    aliases   text[] NOT NULL DEFAULT '{}',
    asx_code  text,
    notes     text,

    -- False means this actor counts toward a geography and is never named in
    -- anything that leaves. Elected officials are always false.
    publishable_by_name boolean NOT NULL DEFAULT true,
    origin    data_origin NOT NULL DEFAULT 'REAL',
    created_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT elected_officials_are_never_named
        CHECK (kind <> 'ELECTED_OFFICIAL' OR publishable_by_name = false)
);

CREATE INDEX market_actor_kind_idx ON market_actor (kind);

CREATE TABLE actor_signal (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id     uuid NOT NULL REFERENCES market_actor(id),
    signal_kind  signal_kind NOT NULL,
    lga          text NOT NULL,
    locality     text,
    observed_at  date NOT NULL,

    -- Same provenance discipline as evidence. A signal nobody can point at is
    -- a rumour, and the Constitution says rumours are never presented as facts.
    source_id    uuid NOT NULL REFERENCES data_source(id),
    source_url   text NOT NULL,
    retrieved_at timestamptz NOT NULL,
    evidence_id  uuid REFERENCES evidence_record(id),
    detail       text NOT NULL,
    origin       data_origin NOT NULL DEFAULT 'REAL',
    created_at   timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT one_signal_per_actor_place_and_day
        UNIQUE (actor_id, signal_kind, lga, locality, observed_at)
);

CREATE INDEX actor_signal_place_idx ON actor_signal (lga, locality);
CREATE INDEX actor_signal_when_idx  ON actor_signal (observed_at DESC);
CREATE INDEX actor_signal_kind_idx  ON actor_signal (signal_kind);

-- Weights in config, not hardcoded — the same discipline as the match weights,
-- and for the same reason: the numbers that decide a ranking are configuration
-- and every change to them is audited.
CREATE TABLE signal_weight_config (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- a version is a whole set of weights, one row per signal kind, so version
    -- is unique with the kind rather than on its own
    version     integer NOT NULL,
    signal_kind signal_kind NOT NULL,
    weight      numeric(4,3) NOT NULL CHECK (weight BETWEEN 0 AND 1),
    is_active   boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (version, signal_kind)
);

CREATE INDEX signal_weight_active_idx ON signal_weight_config (is_active)
    WHERE is_active;

CREATE OR REPLACE FUNCTION audit_signal_weight_change() RETURNS trigger AS $$
DECLARE actor text := nullif(current_setting('crown.user_id', true), '');
BEGIN
    INSERT INTO audit_event (actor_user_id, actor_agent, action, object_table,
                             object_id, previous_state, new_state, correlation_id)
    VALUES (CASE WHEN actor IS NOT NULL THEN actor::uuid END,
            'db.signal_weight_config', 'SIGNAL_WEIGHTS_' || TG_OP,
            'signal_weight_config', NEW.id::text,
            CASE WHEN TG_OP = 'UPDATE' THEN to_jsonb(OLD) END,
            to_jsonb(NEW), gen_random_uuid());
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER signal_weight_audited
    AFTER INSERT OR UPDATE ON signal_weight_config
    FOR EACH ROW EXECUTE FUNCTION audit_signal_weight_change();

-- Action outranks opinion. A listed developer disclosing an acquisition is the
-- strongest thing here; a hotspot list is the weakest, because by the time a
-- suburb appears on one the move has already happened.
INSERT INTO signal_weight_config (version, signal_kind, weight, is_active) VALUES
    (1, 'ASX_ANNOUNCEMENT',           1.000, true),
    (1, 'LANDBANK_DISCLOSURE',        0.900, true),
    (1, 'PERMIT_APPLICATION',         0.800, true),
    (1, 'PANEL_SUBMISSION',           0.700, true),
    (1, 'PSP_SUBMISSION',             0.700, true),
    (1, 'PUBLIC_ACQUISITION_OVERLAY', 0.650, true),
    (1, 'INFRASTRUCTURE_COMMITMENT',  0.600, true),
    (1, 'INTEREST_REGISTER',          0.300, true),
    (1, 'PUBLIC_COMMENTARY',          0.150, true);

-- What may be shown with a name against it. Everything else still counts.
CREATE VIEW actor_signal_publishable AS
    SELECT s.*, a.name, a.kind, a.asx_code
    FROM actor_signal s JOIN market_actor a ON a.id = s.actor_id
    WHERE a.publishable_by_name;
ALTER VIEW actor_signal_publishable SET (security_invoker = true);

GRANT SELECT, INSERT ON market_actor, actor_signal TO crown_app;
GRANT SELECT ON signal_weight_config, actor_signal_publishable TO crown_app;

-- ============================================================
-- The sources these signals come from.
-- ============================================================

INSERT INTO data_source (code, display_name, provider, lane, licence_reference,
                         attribution_text, is_ingestible, notes,
                         carries_personal_information, automated_access,
                         terms_reference, terms_read_by, terms_read_at)
VALUES
    ('ASX_ANNOUNCEMENTS', 'ASX company announcements', 'ASX Limited', 'B_OPEN',
     NULL, NULL, false,
     'Listed developers must disclose material acquisitions. Announcements are public '
     'and are the earliest confirmed record of a corporate land purchase. Check the '
     'terms for automated retrieval before pointing anything at it.',
     false, 'UNKNOWN', NULL, NULL, NULL),

    ('COUNCIL_PLANNING_REGISTERS', 'Council planning permit registers',
     'Victorian councils', 'B_OPEN', NULL, NULL, false,
     'Public registers of lodged applications, naming the applicant. A developer '
     'lodging on a site is intent, months before a transfer registers. Several councils '
     'publish an RSS or email alert, which is the publisher offering the channel.',
     true, 'UNKNOWN', NULL, NULL, NULL),

    ('PANELS_VICTORIA', 'Panels Victoria hearings and submissions',
     'Planning Panels Victoria', 'B_OPEN', NULL, NULL, false,
     'Submissions to an amendment name the parties. Who bothered to make a submission '
     'on a rezoning tells you who holds land inside it.',
     true, 'UNKNOWN', NULL, NULL, NULL),

    ('INFRASTRUCTURE_PIPELINE', 'Australian Government infrastructure pipeline',
     'Department of Infrastructure, Transport, Regional Development', 'B_OPEN',
     'https://investment.infrastructure.gov.au/', NULL, false,
     'Funded project pipeline and the national infrastructure data catalogue. A strong '
     'input, but proximity alone never produces a buy — the factor carries its own note '
     'like every other.',
     false, 'UNKNOWN', NULL, NULL, NULL),

    ('REGISTERS_OF_INTERESTS', 'Parliamentary registers of interests',
     'Parliament of Victoria; Parliament of Australia', 'B_OPEN', NULL, NULL, false,
     'Published under the Members of Parliament (Standards) Act 1978 (Vic) and the '
     'federal equivalents, as bi-annual returns tabled and published. They disclose real '
     'property interests. They are published so the public can scrutinise the people in '
     'them — a purpose Crown is not pursuing. Aggregate signal only: the schema forbids '
     'naming an elected official in anything that leaves, and a secondary use of a public '
     'register needs its own basis checked with the register''s own body.',
     true, 'UNKNOWN', NULL, NULL, NULL)
ON CONFLICT (code) DO NOTHING;

COMMIT;
