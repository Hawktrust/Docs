-- CROWN AI — MIGRATION 0015: the councils, one by one, and a name on the register
--
-- Migration 0014 left COUNCIL_PLANNING_REGISTERS at UNKNOWN with a note saying
-- it was not one source and should become seven. Reading those seven sets of
-- terms turned up something better than seven rows, and something worse than
-- the plan assumed. Both are recorded here.
--
-- WORSE: a council website is not open data. Every council whose own terms page
-- could be found reserves all rights in its content, and Greater Geelong's is
-- explicit that it may not be used "for any commercial purpose whatsoever" and
-- may not be made available to third parties. Crown is a commercial user that
-- produces artefacts for buyers. Pointing a crawler at seven council sites was
-- never the Lane B win the plan treated it as.
--
-- BETTER: the state already aggregates the same data. Every Victorian
-- responsible authority reports standardised planning permit application data
-- monthly to the Planning Permit Activity Reporting System, operated by the
-- Department of Transport and Planning — whose terms Crown read in 0014 and
-- found to be CC BY 4.0. One publisher, one licence already cleared, all seven
-- councils covered, and no scraping.
--
-- HOW THESE WERE READ. By search relay, not by direct fetch: every host in this
-- file answers 403 at the egress gateway, re-tested 2026-09-21. This repository
-- has already been burned once by relay detail contradicting itself, and it
-- happened again here — for three of the seven councils the relay returned the
-- terms of a third-party community-engagement platform instead of the council's
-- own site. Those three are left UNKNOWN with the page to read recorded, rather
-- than given a position nobody checked. terms_read_by says relay on every row
-- set below, so no reader mistakes any of this for a verified reading.

BEGIN;

-- ============================================================
-- THE BETTER ROUTE — the state's own aggregation
-- ============================================================

INSERT INTO data_source (code, display_name, provider, lane, licence_reference,
                         attribution_text, is_ingestible, notes,
                         carries_personal_information, automated_access,
                         terms_reference, terms_read_by, terms_read_at)
VALUES
    ('VIC_PPARS', 'Planning Permit Activity Reporting System',
     'Department of Transport and Planning', 'B_OPEN',
     'https://www.vic.gov.au/dtp-website-terms-and-conditions — CC BY 4.0, '
     'excepting images, photographs and branding',
     '© State of Victoria (Department of Transport and Planning). Licensed under '
     'a Creative Commons Attribution 4.0 licence '
     '(http://creativecommons.org/licenses/by/4.0/). Changes were made: records '
     'were extracted, normalised and classified.',
     false,
     'Every Victorian responsible authority reports standardised planning permit '
     'application data to PPARS monthly, against a published data dictionary, and '
     'DTP publishes monthly, quarterly and annual reports from it. This is the '
     'source the seven per-council rows below were meant to be: one publisher, '
     'statewide coverage, and DTP terms Crown has already read. '
     'WHAT IT DOES NOT GIVE: the published reports are activity statistics. '
     'Whether a register-level extract naming applicants and addresses is '
     'obtainable, and on what terms, is the question to put to DTP — and it is a '
     'question with one answer for the whole state rather than seventy-nine. '
     'Reported by search relay 2026-09-21; not verified by direct fetch.',
     true, 'PERMITTED',
     'https://www.vic.gov.au/dtp-website-terms-and-conditions',
     'Crown AI review 2026-09-21 (search relay; not verified by direct fetch — '
     'egress blocked)', now()),

-- ============================================================
-- THE SEVEN COUNCILS — one row each, as 0014 said they should be
--
-- is_ingestible is false on every one of them and stays false until somebody
-- reads that council's terms directly and signs the row. Splitting the source
-- does not open it; it makes each one answerable on its own.
-- ============================================================

    ('COUNCIL_WYNDHAM', 'Wyndham City Council planning register',
     'Wyndham City Council', 'B_OPEN', NULL, NULL, false,
     'Relay returned the terms of The Loop, Wyndham''s community-engagement '
     'platform (operated by a third party), not the council website''s own terms. '
     'That is not this source. UNKNOWN until wyndham.vic.gov.au''s own copyright '
     'or terms page is read directly. Prefer an RSS or email alert on advertised '
     'applications if the council offers one — a feed is the publisher handing '
     'over the channel, and answers the scraping question by removing it.',
     true, 'UNKNOWN', 'https://www.wyndham.vic.gov.au/', NULL, NULL),

    ('COUNCIL_MELTON', 'Melton City Council planning register',
     'Melton City Council', 'B_OPEN', NULL, NULL, false,
     'Relay returned the terms of Melton Conversations, a third-party engagement '
     'platform, not the council website''s own. UNKNOWN until melton.vic.gov.au''s '
     'own terms are read directly. Prefer a published alert feed if one exists.',
     true, 'UNKNOWN', 'https://www.melton.vic.gov.au/', NULL, NULL),

    ('COUNCIL_HUME', 'Hume City Council planning register',
     'Hume City Council', 'B_OPEN', NULL, NULL, false,
     'Relay returned the terms of Participate Hume, a third-party engagement '
     'platform, not the council website''s own. UNKNOWN until hume.vic.gov.au''s '
     'own terms are read directly. Hume runs an eProperty portal at '
     'ehume.hume.vic.gov.au, which is a likelier register endpoint than the main '
     'site and carries its own terms.',
     true, 'UNKNOWN', 'https://www.hume.vic.gov.au/', NULL, NULL),

    ('COUNCIL_WHITTLESEA', 'City of Whittlesea planning register',
     'City of Whittlesea', 'B_OPEN', NULL, NULL, false,
     'Whittlesea publishes an online planning application portal. No terms or '
     'copyright page was located by relay, so nothing is assumed. UNKNOWN until '
     'whittlesea.vic.gov.au''s terms are read directly. Whittlesea is the LGA '
     'Crown''s land search was built around, so this is the row to resolve first.',
     true, 'UNKNOWN',
     'https://www.whittlesea.vic.gov.au/Services/Building-planning-and-development/Planning/Online-planning-application-portal',
     NULL, NULL),

    ('COUNCIL_CASEY', 'City of Casey planning permit application register',
     'City of Casey', 'B_OPEN', NULL, NULL, false,
     'The one council of the seven that publishes its register as open data with '
     'a documented API, rather than as pages to be scraped: application category, '
     'number, description, suburb, postcode, ward, status, decision stage and '
     'dates. DataVic''s default licence under the DataVic Access Policy is CC BY '
     '4.0. Recorded as PUBLISHER_FEED because an open-data API is the publisher '
     'offering exactly this channel — but confirm the licence on the portal '
     'itself and record the attribution wording before ingesting, the same way '
     '0014 had to correct the wording on the DTP row. Reported by search relay '
     '2026-09-21; not verified by direct fetch.',
     true, 'PUBLISHER_FEED',
     'https://discover.data.vic.gov.au/dataset/planning-permit-application-register',
     'Crown AI review 2026-09-21 (search relay; not verified by direct fetch — '
     'egress blocked)', now()),

    ('COUNCIL_GREATER_GEELONG', 'City of Greater Geelong planning register',
     'City of Greater Geelong', 'B_OPEN', NULL, NULL, false,
     'The council whose own terms page relay did find, and it is the sharpest '
     'answer of the seven: content may be used solely for personal or internal '
     'business purposes, may not be modified, may not be made available to third '
     'parties, and no part may be reproduced or used for any commercial purpose '
     'whatsoever. Crown is a commercial user producing artefacts for third-party '
     'buyers, so this is PROHIBITED on its face and a written permission is the '
     'only route. Treat it as the likely shape of the other six until each is '
     'read. Reported by search relay 2026-09-21; not verified by direct fetch.',
     true, 'PROHIBITED',
     'https://www.geelongcity.vic.gov.au/council/council-and-organisation/using-website/terms-and-conditions '
     '— use is limited to personal or internal business purposes, content may not '
     'be made available to third parties, and no part may be reproduced, modified, '
     'adapted, published or used for any commercial purpose',
     'Crown AI review 2026-09-21 (search relay; not verified by direct fetch — '
     'egress blocked)', now()),

    ('COUNCIL_GREATER_SHEPPARTON', 'Greater Shepparton City Council planning register',
     'Greater Shepparton City Council', 'B_OPEN', NULL, NULL, false,
     'The site carries copyright and disclaimer pages; relay retrieved the '
     'disclaimer (accuracy and external links) but not the copyright terms, which '
     'are the ones that matter here. UNKNOWN until greatershepparton.com.au''s '
     'copyright page is read directly.',
     true, 'UNKNOWN', 'https://greatershepparton.com.au/', NULL, NULL)
ON CONFLICT (code) DO NOTHING;

-- ============================================================
-- THE ROW THEY REPLACE
--
-- Kept rather than deleted. A rights register is a record of what was believed
-- and when, and deleting the row would erase the reasoning that produced seven
-- better ones. Marked superseded so nobody ingests against it.
-- ============================================================

UPDATE data_source SET
    notes = notes || ' SUPERSEDED 2026-09-21 by migration 0015: replaced by seven '
                     'per-council rows (COUNCIL_WYNDHAM, COUNCIL_MELTON, '
                     'COUNCIL_HUME, COUNCIL_WHITTLESEA, COUNCIL_CASEY, '
                     'COUNCIL_GREATER_GEELONG, COUNCIL_GREATER_SHEPPARTON) and by '
                     'VIC_PPARS, the state aggregation that makes most of them '
                     'unnecessary. This row is history and must not be ingested '
                     'against. Its premise was wrong twice over: council sites are '
                     'not open data, and the RSS-alert idea it recorded is right '
                     'but is a property of individual councils, not of all 79.'
WHERE code = 'COUNCIL_PLANNING_REGISTERS';

-- ============================================================
-- HOW EVERY OTHER POSITION WAS READ
--
-- The rows above say "search relay" because that is how they were read. So was
-- every position already in the register: 0009 and 0014 both recorded readings
-- as "Crown AI review <date>", which says who looked but not how, and the how
-- is the part a reader needs. No Victorian host has been reachable from this
-- environment on any day any of these were written.
--
-- Backfilled rather than left alone, because a register where some rows
-- disclose their basis and others do not is worse than one where none do: the
-- silence reads as a stronger reading rather than an older one. Guarded on
-- ILIKE so re-running it cannot stack the disclosure twice.
--
-- The rows seeds/003 inserts are not here. Seeds run after every migration, so
-- they do not exist yet; their wording is corrected in that file instead.
-- ============================================================

UPDATE data_source SET
    terms_read_by = terms_read_by || ' (search relay; not verified by direct '
                                     'fetch — egress blocked)'
WHERE terms_read_by IS NOT NULL
  AND terms_read_by NOT ILIKE '%relay%';

-- ============================================================
-- THE NAME ON THE REGISTER
--
-- 0014 signed VIC_PLANNING_AMENDMENTS as "Hawk (Crown Capital & Development), on
-- Crown AI's reading of the DTP terms 2026-09-20", which bundled the confirming
-- party and the basis into one string. Asked whose name should carry the
-- attestation, Crown answered: the company's.
--
-- Nothing is lost by separating them. register_confirmed_by now names the party
-- that takes responsibility, terms_read_by already records who did the reading
-- (see the backfill above), and the audit trail holds both. A reader
-- asking "who confirmed this, and on what" still gets a complete answer; it is
-- now in the three columns built for it rather than in one sentence.
--
-- Worth knowing: the register's own rule, as 0001 phrased it, is that a named
-- ADVISER signs. An organisation is not a named human, so this satisfies the
-- column without fully satisfying that intent. If a person's name is wanted
-- later it is one run of scripts/confirm_source.py after clearing the column.
-- ============================================================

UPDATE data_source SET
    register_confirmed_by = 'Crown Capital & Development',
    register_confirmed_at = now()
WHERE code = 'VIC_PLANNING_AMENDMENTS';

INSERT INTO audit_event (actor_agent, action, object_table, object_id,
                         new_state, correlation_id)
SELECT 'migrations.0015', 'SOURCE_REGISTER_CONFIRMED', 'data_source', id::text,
       jsonb_build_object(
           'code', code,
           'confirmed_by', register_confirmed_by,
           'terms_read_by', terms_read_by,
           'basis', 'reassigned from the 0014 signature at Crown''s direction; '
                    'the reading it rests on is unchanged and recorded in '
                    'terms_read_by'),
       gen_random_uuid()
FROM data_source WHERE code = 'VIC_PLANNING_AMENDMENTS';

COMMIT;
