-- Seed: twenty buyer mandates, ticket item 4.
--
-- Every record is synthetic. That is asserted twice on purpose: in origin,
-- which the schema requires to be explicit with no default, and in buyer_label,
-- so the label travels with the record into any view that renders it.
--
-- Constitution §6: none of these correspond to a real buyer, a real mandate or
-- a real conversation. They exist to exercise the matching function and must
-- never be counted in a figure shown to a person -- query buyer_mandate_real
-- for that.

INSERT INTO buyer_mandate (buyer_label, origin, geographies, asset_types,
    land_size_min_sqm, land_size_max_sqm, price_min_aud, price_max_aud,
    planning_risk_appetite, relationship_strength, mandate_date, is_active)
VALUES
    ('DEMO / SYNTHETIC DATA — Buyer 01', 'DEMO_SYNTHETIC', '{"Wyndham"}', '{"RESIDENTIAL_LAND"}', 20000, 120000, 8000000, 30000000, 'MEDIUM', 'STRONG', '2026-08-20', true),
    ('DEMO / SYNTHETIC DATA — Buyer 02', 'DEMO_SYNTHETIC', '{"Wyndham","Melton"}', '{"RESIDENTIAL_LAND"}', 40000, 250000, 15000000, 60000000, 'HIGH', 'STRONG', '2026-07-02', true),
    ('DEMO / SYNTHETIC DATA — Buyer 03', 'DEMO_SYNTHETIC', '{"Wyndham"}', '{"INDUSTRIAL_LAND"}', 10000, 80000, 5000000, 25000000, 'LOW', 'MODERATE', '2026-06-11', true),
    ('DEMO / SYNTHETIC DATA — Buyer 04', 'DEMO_SYNTHETIC', '{"Melton"}', '{"RESIDENTIAL_LAND"}', 30000, 200000, 10000000, 45000000, 'MEDIUM', 'MODERATE', '2026-08-01', true),
    ('DEMO / SYNTHETIC DATA — Buyer 05', 'DEMO_SYNTHETIC', '{"Hume"}', '{"INDUSTRIAL_LAND"}', 25000, 150000, 12000000, 55000000, 'MEDIUM', 'STRONG', '2026-05-19', true),
    ('DEMO / SYNTHETIC DATA — Buyer 06', 'DEMO_SYNTHETIC', '{"Hume","Wyndham"}', '{"MIXED_USE"}', 5000, 40000, 4000000, 18000000, 'HIGH', 'WEAK', '2026-04-08', true),
    ('DEMO / SYNTHETIC DATA — Buyer 07', 'DEMO_SYNTHETIC', '{"Wyndham"}', '{"RESIDENTIAL_LAND","MIXED_USE"}', 15000, 90000, 6000000, 22000000, 'LOW', 'STRONG', '2026-08-28', true),
    ('DEMO / SYNTHETIC DATA — Buyer 08', 'DEMO_SYNTHETIC', '{"Melton","Hume"}', '{"RESIDENTIAL_LAND"}', 50000, 300000, 20000000, 80000000, 'HIGH', 'MODERATE', '2026-03-14', true),
    ('DEMO / SYNTHETIC DATA — Buyer 09', 'DEMO_SYNTHETIC', '{"Wyndham"}', '{"COMMERCIAL"}', 2000, 15000, 3000000, 12000000, 'LOW', 'WEAK', '2026-07-22', true),
    ('DEMO / SYNTHETIC DATA — Buyer 10', 'DEMO_SYNTHETIC', '{"Hume"}', '{"RESIDENTIAL_LAND"}', 35000, 180000, 14000000, 50000000, 'MEDIUM', 'STRONG', '2026-08-15', true),
    ('DEMO / SYNTHETIC DATA — Buyer 11', 'DEMO_SYNTHETIC', '{"Melton"}', '{"INDUSTRIAL_LAND"}', 20000, 110000, 9000000, 35000000, 'MEDIUM', 'MODERATE', '2026-02-27', true),
    ('DEMO / SYNTHETIC DATA — Buyer 12', 'DEMO_SYNTHETIC', '{"Wyndham","Melton","Hume"}', '{"RESIDENTIAL_LAND"}', 60000, 400000, 25000000, 120000000, 'HIGH', 'STRONG', '2026-09-01', true),
    ('DEMO / SYNTHETIC DATA — Buyer 13', 'DEMO_SYNTHETIC', '{"Geelong"}', '{"RESIDENTIAL_LAND"}', 20000, 100000, 7000000, 28000000, 'MEDIUM', 'MODERATE', '2026-06-30', true),
    ('DEMO / SYNTHETIC DATA — Buyer 14', 'DEMO_SYNTHETIC', '{"Casey","Cardinia"}', '{"RESIDENTIAL_LAND"}', 30000, 160000, 11000000, 40000000, 'LOW', 'WEAK', '2026-05-05', true),
    ('DEMO / SYNTHETIC DATA — Buyer 15', 'DEMO_SYNTHETIC', '{"Wyndham"}', '{"RETAIL"}', 1000, 8000, 2000000, 9000000, 'LOW', 'MODERATE', '2025-11-18', true),
    ('DEMO / SYNTHETIC DATA — Buyer 16', 'DEMO_SYNTHETIC', '{"Wyndham","Hume"}', '{"INDUSTRIAL_LAND","MIXED_USE"}', 18000, 95000, 8500000, 32000000, 'MEDIUM', 'STRONG', '2026-07-14', true),
    ('DEMO / SYNTHETIC DATA — Buyer 17', 'DEMO_SYNTHETIC', '{"Melton"}', '{"MIXED_USE"}', 6000, 45000, 4500000, 16000000, 'HIGH', 'WEAK', '2025-09-09', true),
    ('DEMO / SYNTHETIC DATA — Buyer 18', 'DEMO_SYNTHETIC', '{"Hume"}', '{"COMMERCIAL"}', 3000, 20000, 3500000, 14000000, 'MEDIUM', 'MODERATE', '2026-04-25', true),
    ('DEMO / SYNTHETIC DATA — Buyer 19', 'DEMO_SYNTHETIC', '{"Wyndham"}', '{"RESIDENTIAL_LAND"}', 25000, 130000, 9500000, 38000000, 'MEDIUM', 'STRONG', '2026-01-12', false),
    ('DEMO / SYNTHETIC DATA — Buyer 20', 'DEMO_SYNTHETIC', '{"Wyndham","Melton"}', '{"RESIDENTIAL_LAND"}', 40000, 220000, 16000000, 65000000, 'LOW', 'WEAK', '2024-10-03', false);
