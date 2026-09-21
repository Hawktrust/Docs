-- CROWN AI — MIGRATION 0007: holding data and using it are different questions
--
-- The survey in docs/DATA-SOURCE-SURVEY.md makes a distinction the register
-- could not express: a licence answers whether Crown may HOLD a source. It does
-- not answer whether Crown may USE it to contact a person. For the Titles
-- Register those have different answers — Victoria has previously varied
-- LANDATA licence conditions specifically to stop owner names and addresses
-- being used for marketing, and APP 7 governs direct marketing whether or not
-- the information was publicly available.
--
-- Left as prose, that distinction survives exactly as long as the person who
-- read it. So it becomes a column and a constraint.

BEGIN;

ALTER TABLE data_source
    ADD COLUMN carries_personal_information boolean NOT NULL DEFAULT false,
    ADD COLUMN privacy_basis text;

COMMENT ON COLUMN data_source.carries_personal_information IS
    'True where the source identifies living individuals — owner names, '
    'addresses, contact details. Such a source needs a lawful basis for the use '
    'Crown intends, not only a licence to hold it.';

COMMENT ON COLUMN data_source.privacy_basis IS
    'The stated basis for the intended use: which APP is relied on, the consent '
    'position, and where the suppression list lives. NULL means the question has '
    'not been answered, and the source cannot be ingested.';

-- A source that identifies people cannot be switched on until that basis is
-- written down. The licence check from 0001 is not enough for these.
ALTER TABLE data_source
    ADD CONSTRAINT personal_information_needs_a_basis
        CHECK (NOT is_ingestible
               OR NOT carries_personal_information
               OR privacy_basis IS NOT NULL);

-- Surface it alongside the register's other gaps.
DROP VIEW data_rights_exception;
CREATE VIEW data_rights_exception AS
    SELECT id, code, display_name, provider, lane, is_ingestible,
           licence_reference, attribution_text, notes,
           CASE
               WHEN carries_personal_information AND privacy_basis IS NULL
                   THEN 'ingestible and identifies people, with no stated basis for the intended use'
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
           OR (carries_personal_information AND privacy_basis IS NULL));

GRANT SELECT ON data_rights_exception TO crown_app;

COMMENT ON VIEW data_rights_exception IS
    'Sources being ingested without a complete data rights register entry. '
    'This should be empty before go-live.';

-- Whittlesea joined the scope on 2026-09-20. The register's note says which
-- LGAs Ticket 01 covers, and 0001 is already applied, so it is amended here
-- rather than edited in place.
UPDATE data_source
SET notes = replace(notes,
        'Ticket 01 covers Wyndham, Melton and Hume.',
        'Ticket 01 covers Wyndham, Melton and Hume; Whittlesea added 2026-09-20.')
WHERE code = 'VIC_PLANNING_AMENDMENTS';

COMMIT;
