-- CROWN AI — MIGRATION 0009: may we fetch this automatically?
--
-- The register answers who owns a source, what lane it is in, and whether a
-- named adviser signed it off. It has never answered the question that decides
-- whether a crawler may run: do this publisher's terms permit automated access
-- at all?
--
-- For most of what Crown wants, the answer is no. Google's terms prohibit
-- "the sending of automated queries of any sort to our system without express
-- permission" and access "through the use of any automated means (such as
-- robots, spiders or scrapers)". Meta prohibits automated collection. The major
-- property portals prohibit scraping. Cotality prohibits systematic retrieval.
--
-- Separately, the OAIC and eleven other regulators have stated that publicly
-- accessible personal information remains subject to privacy law, and that
-- scraping incidents can be notifiable data breaches. "It was public" is not a
-- defence in Australia.
--
-- So the position per source becomes a column, set deliberately, and the
-- automated fetch path refuses a source that does not permit it.

BEGIN;

CREATE TYPE automated_access AS ENUM (
    'PERMITTED',        -- terms allow it, or a written permission is on file
    'PUBLISHER_FEED',   -- the publisher offers a feed or API for exactly this
    'PROHIBITED',       -- terms forbid automated access
    'UNKNOWN'           -- nobody has read the terms yet
);

ALTER TABLE data_source
    ADD COLUMN automated_access automated_access NOT NULL DEFAULT 'UNKNOWN',
    ADD COLUMN terms_reference text,
    ADD COLUMN terms_read_by text,
    ADD COLUMN terms_read_at timestamptz;

COMMENT ON COLUMN data_source.automated_access IS
    'Whether this publisher''s terms permit automated retrieval. UNKNOWN is the '
    'honest default and blocks the crawler; it does not block a human opening '
    'the page in a browser, which is ordinary permitted use.';

-- Reading the terms is an act with a name attached to it, like signing the
-- register entry.
ALTER TABLE data_source
    ADD CONSTRAINT a_position_on_terms_is_attributed
        CHECK (automated_access = 'UNKNOWN'
               OR (terms_reference IS NOT NULL AND terms_read_by IS NOT NULL));

-- The position Crown already holds on its existing sources.
UPDATE data_source SET
    automated_access = 'PERMITTED',
    terms_reference = 'https://www.land.vic.gov.au/maps-and-spatial/spatial-data/how-to-access-spatial-data/licensing',
    terms_read_by = 'Crown AI review 2026-09-20',
    terms_read_at = now()
WHERE code = 'VIC_PLANNING_AMENDMENTS';
-- The Vicmap and VPA rows arrive in seeds/003, which runs after every migration,
-- so their position is set there rather than here where they do not yet exist.

UPDATE data_source SET
    automated_access = 'PROHIBITED',
    terms_reference = 'https://www.corelogic.com.au/legals/end-user-terms — systematic retrieval to compile a database is prohibited without written permission, and the licensed material must not be used to carry out or facilitate a search by purchaser or vendor name',
    terms_read_by = 'Crown AI review 2026-09-20',
    terms_read_at = now()
WHERE code = 'RP_DATA_SEAT';

-- ============================================================
-- Sources Crown asked about. Registered with the position their terms take,
-- so the answer is on file rather than relitigated every time someone asks.
-- All are is_ingestible = false; several could never be otherwise.
-- ============================================================

INSERT INTO data_source (code, display_name, provider, lane, licence_reference,
                         attribution_text, is_ingestible, notes,
                         carries_personal_information, automated_access,
                         terms_reference, terms_read_by, terms_read_at)
VALUES
    ('GOOGLE_SEARCH',
     'Google Search results',
     'Google LLC',
     'BLOCKED',
     NULL, NULL, false,
     'Terms prohibit sending automated queries of any sort without express permission, '
     'and access by automated means including robots, spiders and scrapers. Google has '
     'litigated against SERP scraping services. The Custom Search JSON API is closed to '
     'new customers and retires 2027-01-01. For a fixed set of nominated domains — the '
     'seven councils, DTP, VPA, the gazette — Vertex AI Search is the supported route '
     'and covers up to 50 domains, which is the shape Crown actually needs.',
     false, 'PROHIBITED',
     'https://policies.google.com/terms — no automated queries without express permission',
     'Crown AI review 2026-09-20', now()),

    ('SOCIAL_MARKETPLACE',
     'Social media marketplaces (Meta Marketplace and similar)',
     'Meta Platforms and others',
     'BLOCKED',
     NULL, NULL, false,
     'Automated collection is prohibited by platform terms and actively litigated. '
     'Listings by private sellers are personal information: the OAIC and eleven other '
     'regulators have stated that publicly accessible personal information remains '
     'subject to privacy law and that scraping can constitute a notifiable data breach. '
     'Public accessibility is not consent and is not a defence.',
     true, 'PROHIBITED',
     'Platform terms prohibit automated collection; OAIC joint statement on data scraping, August 2023',
     'Crown AI review 2026-09-20', now()),

    ('PROPERTY_PORTALS',
     'Residential property portals',
     'Various portal operators',
     'BLOCKED',
     NULL, NULL, false,
     'On-market listings are obtainable, but portal terms prohibit scraping and operators '
     'enforce it. The route is a commercial feed or partner agreement per portal, which '
     'makes each one its own Lane A entry rather than a crawler target.',
     true, 'PROHIBITED',
     'Portal terms of use — per operator, to be referenced individually when an agreement is sought',
     'Crown AI review 2026-09-20', now()),

    ('CROWN_INBOX',
     'Off-market approaches received by Crown',
     'Crown Capital & Development (first party)',
     'B_OPEN',
     'Crown''s own correspondence',
     NULL, false,
     'The off-market listings Crown wants are already arriving: agents email them. This is '
     'first-party correspondence Crown lawfully holds, which no competitor can copy because '
     'it is Crown''s relationships. Ingested with the sender, the message id and the date as '
     'provenance, an emailed approach is evidence like any other — and it is the only '
     'lawful source of off-market status that exists. Needs a privacy basis before any '
     'contact detail inside it is used for outreach, which is why it is flagged.',
     true, 'PERMITTED',
     'Crown''s own mailbox; no third-party terms apply to reading correspondence addressed to Crown',
     'Crown AI review 2026-09-20', now())
ON CONFLICT (code) DO NOTHING;

-- Surface an ingestible source whose terms forbid the crawler, or whose terms
-- nobody has read.
DROP VIEW data_rights_exception;
CREATE VIEW data_rights_exception AS
    SELECT id, code, display_name, provider, lane, is_ingestible,
           licence_reference, attribution_text, notes,
           CASE
               WHEN carries_personal_information AND privacy_basis IS NULL
                   THEN 'ingestible and identifies people, with no stated basis for the intended use'
               WHEN automated_access = 'PROHIBITED'
                   THEN 'ingestible, but the publisher''s terms prohibit automated access'
               WHEN automated_access = 'UNKNOWN'
                   THEN 'ingestible, but nobody has read the publisher''s terms'
               WHEN register_confirmed_by IS NULL
                   THEN 'ingestible, but no named adviser has confirmed the register entry'
               WHEN licence_reference IS NULL
                   THEN 'ingestible, but no licence reference is on file'
               WHEN attribution_text IS NULL
                   THEN 'ingestible, but no attribution wording is on file'
           END AS exception_reason
    FROM data_source
    WHERE is_ingestible
      AND (register_confirmed_by IS NULL
           OR licence_reference IS NULL
           OR attribution_text IS NULL
           OR automated_access IN ('PROHIBITED', 'UNKNOWN')
           OR (carries_personal_information AND privacy_basis IS NULL));

GRANT SELECT ON data_rights_exception TO crown_app;

COMMIT;
