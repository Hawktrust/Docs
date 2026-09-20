-- PROPOSED, NOT APPLIED. See docs/DATA-SOURCE-SURVEY.md.
--
-- Adding a source to the register is a scoping decision, not a code change, so
-- this file is deliberately outside the seed set that migrations and tests run.
-- Apply it when someone has decided to widen beyond Ticket 01's single source.
--
-- Note that every row below lands with is_ingestible = false. The register's own
-- rule is that a named adviser confirms an entry before anything is ingested
-- from it, and none of these has been confirmed. Set is_ingestible = true and
-- fill register_confirmed_by in the same statement, deliberately, per source.

INSERT INTO data_source (code, display_name, provider, lane, licence_reference,
                         attribution_text, is_ingestible, notes)
VALUES
    ('VICMAP_PROPERTY',
     'Vicmap Property (cadastre)',
     'Department of Transport and Planning (Victoria)',
     'B_OPEN',
     'https://www.land.vic.gov.au/maps-and-spatial/spatial-data/how-to-access-spatial-data/licensing',
     'Contains information from the State Government of Victoria, licensed under Creative Commons Attribution.',
     false,
     'Parcel and property polygons, SPI, parcel area, Crown vs freehold, easements. '
     'Contains NO owner information — the cadastre and the Titles Register are separate systems.'),

    ('VICMAP_PLANNING',
     'Vicmap Planning (zones and overlays)',
     'Department of Transport and Planning (Victoria)',
     'B_OPEN',
     'https://www.land.vic.gov.au/maps-and-spatial/spatial-data/how-to-access-spatial-data/licensing',
     'Contains information from the State Government of Victoria, licensed under Creative Commons Attribution.',
     false,
     'Zones and overlays for all 79 LGAs, Urban Growth Boundary and Growth Area. Updated weekly.'),

    ('VPA_PSP',
     'Victorian Planning Authority precinct structure plans',
     'Victorian Planning Authority',
     'B_OPEN',
     'https://vpa.vic.gov.au/strategy-guidelines/open-data/',
     'Contains information from the Victorian Planning Authority.',
     false,
     'Greenfield PSP boundaries and approved PSP land use.'),

    ('VG_PROPERTY_SALES',
     'Valuer General property sales',
     'Valuer-General Victoria',
     'C_DERIVED_ONLY',
     NULL,
     NULL,
     false,
     'Sale prices and dates. Lane C until the licence is read: some Valuer General '
     'products carry restrictions on marketing use. Confirm before any use.'),

    ('LANDATA_TITLES',
     'Landata / Victorian Titles Register',
     'Land Use Victoria (LANDATA, operated by SERV)',
     'A_LICENSED',
     'https://www.landata.online/title-search/',
     'Contains information from the Victorian Titles Register.',
     false,
     'The only lawful route to a registered proprietor. Per-search; a Proprietor Name '
     'Search is available only through Information Brokers; bulk extraction is a '
     'separate commercial arrangement. Holding a licence settles whether Crown may '
     'HOLD this data. It does not settle whether Crown may USE it to contact anyone — '
     'that is APP 7 plus any register-specific restriction, and needs its own basis, '
     'consent position and suppression list. Gate 0 work.')
ON CONFLICT (code) DO NOTHING;
