-- DEVELOPMENT ONLY. Not part of the production seed set.
--
-- Ticket 01 says everything is real except the buyer mandates. It is, in the
-- real database: no evidence has been ingested there, because egress to
-- planning.vic.gov.au is blocked (see ingest/README.md).
--
-- These rows exist so the loop can be walked end to end on a developer's
-- machine. Every one is flagged DEMO_SYNTHETIC in the origin column and titled
-- as a demo record. They do not describe real amendments, and loading this file
-- into a database anyone reads a figure from would be a mistake.

INSERT INTO evidence_record (
    source_id, source_reference, source_url, provider, retrieved_at, observed_at,
    last_verified_at, lane, reliability, evidence_class, confidence, lga, title,
    summary, amendment_status, geography, origin)
SELECT ds.id, v.reference,
       'https://www.planning.vic.gov.au/amendment/' || v.reference,
       'State Government of Victoria', now(), v.observed::timestamptz, now(),
       'B_OPEN', 'AUTHORITATIVE', v.klass::evidence_class, v.confidence,
       v.lga, 'DEMO RECORD — ' || v.title, v.summary, v.status,
       jsonb_build_object('suburbs', jsonb_build_array(v.suburb)), 'DEMO_SYNTHETIC'
FROM data_source ds,
(VALUES
  ('DEMO-C001wynd', 'Wyndham', 'Tarneit',      'Rezoning of land in the Tarneit precinct', 'Demo amendment used to exercise the loop', 'GAZETTED',  'FACT',       1.0, '2026-08-14'),
  ('DEMO-C002wynd', 'Wyndham', 'Tarneit',      'Public acquisition overlay, Tarneit',      'Demo amendment used to exercise the loop', 'EXHIBITED', 'HYPOTHESIS', 0.9, '2026-08-28'),
  ('DEMO-C003wynd', 'Wyndham', 'Werribee',     'Structure plan update, Werribee',          'Demo amendment used to exercise the loop', 'EXHIBITED', 'HYPOTHESIS', 0.9, '2026-07-19'),
  ('DEMO-C004melt', 'Melton',  'Rockbank',     'Precinct structure plan, Rockbank',        'Demo amendment used to exercise the loop', 'GAZETTED',  'FACT',       1.0, '2026-06-30'),
  ('DEMO-C005hume', 'Hume',    'Craigieburn',  'Industrial land rezoning, Craigieburn',    'Demo amendment used to exercise the loop', 'EXHIBITED', 'HYPOTHESIS', 0.9, '2026-08-05')
) AS v(reference, lga, suburb, title, summary, status, klass, confidence, observed)
WHERE ds.code = 'VIC_PLANNING_AMENDMENTS';
