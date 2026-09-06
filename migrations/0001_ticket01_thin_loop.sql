-- CROWN AI — SCHEMA FOR TICKET 01 (THE THIN LOOP)
-- Postgres 15+. Enforces the Constitution as database constraints, not conventions.
-- Scope: Lane B sources only. No parcel, owner, title or partner tables — those are Gate 0 work.

BEGIN;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- ENUMS  (Constitution §1, §2, §3)
-- ============================================================

CREATE TYPE data_lane         AS ENUM ('A_LICENSED', 'B_OPEN', 'C_DERIVED_ONLY', 'BLOCKED');
CREATE TYPE evidence_class    AS ENUM ('FACT', 'INFERENCE', 'HYPOTHESIS', 'PREDICTION', 'UNKNOWN');
CREATE TYPE reliability       AS ENUM ('AUTHORITATIVE', 'STRONG', 'MODERATE', 'WEAK', 'UNVERIFIED');
CREATE TYPE opportunity_stage AS ENUM ('WATCH', 'DEVELOPING', 'HIGH_CONFIDENCE', 'CONFIRMED');
CREATE TYPE approval_decision AS ENUM ('APPROVED', 'REJECTED');
CREATE TYPE data_origin       AS ENUM ('REAL', 'DEMO_SYNTHETIC');

-- ============================================================
-- USERS — a named human owns every opportunity and every approval
-- ============================================================

CREATE TABLE app_user (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email        text NOT NULL UNIQUE,
    display_name text NOT NULL,
    role         text NOT NULL CHECK (role IN ('ADMIN', 'ANALYST', 'AGENT', 'COMPLIANCE')),
    is_active    boolean NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- SOURCE REGISTRY  (Constitution §1 — the data rights register, enforced)
-- A source with no row here cannot be ingested from.
-- ============================================================

CREATE TABLE data_source (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code                  text NOT NULL UNIQUE,        -- e.g. 'VIC_PLANNING_AMENDMENTS'
    display_name          text NOT NULL,
    provider              text NOT NULL,
    lane                  data_lane NOT NULL,
    licence_reference     text,                        -- URL or agreement reference
    attribution_text      text,                        -- required for many Lane B sources
    register_confirmed_by text,                        -- NULL until a named adviser signs
    register_confirmed_at timestamptz,
    is_ingestible         boolean NOT NULL DEFAULT false,
    notes                 text,
    created_at            timestamptz NOT NULL DEFAULT now(),

    -- Only Lane A and Lane B may ever be ingested in bulk. Lane C stores
    -- derived values via a separate, narrower path; BLOCKED stores nothing.
    CONSTRAINT ingestible_lane_only
        CHECK (NOT is_ingestible OR lane IN ('A_LICENSED', 'B_OPEN')),

    -- Lane A requires a licence reference on file before it can be used.
    CONSTRAINT lane_a_needs_licence
        CHECK (lane <> 'A_LICENSED' OR licence_reference IS NOT NULL)
);

-- ============================================================
-- RAW PAYLOADS — immutable landing zone; this is what makes ingestion idempotent
-- ============================================================

CREATE TABLE raw_ingest (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id     uuid NOT NULL REFERENCES data_source(id),
    source_ref    text NOT NULL,        -- amendment number / stable upstream id
    content_hash  text NOT NULL,        -- sha256 of the normalised payload
    payload       jsonb NOT NULL,
    retrieved_at  timestamptz NOT NULL,
    retrieved_from text NOT NULL,       -- exact URL fetched
    created_at    timestamptz NOT NULL DEFAULT now(),

    -- Acceptance criterion 2: re-running ingestion produces zero duplicates.
    CONSTRAINT raw_ingest_idempotent UNIQUE (source_id, source_ref, content_hash)
);

-- ============================================================
-- EVIDENCE  (Constitution §2 — every provenance field is mandatory)
-- ============================================================

CREATE TABLE evidence_record (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_ingest_id     uuid REFERENCES raw_ingest(id),
    source_id         uuid NOT NULL REFERENCES data_source(id),

    -- provenance: all mandatory. Missing provenance is a validation failure,
    -- not a warning — a record that can't fill these goes to the review queue instead.
    source_reference  text NOT NULL,
    source_url        text NOT NULL,
    provider          text NOT NULL,
    retrieved_at      timestamptz NOT NULL,
    observed_at       timestamptz NOT NULL,   -- when the fact was true upstream
    last_verified_at  timestamptz NOT NULL,
    lane              data_lane NOT NULL,
    reliability       reliability NOT NULL,
    evidence_class    evidence_class NOT NULL,
    confidence        numeric(4,3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    reviewed_by       uuid REFERENCES app_user(id),
    contradicted_by   uuid REFERENCES evidence_record(id),

    origin            data_origin NOT NULL DEFAULT 'REAL',

    -- payload
    lga               text NOT NULL,
    title             text NOT NULL,
    summary           text,
    amendment_status  text,                   -- e.g. 'EXHIBITED', 'GAZETTED'
    geography         jsonb,                  -- suburb / precinct identifiers

    created_at        timestamptz NOT NULL DEFAULT now(),

    -- Model confidence never promotes a class: a FACT must rest on an
    -- authoritative or strong source, whatever confidence score a model gave it.
    CONSTRAINT fact_needs_strong_source
        CHECK (evidence_class <> 'FACT' OR reliability IN ('AUTHORITATIVE', 'STRONG')),

    CONSTRAINT unverified_cannot_be_fact
        CHECK (NOT (reliability = 'UNVERIFIED' AND evidence_class = 'FACT'))
);

CREATE INDEX evidence_lga_idx      ON evidence_record (lga);
CREATE INDEX evidence_class_idx    ON evidence_record (evidence_class);
CREATE INDEX evidence_observed_idx ON evidence_record (observed_at DESC);

-- Acceptance criterion 3: a record failing provenance validation goes here,
-- not into evidence_record.
CREATE TABLE evidence_review_queue (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_ingest_id     uuid REFERENCES raw_ingest(id),
    source_id         uuid NOT NULL REFERENCES data_source(id),
    attempted_payload jsonb NOT NULL,
    failure_reason    text NOT NULL,
    missing_fields    text[] NOT NULL DEFAULT '{}',
    resolved_at       timestamptz,
    resolved_by       uuid REFERENCES app_user(id),
    created_at        timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- OPPORTUNITY  (geographic only in Ticket 01 — no owners, no parcels)
-- ============================================================

CREATE TABLE opportunity (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lga             text NOT NULL,
    geography_label text NOT NULL,          -- suburb / precinct, not an address
    stage           opportunity_stage NOT NULL DEFAULT 'WATCH',
    stage_rule      text NOT NULL,          -- the rule that set the stage, human-readable
    owner_user_id   uuid NOT NULL REFERENCES app_user(id),   -- AC4: a named human owner
    next_action     text,
    next_action_due date,
    origin          data_origin NOT NULL DEFAULT 'REAL',
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE opportunity_evidence (
    opportunity_id uuid NOT NULL REFERENCES opportunity(id) ON DELETE CASCADE,
    evidence_id    uuid NOT NULL REFERENCES evidence_record(id),
    linked_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (opportunity_id, evidence_id)
);

-- ============================================================
-- BUYER MANDATES  (all synthetic in Ticket 01 — Constitution §6, no fabrication)
-- ============================================================

CREATE TABLE buyer_mandate (
    id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    buyer_label            text NOT NULL,
    origin                 data_origin NOT NULL,    -- no default: must be explicit every time
    geographies            text[] NOT NULL,
    asset_types            text[] NOT NULL,
    land_size_min_sqm      integer,
    land_size_max_sqm      integer,
    price_min_aud          bigint,
    price_max_aud          bigint,
    planning_risk_appetite text CHECK (planning_risk_appetite IN ('LOW','MEDIUM','HIGH')),
    relationship_strength  text CHECK (relationship_strength IN ('WEAK','MODERATE','STRONG')),
    mandate_date           date NOT NULL,
    is_active              boolean NOT NULL DEFAULT true,
    created_at             timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT sane_size  CHECK (land_size_max_sqm IS NULL OR land_size_min_sqm IS NULL
                                 OR land_size_max_sqm >= land_size_min_sqm),
    CONSTRAINT sane_price CHECK (price_max_aud IS NULL OR price_min_aud IS NULL
                                 OR price_max_aud >= price_min_aud)
);

-- Acceptance criterion 7: synthetic records are labelled and excluded from
-- any count shown to a human. Query real data through this view, never the
-- base table directly, when producing a figure for a person.
CREATE VIEW buyer_mandate_real AS
    SELECT * FROM buyer_mandate WHERE origin = 'REAL';

-- ============================================================
-- MATCHING  (AC5, AC6 — five transparent factors, weights in config, no LLM)
-- ============================================================

CREATE TABLE match_weight_config (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version           integer NOT NULL UNIQUE,
    geographic_fit    numeric(4,3) NOT NULL,
    asset_fit         numeric(4,3) NOT NULL,
    price_fit         numeric(4,3) NOT NULL,
    size_fit          numeric(4,3) NOT NULL,
    mandate_freshness numeric(4,3) NOT NULL,
    is_active         boolean NOT NULL DEFAULT false,
    created_at        timestamptz NOT NULL DEFAULT now()
);

-- exactly one active weight set at a time
CREATE UNIQUE INDEX one_active_weight_config
    ON match_weight_config (is_active) WHERE is_active;

CREATE TABLE match_result (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    opportunity_id        uuid NOT NULL REFERENCES opportunity(id) ON DELETE CASCADE,
    buyer_mandate_id      uuid NOT NULL REFERENCES buyer_mandate(id),
    weight_config_version integer NOT NULL REFERENCES match_weight_config(version),

    total_score           numeric(6,4) NOT NULL,
    -- per-factor contributions, shown in the UI (AC5)
    geographic_fit_score  numeric(6,4) NOT NULL,
    asset_fit_score       numeric(6,4) NOT NULL,
    price_fit_score       numeric(6,4) NOT NULL,
    size_fit_score        numeric(6,4) NOT NULL,
    freshness_score       numeric(6,4) NOT NULL,

    is_excluded           boolean NOT NULL DEFAULT false,
    why_not               text,                    -- required when excluded
    computed_at           timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT excluded_needs_reason
        CHECK (NOT is_excluded OR why_not IS NOT NULL),

    CONSTRAINT match_unique_per_config
        UNIQUE (opportunity_id, buyer_mandate_id, weight_config_version)
);

-- ============================================================
-- APPROVAL  (Constitution §4 — nothing consequential leaves without one)
-- ============================================================

CREATE TABLE approval (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    match_result_id uuid NOT NULL REFERENCES match_result(id),
    decision        approval_decision NOT NULL,
    reason          text NOT NULL,
    approver_id     uuid NOT NULL REFERENCES app_user(id),
    decided_at      timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- OUTBOUND  (AC8 — no export or outreach draft without an approval id)
-- ============================================================

CREATE TABLE outbound_artifact (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_id   uuid NOT NULL REFERENCES approval(id),   -- NOT NULL is the actual control
    artifact_type text NOT NULL CHECK (artifact_type IN ('EXPORT','OUTREACH_DRAFT','BUYER_BRIEF')),
    content       jsonb NOT NULL,
    created_by    uuid NOT NULL REFERENCES app_user(id),
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- ATTRIBUTION  (AC11 — trace any record back to the signal that started it)
-- ============================================================

CREATE TABLE attribution (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    opportunity_id           uuid NOT NULL REFERENCES opportunity(id),
    buyer_mandate_id         uuid NOT NULL REFERENCES buyer_mandate(id),
    approval_id              uuid NOT NULL REFERENCES approval(id),
    originating_evidence_id  uuid NOT NULL REFERENCES evidence_record(id),
    originating_source_url   text NOT NULL,
    originating_retrieved_at timestamptz NOT NULL,
    approver_id              uuid NOT NULL REFERENCES app_user(id),
    created_at               timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- AUDIT  (Constitution §5, AC10 — append-only, enforced by trigger not convention)
-- ============================================================

CREATE TABLE audit_event (
    id             bigserial PRIMARY KEY,
    actor_user_id  uuid REFERENCES app_user(id),
    actor_agent    text,
    action         text NOT NULL,
    object_table   text NOT NULL,
    object_id      text NOT NULL,
    previous_state jsonb,
    new_state      jsonb,
    evidence_id    uuid REFERENCES evidence_record(id),
    approval_id    uuid REFERENCES approval(id),
    correlation_id uuid NOT NULL,
    model          text,
    provider       text,
    occurred_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX audit_object_idx      ON audit_event (object_table, object_id);
CREATE INDEX audit_correlation_idx ON audit_event (correlation_id);
CREATE INDEX audit_time_idx        ON audit_event (occurred_at DESC);

CREATE OR REPLACE FUNCTION audit_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_event is append-only: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_no_update   BEFORE UPDATE   ON audit_event FOR EACH STATEMENT EXECUTE FUNCTION audit_append_only();
CREATE TRIGGER audit_no_delete   BEFORE DELETE   ON audit_event FOR EACH STATEMENT EXECUTE FUNCTION audit_append_only();
CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_event FOR EACH STATEMENT EXECUTE FUNCTION audit_append_only();

-- Attribution is a permanent record too — same discipline.
CREATE TRIGGER attribution_no_update BEFORE UPDATE ON attribution FOR EACH STATEMENT EXECUTE FUNCTION audit_append_only();
CREATE TRIGGER attribution_no_delete BEFORE DELETE ON attribution FOR EACH STATEMENT EXECUTE FUNCTION audit_append_only();

-- ============================================================
-- ROW-LEVEL SECURITY  (AC9 — server-side authorisation, not client-supplied headers)
-- Enable RLS now so policies are written against it from day one.
-- The application connects as a non-superuser role and must never bypass this.
-- ============================================================

ALTER TABLE opportunity       ENABLE ROW LEVEL SECURITY;
ALTER TABLE buyer_mandate     ENABLE ROW LEVEL SECURITY;
ALTER TABLE match_result      ENABLE ROW LEVEL SECURITY;
ALTER TABLE approval          ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbound_artifact ENABLE ROW LEVEL SECURITY;

-- Example policy shape. The role and user id come from a session variable set
-- server-side immediately after authentication — never from a client header.
CREATE POLICY opportunity_read ON opportunity FOR SELECT
    USING (
        current_setting('crown.user_role', true) IN ('ADMIN','ANALYST','COMPLIANCE')
        OR owner_user_id::text = current_setting('crown.user_id', true)
    );

CREATE POLICY approval_insert_compliance ON approval FOR INSERT
    WITH CHECK (current_setting('crown.user_role', true) IN ('ADMIN','COMPLIANCE'));

-- ============================================================
-- SEED — the only ingestible source in Ticket 01, and RP Data recorded as blocked
-- ============================================================

INSERT INTO data_source (code, display_name, provider, lane, licence_reference,
                         attribution_text, is_ingestible, notes)
VALUES (
    'VIC_PLANNING_AMENDMENTS',
    'Victorian planning scheme amendments',
    'State Government of Victoria',
    'B_OPEN',
    'https://www.planning.vic.gov.au/',
    'Contains information from the State Government of Victoria.',
    true,
    'Confirm exact reuse licence and attribution wording before go-live. Ticket 01 covers Wyndham, Melton and Hume.'
);

-- Deliberately registered as BLOCKED rather than omitted: the row documents
-- that the licence question is open, and stops any code path from treating
-- RP Data as ingestible until this row is updated by a signed agreement.
INSERT INTO data_source (code, display_name, provider, lane, is_ingestible, notes)
VALUES (
    'RP_DATA_SEAT',
    'RP Data / CoreLogic (seat subscription)',
    'CoreLogic (Cotality)',
    'BLOCKED',
    false,
    'Seat subscription only — no platform/API agreement on file. Do not ingest, cache or redistribute.'
);

COMMIT;
