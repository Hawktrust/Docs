-- CROWN AI — MIGRATION 0004: five defects found reviewing the thin loop
--
-- Each of these was reproduced before it was fixed. The tests that reproduce
-- them are in tests/test_integrity.py.

BEGIN;

-- ============================================================
-- 1. buyer_mandate_real bypassed row-level security.
--
-- A view runs with its owner's rights unless told otherwise, and this one is
-- owned by the role that ran the migration. So the view the schema comment
-- tells you to use for "any figure shown to a person" was the one path that
-- ignored the policies on the table underneath it: a connection with no
-- identity set at all could read real mandates through it.
--
-- security_invoker makes the view run as the caller, so the policies on
-- buyer_mandate apply to it like anything else.
-- ============================================================

ALTER VIEW buyer_mandate_real SET (security_invoker = true);

-- ============================================================
-- 2 and 3. One match could be approved twice, and one approval could produce
-- any number of attribution records.
--
-- A double-clicked Approve button was enough. Attribution is append-only, so
-- the duplicates it created could never be removed — permanently wrong rows in
-- the record that is supposed to answer "which signal created this".
-- ============================================================

ALTER TABLE approval
    ADD CONSTRAINT one_decision_per_match UNIQUE (match_result_id);

ALTER TABLE attribution
    ADD CONSTRAINT one_attribution_per_approval UNIQUE (approval_id);

-- ============================================================
-- 4. An approved match could be rescored underneath its approval.
--
-- Recomputing a ranking rewrites match_result rows in place. A match approved
-- at 0.7639 could afterwards read 0.5444, with the approval still pointing at
-- it, so the record no longer showed what the approver actually approved.
--
-- The application skips approved rows when it recomputes; this is the backstop
-- that makes the rule true regardless of which code path does the writing.
-- ============================================================

CREATE OR REPLACE FUNCTION match_result_frozen_once_approved() RETURNS trigger AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM approval WHERE match_result_id = OLD.id) THEN
        RAISE EXCEPTION
            'match_result % has been decided and cannot be rescored: an approval '
            'must keep pointing at the numbers its approver saw', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER match_result_no_rescore_after_approval
    BEFORE UPDATE ON match_result
    FOR EACH ROW EXECUTE FUNCTION match_result_frozen_once_approved();

COMMIT;
