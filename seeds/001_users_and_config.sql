-- Seed: the named humans, and the starting weight set.
--
-- These are operational configuration, not evidence. The display names are role
-- placeholders for the thin loop; replace them with the actual people before
-- anyone relies on an owner or approver name.

INSERT INTO app_user (email, display_name, role) VALUES
    ('hawk@crown.local',       'Hawk',             'ADMIN'),
    ('analyst@crown.local',    'Crown Analyst',    'ANALYST'),
    ('compliance@crown.local', 'Crown Compliance', 'COMPLIANCE'),
    ('agent@crown.local',      'Crown Agent',      'AGENT')
ON CONFLICT (email) DO NOTHING;

-- AC6: these five numbers are the whole of the scoring configuration. Changing
-- one and activating the new version changes the ranking, with no code change.
INSERT INTO match_weight_config
    (version, geographic_fit, asset_fit, price_fit, size_fit, mandate_freshness, is_active)
VALUES (1, 0.350, 0.200, 0.200, 0.150, 0.100, true)
ON CONFLICT (version) DO NOTHING;
