-- DEVELOPMENT ONLY. Do not apply this to a database anybody relies on.
--
-- Four accounts on crown.local, a domain Crown does not own, holding the roles
-- ADMIN, ANALYST, COMPLIANCE and AGENT. They exist so the thin loop has
-- somebody to attribute a decision to, and so the test suite can exercise each
-- role without inventing one per test.
--
-- WHY THEY MOVED OUT OF seeds/001. They were in the same file as the match
-- weight configuration, which a production database does need. README told
-- anyone building a real database to apply that file, so following the
-- instructions produced four privileged accounts on a fake domain.
--
-- None of them has a password and 0006 refuses a login without one, so they
-- could not be signed into. The danger was never that. It was
-- EVERY_ACCOUNT_HAS_A_PASSWORD, whose advice reads "set a password or
-- deactivate the account": a person trying to get the gate green on a real
-- database would have found four accounts blocking it and the check itself
-- suggesting the fix is to give them passwords. A readiness check that steers
-- you toward creating privileged accounts on a domain you do not own is worse
-- than no check.
--
-- A production database gets its first real account from migration 0019
-- instead, and then needs exactly one password set.

INSERT INTO app_user (email, display_name, role) VALUES
    ('hawk@crown.local',       'Hawk',             'ADMIN'),
    ('analyst@crown.local',    'Crown Analyst',    'ANALYST'),
    ('compliance@crown.local', 'Crown Compliance', 'COMPLIANCE'),
    ('agent@crown.local',      'Crown Agent',      'AGENT')
ON CONFLICT (email) DO NOTHING;
