-- Candidate sources beyond Ticket 01's single signal. See docs/DATA-SOURCE-SURVEY.md.
--
-- Adopted into the register on 2026-09-20. Being in the register is not
-- permission to ingest: every row below lands is_ingestible = false with
-- register_confirmed_by NULL, because the register's own rule is that a named
-- adviser confirms an entry first.
--
-- To sign one, and turn it on:
--
--     python scripts/confirm_source.py VICMAP_PROPERTY --adviser "Your Name"
--
-- That records who signed, when, and writes an audit row. Until then these
-- sources are documented and unusable, which is the correct state for a source
-- nobody has taken responsibility for.

INSERT INTO data_source (code, display_name, provider, lane, licence_reference,
                         attribution_text, is_ingestible, notes,
                         carries_personal_information, automated_access,
                         terms_reference, terms_read_by, terms_read_at)
VALUES
    ('VICMAP_PROPERTY',
     'Vicmap Property (cadastre)',
     'Department of Transport and Planning (Victoria)',
     'B_OPEN',
     'https://www.land.vic.gov.au/maps-and-spatial/spatial-data/how-to-access-spatial-data/licensing',
     'Contains information from the State Government of Victoria, licensed under Creative Commons Attribution.',
     false,
     'Parcel and property polygons, SPI, parcel area, Crown vs freehold, easements. '
     'Contains NO owner information — the cadastre and the Titles Register are separate systems.',
     false,
     'PERMITTED', 'https://www.land.vic.gov.au/maps-and-spatial/spatial-data/how-to-access-spatial-data/licensing', 'Crown AI review 2026-09-20', now()),

    ('VICMAP_PLANNING',
     'Vicmap Planning (zones and overlays)',
     'Department of Transport and Planning (Victoria)',
     'B_OPEN',
     'https://www.land.vic.gov.au/maps-and-spatial/spatial-data/how-to-access-spatial-data/licensing',
     'Contains information from the State Government of Victoria, licensed under Creative Commons Attribution.',
     false,
     'Zones and overlays for all 79 LGAs, Urban Growth Boundary and Growth Area. Updated weekly.',
     false,
     'PERMITTED', 'https://www.land.vic.gov.au/maps-and-spatial/spatial-data/how-to-access-spatial-data/licensing', 'Crown AI review 2026-09-20', now()),

    ('VPA_PSP',
     'Victorian Planning Authority precinct structure plans',
     'Victorian Planning Authority',
     'B_OPEN',
     'https://vpa.vic.gov.au/strategy-guidelines/open-data/',
     'Contains information from the Victorian Planning Authority.',
     false,
     'Greenfield PSP boundaries and approved PSP land use.',
     false,
     'PERMITTED', 'https://vpa.vic.gov.au/strategy-guidelines/open-data/', 'Crown AI review 2026-09-20', now()),

    ('VG_PROPERTY_SALES',
     'Valuer General property sales',
     'Valuer-General Victoria',
     'C_DERIVED_ONLY',
     NULL,
     NULL,
     false,
     'Sale prices and dates. Lane C until the licence is read: some Valuer General '
     'products carry restrictions on marketing use. Confirm before any use.',
     true,
     'UNKNOWN', NULL, NULL, NULL),

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
     'consent position and suppression list. Gate 0 work.',
     true,
     'UNKNOWN', NULL, NULL, NULL)
ON CONFLICT (code) DO NOTHING;
