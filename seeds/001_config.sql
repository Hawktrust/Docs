-- Seed: the starting weight set.
--
-- Operational configuration, not evidence and not people. Safe to apply to any
-- database including a production one — MATCH_WEIGHTS_ARE_VERSIONED requires
-- it, so a database without it cannot launch.
--
-- The four demonstration accounts that used to live in this file are now in
-- seeds/dev_only_users.sql. They were here because the thin loop needed
-- somebody to attribute a decision to, and they stayed here long enough that
-- README told anybody building a real database to apply them. See that file
-- for why that was the wrong place for them.

-- AC6: these five numbers are the whole of the scoring configuration. Changing
-- one and activating the new version changes the ranking, with no code change.
INSERT INTO match_weight_config
    (version, geographic_fit, asset_fit, price_fit, size_fit, mandate_freshness, is_active)
VALUES (1, 0.350, 0.200, 0.200, 0.150, 0.100, true)
ON CONFLICT (version) DO NOTHING;
