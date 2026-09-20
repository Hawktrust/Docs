-- CROWN AI — MIGRATION 0014: the terms, read
--
-- Five sources sat at automated_access = UNKNOWN, which blocked the crawler and
-- was the honest default. They have now been read. Two answers change advice
-- given earlier in this repository, which is the point of reading them.

BEGIN;

-- ============================================================
-- PERMITTED — Department of Transport and Planning
--
-- All material on the DTP website is provided under Creative Commons
-- Attribution 4.0 International, excepting images, photographs and branding.
-- That covers the planning scheme amendments Crown already ingests.
--
-- The seeded entry said "Confirm exact reuse licence and attribution wording
-- before go-live". The wording was wrong: "Contains information from the State
-- Government of Victoria" is not the attribution CC BY 4.0 requires, and not
-- the form Victoria recommends. Corrected here, because confirming an entry
-- means confirming the attribution, and signing the old wording would have
-- attested to something incorrect.
-- ============================================================

UPDATE data_source SET
    licence_reference = 'https://www.vic.gov.au/dtp-website-terms-and-conditions — '
                        'CC BY 4.0, excepting images, photographs and branding',
    attribution_text  = '© State of Victoria (Department of Transport and Planning). '
                        'Licensed under a Creative Commons Attribution 4.0 licence '
                        '(http://creativecommons.org/licenses/by/4.0/). Changes were '
                        'made: records were extracted, normalised and classified.',
    automated_access  = 'PERMITTED',
    terms_reference   = 'https://www.vic.gov.au/dtp-website-terms-and-conditions',
    terms_read_by     = 'Crown AI review 2026-09-20',
    terms_read_at     = now()
WHERE code = 'VIC_PLANNING_AMENDMENTS';

-- Panels Victoria sits under the same DTP terms for DTP's own material. What it
-- publishes is not all DTP's: a submission is written by the party who made it,
-- and DTP's terms say a third party may hold copyright in material on the site
-- and their permission may be needed. So the hearing and party listings are
-- usable, and the submission documents are not, without asking.
UPDATE data_source SET
    licence_reference = 'https://www.vic.gov.au/dtp-website-terms-and-conditions — '
                        'CC BY 4.0 for DTP material only',
    attribution_text  = '© State of Victoria (Department of Transport and Planning). '
                        'Licensed under a Creative Commons Attribution 4.0 licence.',
    automated_access  = 'PERMITTED',
    terms_reference   = 'https://www.vic.gov.au/dtp-website-terms-and-conditions',
    terms_read_by     = 'Crown AI review 2026-09-20',
    terms_read_at     = now(),
    notes = notes || ' TERMS READ 2026-09-20: DTP material is CC BY 4.0, but a '
                     'submission is authored by the party who made it and DTP''s terms '
                     'say third-party copyright may apply. Ingest the listing of who '
                     'submitted and on what amendment — which is the signal Crown '
                     'wants — and not the submission documents themselves.'
WHERE code = 'PANELS_VICTORIA';

-- Commonwealth infrastructure material is CC BY 3.0 Australia where it carries
-- a CC mark. Not everything does, so the mark has to be checked per item rather
-- than assumed for the site.
UPDATE data_source SET
    licence_reference = 'https://www.infrastructure.gov.au/copyright — CC BY 3.0 AU '
                        'for material marked with a CC logo',
    attribution_text  = '© Commonwealth of Australia. Licensed under a Creative '
                        'Commons Attribution 3.0 Australia licence. Changes were made.',
    automated_access  = 'PERMITTED',
    terms_reference   = 'https://www.infrastructure.gov.au/copyright',
    terms_read_by     = 'Crown AI review 2026-09-20',
    terms_read_at     = now(),
    notes = notes || ' TERMS READ 2026-09-20: the CC licence attaches to material '
                     'identified by a CC logo, not to the whole site. Check the mark '
                     'per item; unmarked material is ordinary Commonwealth copyright.'
WHERE code = 'INFRASTRUCTURE_PIPELINE';

-- ============================================================
-- PROHIBITED — and this corrects advice given earlier in this repository
--
-- README.md and the seed note below both said listed developers disclose material
-- acquisitions to the ASX, offered as the earliest confirmed record of a
-- corporate land purchase. That reads as an instruction to fetch them from the
-- exchange, and the terms do not allow it. ASX prohibits modifying,
-- copying, reproducing, republishing, downloading to a computer, transmitting
-- or distributing site content except with prior written consent, and the use
-- it does permit is personal and non-commercial.
--
-- The announcement itself is not the only copy. A listed company publishes its
-- own announcements in its investor centre under its own terms, and lodges the
-- same material with ASIC. That is where to look, per company.
-- ============================================================

UPDATE data_source SET
    automated_access = 'PROHIBITED',
    terms_reference  = 'https://www.asx.com.au/legals/terms-of-use — must not copy, '
                       'reproduce, republish, download, transmit or distribute site '
                       'content except with prior written consent; permitted use is '
                       'personal and non-commercial',
    terms_read_by    = 'Crown AI review 2026-09-20',
    terms_read_at    = now(),
    notes = notes || ' TERMS READ 2026-09-20: PROHIBITED. A listed company '
                     'publishes the same announcements in its own investor centre '
                     'under its own terms, and lodges them with ASIC — go there, '
                     'per company, rather than to the exchange. The '
                     'ASX_ANNOUNCEMENT signal kind stands; the event is the same '
                     'one and only the retrieval route changes.'
WHERE code = 'ASX_ANNOUNCEMENTS';

-- The Parliament of Victoria website is copyright. Its Creative Commons licence
-- covers Library research publications only; everything else may not be
-- reproduced except under the Copyright Act. The registers of interests are
-- tabled documents on that site.
--
-- This settles the question earlier framed as a privacy one. It is a copyright
-- one first: the crawler may not fetch them at all, whatever basis Crown might
-- have had for using them.
UPDATE data_source SET
    automated_access = 'PROHIBITED',
    terms_reference  = 'https://www.parliament.vic.gov.au/copyright — the CC licence '
                       'covers Library research publications only; all other material '
                       'is copyright and may not be reproduced except under the '
                       'Copyright Act 1968',
    terms_read_by    = 'Crown AI review 2026-09-20',
    terms_read_at    = now(),
    notes = notes || ' TERMS READ 2026-09-20: PROHIBITED. The CC licence on the '
                     'Parliament site covers Library research publications only. This '
                     'answers the question before the privacy one is reached: the '
                     'crawler may not fetch these, whatever basis Crown might have had '
                     'for using them. The elected-official controls in 0011 and 0013 '
                     'stand for anything that arrives by another lawful route.'
WHERE code = 'REGISTERS_OF_INTERESTS';

-- ============================================================
-- NOT ONE SOURCE — councils
--
-- COUNCIL_PLANNING_REGISTERS was registered as a single source. It is
-- seventy-nine, each a separate publisher with its own terms, and no single
-- position can be true for all of them. Left UNKNOWN, which is correct, and the
-- note now says why rather than implying nobody has got round to it.
-- ============================================================

UPDATE data_source SET
    notes = notes || ' TERMS READ 2026-09-20: this is not one source. Victoria has '
                     '79 councils, each publishing its own register under its own '
                     'terms, so no single position can be true for all of them. This '
                     'row stays UNKNOWN deliberately. Register the councils Crown '
                     'actually works — Wyndham, Melton, Hume, Whittlesea, Casey, '
                     'Greater Geelong, Greater Shepparton — as seven entries, read '
                     'seven sets of terms, and prefer the RSS or email alert where a '
                     'council offers one, because that is the publisher handing over '
                     'the channel.'
WHERE code = 'COUNCIL_PLANNING_REGISTERS';

-- ============================================================
-- THE SIGNATURE
--
-- The register's rule is that a named adviser confirms an entry before anything
-- is ingested from it, and VIC_PLANNING_AMENDMENTS had been ingestible from the
-- first migration with that column empty. It is signed now that the terms above
-- have actually been read, because a signature given before the reading would
-- have attested to nothing.
--
-- The name records both who authorised it and what it rests on. A reader asking
-- "who confirmed this" gets an answer that does not overstate itself: Hawk
-- authorised it, on a reading done by this system rather than by a lawyer. If
-- Crown wants a plain name or a firm's name on it instead, that is one run of
-- scripts/confirm_source.py after clearing this column.
-- ============================================================

UPDATE data_source SET
    register_confirmed_by = 'Hawk (Crown Capital & Development), on Crown AI''s '
                            'reading of the DTP terms 2026-09-20',
    register_confirmed_at = now()
WHERE code = 'VIC_PLANNING_AMENDMENTS';

INSERT INTO audit_event (actor_agent, action, object_table, object_id,
                         new_state, correlation_id)
SELECT 'migrations.0014', 'SOURCE_REGISTER_CONFIRMED', 'data_source', id::text,
       jsonb_build_object('code', code, 'confirmed_by', register_confirmed_by,
                          'basis', 'terms read and recorded in migration 0014'),
       gen_random_uuid()
FROM data_source WHERE code = 'VIC_PLANNING_AMENDMENTS';

COMMIT;
