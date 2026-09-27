-- CROWN AI — MIGRATION 0027: the rule-raised opportunity is one per geography
--
-- crown.opportunity.refresh() opens with "an opportunity is identified by
-- (lga, geography_label), so a second run restages the existing row rather than
-- creating a second one." That was true of the code and not of the schema: the
-- only unique index on opportunity was its primary key on a generated id, so the
-- identity the module is built around was enforced by a SELECT in Python and by
-- nothing else.
--
-- WHAT THAT ALLOWED. Two refreshes overlapping — a cron poll and somebody
-- pressing the button, or two workers once ingestion is concurrent — both read
-- no existing row for a geography and both insert one. Two opportunity rows for
-- one suburb, each with its own stage, its own owner and half the evidence.
-- Nothing downstream would report it: match_result, approval and attribution all
-- reference an opportunity id and do not care that a second one exists. It would
-- surface as a person approached twice about the same land by the same firm,
-- which is the failure acceptance criterion 2 exists to stop — guaranteed for
-- evidence records since 0001, and until now merely intended for the
-- opportunities built from them.
--
-- WHY THIS IS A PARTIAL INDEX, which is the part worth reading.
--
-- The obvious constraint — UNIQUE (lga, geography_label) — is wrong, and 0008
-- says why. Crown working Tarneit for its own book and Crown working Tarneit for
-- Client A are two opportunities on one geography *on purpose*: that is the
-- conflict this product has to be able to see, conflict_disclosure exists to
-- record the competing pair, and outbound refuses to send until the disclosure
-- is there. A blanket unique index would have made the conflict unrepresentable
-- and quietly deleted the control — the schema would have enforced that Crown
-- cannot notice it is on two sides of a deal.
--
-- So (lga, geography_label) is not the identity of an opportunity. It is the
-- identity of a *rule-raised* one, and 0008 already named that state: principal
-- is 'NULL until someone decides, which is honest: an opportunity raised by a
-- rule has no principal yet'. refresh() only ever creates rows in that state.
-- The invariant it actually needs, and now has, is: at most one unassigned
-- opportunity per geography. Once a human takes one on for a principal it leaves
-- the set this index governs, which is correct — it has stopped being the rule's
-- row and become theirs.
--
-- STILL OPEN, and deliberately not decided here: refresh() looks a geography up
-- by (lga, geography_label) without regard to principal, so once a geography's
-- rule-raised opportunity has been assigned a principal, which row refresh
-- restages is ambiguous. Narrowing that lookup would change behaviour — the next
-- refresh would raise a fresh unassigned opportunity for the geography instead
-- of restaging the assigned one — and that is a product decision about whether
-- the rule keeps tracking a geography somebody has taken on. Recorded rather
-- than guessed.
--
-- IF THIS MIGRATION FAILS, it has found duplicates that already exist. Do not
-- drop the index to admit them. Each is two records of one geography with no
-- principal to tell them apart, and the question is which stage, owner and
-- evidence set is correct — a merge a person decides, because picking one
-- automatically would silently discard an owner's work. The query names them.

BEGIN;

-- Report before enforcing, so a failure arrives with the rows attached rather
-- than as a bare constraint violation.
DO $$
DECLARE
    offending text;
BEGIN
    SELECT string_agg(format('%s/%s (%s rows)', lga, geography_label, n), '; ')
      INTO offending
      FROM (SELECT lga, geography_label, count(*) AS n
              FROM opportunity
             WHERE principal IS NULL
             GROUP BY lga, geography_label
            HAVING count(*) > 1) d;

    IF offending IS NOT NULL THEN
        RAISE EXCEPTION
            'opportunity already holds duplicate unassigned geographies: %. '
            'Each is two records of one geography; merge them by hand — decide '
            'which stage, owner and evidence set is right — then re-run this '
            'migration. Do not drop this index.', offending;
    END IF;
END $$;

CREATE UNIQUE INDEX one_rule_raised_opportunity_per_geography
    ON opportunity (lga, geography_label)
    WHERE principal IS NULL;

COMMENT ON INDEX one_rule_raised_opportunity_per_geography IS
    'refresh() restages the existing unassigned row for a (lga, geography_label) '
    'instead of adding a second, and this makes that true when two refreshes run '
    'at once rather than only when they do not. Scoped to principal IS NULL so '
    'that two principals on one geography — the conflict 0008 exists to make '
    'visible — stays representable.';

COMMIT;
