-- CROWN AI — MIGRATION 0012: watchlists, alerts and the investment brief
--
-- The vision specifies a daily shortlist, a weekly investment brief, watchlist
-- alerts and stale-data alerts, with duplicates and low-confidence alerts
-- suppressed. This is the schema for that.
--
-- Two decisions worth stating.
--
-- Deduplication is a database constraint rather than application logic, because
-- "we already told you that" is the difference between a product people read
-- and one they filter to a folder. Every alert computes a dedupe key from what
-- it is about, and the same key cannot be raised twice.
--
-- Confidence is derived from the evidence, exactly as it is for a
-- recommendation. An alert that cannot say how strongly it is founded is
-- suppressed rather than sent, and the suppression is recorded so nobody has to
-- wonder whether the system missed something or chose not to speak.

BEGIN;

CREATE TYPE watch_kind AS ENUM
    ('LGA', 'SUBURB', 'PARCEL', 'ACTOR', 'BUYER_MANDATE', 'SAVED_SEARCH');

CREATE TABLE watchlist (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    uuid NOT NULL REFERENCES app_user(id),
    kind       watch_kind NOT NULL,
    target     text NOT NULL,              -- the LGA name, suburb, parcel id, actor id
    label      text NOT NULL,
    parameters jsonb,                      -- a saved search's filters
    is_active  boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT one_watch_per_target UNIQUE (user_id, kind, target)
);

CREATE INDEX watchlist_active_idx ON watchlist (user_id) WHERE is_active;
CREATE INDEX watchlist_target_idx ON watchlist (kind, target) WHERE is_active;

CREATE TYPE alert_kind AS ENUM (
    'NEW_EVIDENCE',              -- an amendment touching a watched geography
    'MARKET_SIGNAL',             -- a developer, fund or government move
    'STAGE_CHANGE',              -- an opportunity restaged
    'GOVERNMENT_ACQUISITION',    -- a PAO appearing on watched land
    'ADJOINING_ACTIVITY',        -- something happening next door
    'STALE_EVIDENCE',            -- a record that needs re-verifying
    'DATA_RIGHTS_EXCEPTION');    -- a source in use without a complete entry

CREATE TYPE alert_confidence AS ENUM ('CONFIRMED', 'PROBABLE', 'SPECULATIVE');

CREATE TABLE alert (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind          alert_kind NOT NULL,
    watchlist_id  uuid REFERENCES watchlist(id) ON DELETE SET NULL,
    user_id       uuid REFERENCES app_user(id),

    -- what it is about
    lga           text,
    locality      text,
    parcel_id     uuid REFERENCES parcel(id),
    acres         numeric(12,2),
    zone_code     text,
    overlay_codes text[] NOT NULL DEFAULT '{}',

    -- what happened, and how we know
    detected_event text NOT NULL,
    source_url    text NOT NULL,
    evidence_id   uuid REFERENCES evidence_record(id),
    signal_id     uuid REFERENCES actor_signal(id),
    confidence    alert_confidence NOT NULL,

    -- what it means and what to do
    investment_impact text NOT NULL,
    recommended_action text NOT NULL,

    -- "we already told you that" is the difference between a product people
    -- read and one they filter to a folder
    dedupe_key    text NOT NULL UNIQUE,

    suppressed_reason text,
    delivered_at  timestamptz,
    read_at       timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT a_suppressed_alert_is_not_delivered
        CHECK (suppressed_reason IS NULL OR delivered_at IS NULL)
);

CREATE INDEX alert_undelivered_idx ON alert (created_at DESC)
    WHERE delivered_at IS NULL AND suppressed_reason IS NULL;
CREATE INDEX alert_user_idx ON alert (user_id, created_at DESC);
CREATE INDEX alert_place_idx ON alert (lga, locality);

GRANT SELECT, INSERT, UPDATE ON watchlist, alert TO crown_app;

ALTER TABLE alert ENABLE ROW LEVEL SECURITY;
ALTER TABLE alert FORCE ROW LEVEL SECURITY;
CREATE POLICY alert_read ON alert FOR SELECT
    USING (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE'));
CREATE POLICY alert_write ON alert FOR INSERT
    WITH CHECK (crown_role() IN ('ADMIN','ANALYST'));
CREATE POLICY alert_update ON alert FOR UPDATE
    USING (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE'));

ALTER TABLE watchlist ENABLE ROW LEVEL SECURITY;
ALTER TABLE watchlist FORCE ROW LEVEL SECURITY;
CREATE POLICY watchlist_own ON watchlist FOR SELECT
    USING (crown_role() IN ('ADMIN','COMPLIANCE')
           OR user_id::text = crown_user_id());
CREATE POLICY watchlist_insert ON watchlist FOR INSERT
    WITH CHECK (user_id::text = crown_user_id()
                OR crown_role() = 'ADMIN');
CREATE POLICY watchlist_update ON watchlist FOR UPDATE
    USING (user_id::text = crown_user_id() OR crown_role() = 'ADMIN');

-- ============================================================
-- STALE EVIDENCE — a record nobody has re-checked.
--
-- The Constitution requires last_verified_at on every record. This is what
-- makes that column do something: evidence past its shelf life raises an alert
-- rather than quietly continuing to support a recommendation.
--
-- Different classes go stale at different speeds. A gazetted amendment is
-- settled and rarely changes; an exhibited one is moving, and a relayed claim
-- was never verified in the first place.
-- ============================================================

CREATE VIEW stale_evidence AS
    SELECT e.id, e.source_reference, e.lga, e.title, e.evidence_class,
           e.reliability, e.retrieval_method, e.last_verified_at, e.source_url,
           CASE e.retrieval_method
               WHEN 'SEARCH_RELAY' THEN 30
               WHEN 'MANUAL_ENTRY' THEN 90
               ELSE CASE e.evidence_class
                        WHEN 'FACT' THEN 365
                        WHEN 'HYPOTHESIS' THEN 90
                        ELSE 60
                    END
           END AS shelf_life_days,
           (now()::date - e.last_verified_at::date) AS days_since_verified
    FROM evidence_record e
    WHERE e.origin = 'REAL'
      AND (now()::date - e.last_verified_at::date) >
          CASE e.retrieval_method
              WHEN 'SEARCH_RELAY' THEN 30
              WHEN 'MANUAL_ENTRY' THEN 90
              ELSE CASE e.evidence_class
                       WHEN 'FACT' THEN 365
                       WHEN 'HYPOTHESIS' THEN 90
                       ELSE 60
                   END
          END;

ALTER VIEW stale_evidence SET (security_invoker = true);
GRANT SELECT ON stale_evidence TO crown_app;

COMMENT ON VIEW stale_evidence IS
    'Evidence past its shelf life. Relayed claims go stale in 30 days because '
    'they were never verified; a gazetted fact lasts a year because it is '
    'settled. This is what makes last_verified_at more than a column.';

COMMIT;
