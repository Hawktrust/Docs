-- CROWN AI — MIGRATION 0010: the land layer
--
-- Ticket 01 said "no parcel-level or owner-level resolution", and was right to:
-- owner resolution is Gate 0. But the two were bundled together, and they are
-- different problems. Owners are licensed and privacy-bound. Parcels are open:
-- Vicmap Property is Creative Commons, carries no personal information, and
-- gives boundary, area, identifier and Crown-versus-freehold for every parcel
-- in Victoria.
--
-- This is the layer that answers "land in Whittlesea between 20 and 150 acres,
-- with zoning and overlays" without touching anything licensed. It is Ticket 02
-- scope, built ahead of the data so the day Vicmap loads the query already works.
--
-- No PostGIS on this cluster, so boundaries are kept as GeoJSON and proximity
-- is centroid distance via earthdistance. Adjacency proper — parcels that touch
-- — needs PostGIS and is marked where it matters.

BEGIN;

CREATE EXTENSION IF NOT EXISTS cube;
CREATE EXTENSION IF NOT EXISTS earthdistance;

-- 20 acres and 150 acres are 80,937 and 606,000 square metres. Storing metres
-- and converting at the edge keeps one unit in the database.
CREATE OR REPLACE FUNCTION acres_to_sqm(acres numeric) RETURNS numeric AS $$
    SELECT acres * 4046.8564224;
$$ LANGUAGE sql IMMUTABLE;

CREATE OR REPLACE FUNCTION sqm_to_acres(sqm numeric) RETURNS numeric AS $$
    SELECT sqm / 4046.8564224;
$$ LANGUAGE sql IMMUTABLE;

-- ============================================================
-- PARCELS — the cadastre. No owner, by design and by source.
-- ============================================================

CREATE TABLE parcel (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    spi             text NOT NULL UNIQUE,   -- standard parcel identifier
    lga             text NOT NULL,
    locality        text,                   -- suburb, where the source gives one
    area_sqm        numeric(14,2) NOT NULL CHECK (area_sqm > 0),
    is_crown_land   boolean,
    centroid_lat    double precision,
    centroid_lon    double precision,
    boundary        jsonb,                  -- GeoJSON, pending PostGIS

    -- Parcels carry the same provenance discipline as evidence. A parcel whose
    -- origin nobody can state is not usable for a recommendation either.
    source_id       uuid NOT NULL REFERENCES data_source(id),
    retrieved_at    timestamptz NOT NULL,
    retrieval_method text NOT NULL DEFAULT 'DIRECT_FETCH'
        CHECK (retrieval_method IN ('DIRECT_FETCH','OPERATOR_CAPTURE','MANUAL_ENTRY')),
    origin          data_origin NOT NULL DEFAULT 'REAL',
    created_at      timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT centroid_is_complete_or_absent
        CHECK ((centroid_lat IS NULL) = (centroid_lon IS NULL)),
    CONSTRAINT centroid_is_on_earth
        CHECK (centroid_lat IS NULL
               OR (centroid_lat BETWEEN -90 AND 90 AND centroid_lon BETWEEN -180 AND 180))
);

CREATE INDEX parcel_lga_idx      ON parcel (lga);
CREATE INDEX parcel_locality_idx ON parcel (locality);
CREATE INDEX parcel_area_idx     ON parcel (area_sqm);
CREATE INDEX parcel_origin_idx   ON parcel (origin);
-- proximity: "what else is near this parcel"
CREATE INDEX parcel_position_idx ON parcel
    USING gist (ll_to_earth(centroid_lat, centroid_lon))
    WHERE centroid_lat IS NOT NULL;

-- ============================================================
-- PLANNING — zone and overlays, as at a date.
--
-- Zoning changes, and the change is the signal Crown trades on. So this is
-- history, not a column on the parcel: a row per observation, and the current
-- picture is the latest one.
-- ============================================================

CREATE TABLE parcel_planning (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    parcel_id    uuid NOT NULL REFERENCES parcel(id) ON DELETE CASCADE,
    zone_code    text NOT NULL,            -- e.g. 'UGZ', 'FZ', 'GRZ1'
    zone_name    text,
    overlay_codes text[] NOT NULL DEFAULT '{}',   -- e.g. {'DCPO3','BMO','LSIO'}
    psp_name     text,                     -- precinct structure plan, where inside one
    psp_status   text CHECK (psp_status IN ('APPROVED','DRAFT','UNDER_INVESTIGATION','NONE')),
    as_at        date NOT NULL,
    source_id    uuid NOT NULL REFERENCES data_source(id),
    retrieved_at timestamptz NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT one_observation_per_parcel_per_day UNIQUE (parcel_id, as_at)
);

CREATE INDEX parcel_planning_current_idx ON parcel_planning (parcel_id, as_at DESC);
CREATE INDEX parcel_planning_zone_idx    ON parcel_planning (zone_code);
CREATE INDEX parcel_planning_psp_idx     ON parcel_planning (psp_status);
CREATE INDEX parcel_planning_overlay_idx ON parcel_planning USING gin (overlay_codes);

CREATE VIEW parcel_planning_current AS
    SELECT DISTINCT ON (parcel_id) *
    FROM parcel_planning ORDER BY parcel_id, as_at DESC;

-- ============================================================
-- DWELLING — deliberately its own table, because it has no source yet.
--
-- "With or without a house" was specified as a search filter. Vicmap Property
-- does not carry it. Modelling it as a boolean on parcel would make every
-- parcel read "no dwelling" the moment the table was created, which is a lie
-- with a default value. A separate table means absent stays absent: a parcel
-- with no row here has unknown dwelling status, and the search says so.
-- ============================================================

CREATE TABLE parcel_dwelling (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    parcel_id    uuid NOT NULL REFERENCES parcel(id) ON DELETE CASCADE,
    has_dwelling boolean NOT NULL,
    dwelling_count integer CHECK (dwelling_count IS NULL OR dwelling_count >= 0),
    observed_at  date NOT NULL,
    source_id    uuid NOT NULL REFERENCES data_source(id),
    method       text NOT NULL CHECK (method IN
                    ('BUILDING_PERMIT','RATES_RECORD','IMAGERY','SITE_VISIT','LISTING')),
    notes        text,
    created_at   timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT one_dwelling_observation_per_day UNIQUE (parcel_id, observed_at)
);

CREATE INDEX parcel_dwelling_current_idx ON parcel_dwelling (parcel_id, observed_at DESC);

CREATE VIEW parcel_dwelling_current AS
    SELECT DISTINCT ON (parcel_id) *
    FROM parcel_dwelling ORDER BY parcel_id, observed_at DESC;

-- ============================================================
-- Parcels under an opportunity. Still no owners: this says which land a
-- geographic opportunity covers, not who holds it.
-- ============================================================

CREATE TABLE opportunity_parcel (
    opportunity_id uuid NOT NULL REFERENCES opportunity(id) ON DELETE CASCADE,
    parcel_id      uuid NOT NULL REFERENCES parcel(id),
    linked_at      timestamptz NOT NULL DEFAULT now(),
    linked_by      uuid REFERENCES app_user(id),
    PRIMARY KEY (opportunity_id, parcel_id)
);

-- ============================================================
-- Only real parcels are counted for a person, same rule as everywhere else.
-- ============================================================

CREATE VIEW parcel_real AS SELECT * FROM parcel WHERE origin = 'REAL';
ALTER VIEW parcel_real SET (security_invoker = true);

GRANT SELECT, INSERT, UPDATE ON parcel, parcel_planning, parcel_dwelling,
      opportunity_parcel TO crown_app;
GRANT SELECT ON parcel_planning_current, parcel_dwelling_current, parcel_real
      TO crown_app;

ALTER TABLE parcel ENABLE ROW LEVEL SECURITY;
ALTER TABLE parcel FORCE ROW LEVEL SECURITY;
CREATE POLICY parcel_read ON parcel FOR SELECT
    USING (crown_role() IN ('ADMIN','ANALYST','AGENT','COMPLIANCE'));
CREATE POLICY parcel_write ON parcel FOR INSERT
    WITH CHECK (crown_role() IN ('ADMIN','ANALYST'));

COMMENT ON TABLE parcel IS
    'The cadastre. Contains no owner information, because the source does not: '
    'Vicmap Property and the Titles Register are separate systems and the bridge '
    'between them is licensed. See docs/DATA-SOURCE-SURVEY.md.';

COMMIT;
