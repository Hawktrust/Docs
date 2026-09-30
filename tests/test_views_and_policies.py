"""A view is a way around a policy, unless somebody decided otherwise.

A view without `security_invoker` runs with its owner's privileges and its
owner's row-level security context, so it sees every row whatever the caller's
policies say. That is sometimes exactly right and sometimes a hole, and until
0029 nothing in the repository said which was which.

The audit that produced these tests found no exploitable hole. It found two
protections that were load-bearing by accident: three views bypassing RLS while
exposing row-level data, safe only because nobody had granted the application
role SELECT on them. These tests are what makes that a decision instead of a
coincidence.
"""
import pytest

# Views that legitimately see the whole database, with the reason. Anything not
# listed here must be caller-scoped.
DELIBERATE_BYPASS = {
    "launch_readiness":
        "the launch gate counts rows across the whole database; caller-scoped "
        "it would report the system ready on the strength of rows the caller "
        "cannot see",
    "data_rights_exception":
        "reads data_source, which has no policies for anybody",
    "parcel_planning_current":
        "parcels carry no personal information",
    "parcel_dwelling_current":
        "parcels carry no personal information",
}

# Columns whose exposure past a policy would be a privacy failure rather than
# an inconvenience.
PERSONAL = ("contact_identifier", "identifier", "normalised", "password_hash",
            "email")


def views(db):
    return db.execute(
        """SELECT c.relname,
                  coalesce((SELECT option_value FROM pg_options_to_table(c.reloptions)
                            WHERE option_name = 'security_invoker'), 'off')
           FROM pg_class c
           WHERE c.relkind = 'v' AND c.relnamespace = 'public'::regnamespace
           ORDER BY c.relname""").fetchall()


def test_every_bypassing_view_is_one_somebody_chose(db):
    """The invariant. A view that sees past the policies is either on the list
    with a reason, or it is an accident nobody has noticed yet."""
    unexplained = [name for name, invoker in views(db)
                   if invoker != "true" and name not in DELIBERATE_BYPASS]
    assert unexplained == [], (
        "these views bypass row-level security and no reason is recorded: "
        + ", ".join(unexplained)
        + ". Either set security_invoker = true, or add it to "
          "DELIBERATE_BYPASS with the reason.")


def test_no_bypassing_view_exposes_a_person(db):
    """The one that would actually matter. A caller-scoped view exposing a name
    is fine; a bypassing one is a way to read past the policy protecting it."""
    offenders = []
    for name, invoker in views(db):
        if invoker == "true":
            continue
        cols = {r[0] for r in db.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = %s""",
            (name,)).fetchall()}
        leaked = cols & set(PERSONAL)
        if leaked:
            offenders.append(f"{name} exposes {sorted(leaked)}")
    assert offenders == [], "; ".join(offenders)


def test_the_gate_still_sees_everything(db):
    """launch_readiness must NOT be caller-scoped, and this is the reason
    written as a test: a gate that counts only what the caller can see reports
    a comfortable number and calls the system ready."""
    invoker = dict(views(db))["launch_readiness"]
    assert invoker != "true", (
        "launch_readiness has been made caller-scoped. Every check in it is a "
        "count, so it would now compute each one over a subset of the database "
        "and pass on rows nobody can see.")


@pytest.mark.parametrize("view", sorted(DELIBERATE_BYPASS))
def test_each_deliberate_bypass_still_exists(db, view):
    """So the list cannot rot into naming views that were renamed or dropped,
    which would quietly re-permit whatever replaced them."""
    assert view in dict(views(db)), (
        f"{view} is on the deliberate-bypass list and no longer exists; "
        "remove it rather than leaving a stale exemption")


def test_the_three_that_expose_a_name_are_caller_scoped(db):
    """Named explicitly, because these are the ones the audit was about."""
    invoker = dict(views(db))
    for view in ("channel_exception", "opt_out_prominence_exception",
                 "retention_due"):
        assert invoker[view] == "true", f"{view} bypasses row-level security"


# ---------------------------------------------------------------- the tables

# Tables that carry no row-level security, each with the reason. Every one is
# from 0001 and each is a decision; the migration comments say the same thing at
# more length. Anything not on this list must have policies.
DELIBERATE_NO_RLS = {
    "app_user":
        "authentication reads a row by email before any role is known, so a "
        "policy gated on crown_role() would refuse every login",
    "audit_event":
        "it exists to be auditable by anybody entitled to audit; UPDATE and "
        "DELETE are revoked and the 0005 trigger refuses both anyway",
    "evidence_record":
        "the shared graph — separation that matters is by origin, and the "
        "parcel_real and buyer_mandate_real views carry it",
    "data_source":
        "the rights register is read by the crawler gate on every fetch",
    "evidence_review_queue":
        "a work queue every analyst works, not owned by whoever queued it",
    "match_weight_config":
        "every score records the weight version that produced it",
    "signal_weight_config":
        "same as match_weight_config",
    "raw_ingest":
        "bodies as fetched, read by nothing at run time; the weakest of the "
        "nine, and it needs a policy the day anything surfaces it to a user",
}


def tables_without_rls(db):
    return [r[0] for r in db.execute(
        """SELECT relname FROM pg_class
           WHERE relkind = 'r' AND relnamespace = 'public'::regnamespace
             AND NOT relrowsecurity
           ORDER BY relname""").fetchall()]


def test_every_unprotected_table_is_one_somebody_chose(db):
    """The same invariant as the views, one layer down. A table with no policies
    is either on the list with a reason or an accident nobody has noticed."""
    unexplained = [t for t in tables_without_rls(db)
                   if t not in DELIBERATE_NO_RLS]
    assert unexplained == [], (
        "these tables have no row-level security and no reason is recorded: "
        + ", ".join(unexplained)
        + ". Add policies, or add them to DELIBERATE_NO_RLS with the reason.")


def test_the_list_does_not_outlive_its_tables(db):
    """So a rename cannot leave behind an exemption that silently covers
    whatever took the old name."""
    present = set(tables_without_rls(db))
    stale = [t for t in DELIBERATE_NO_RLS if t not in present]
    assert stale == [], (
        "on the no-policy list but now protected or gone: " + ", ".join(stale)
        + " — remove the exemption rather than leaving it")


def test_no_table_referencing_a_row_restricted_one_is_unprotected(db):
    """The leak 0030 closed, as an invariant. opportunity restricts by row, so a
    table pointing at it without policies lets somebody enumerate the rows they
    were refused — which is what opportunity_evidence and opportunity_parcel
    did, measured at one leaked link out of two."""
    offenders = db.execute(
        """SELECT DISTINCT c.relname
           FROM pg_constraint co
           JOIN pg_class c ON c.oid = co.conrelid
           JOIN pg_class p ON p.oid = co.confrelid
           WHERE co.contype = 'f'
             AND NOT c.relrowsecurity
             AND p.relrowsecurity
             AND EXISTS (SELECT 1 FROM pg_policies
                         WHERE tablename = p.relname
                           AND qual LIKE '%crown.user_id%')
           ORDER BY 1""").fetchall()
    names = [r[0] for r in offenders]
    assert names == [], (
        "these have no policies but reference a table restricted by row, so "
        "they expose rows their parent refuses: " + ", ".join(names))


def test_the_join_tables_follow_their_opportunity(db):
    """Written as a subquery on purpose: the link inherits whatever opportunity
    decides, so there is one copy of the rule rather than two, and the second
    copy is the one that goes stale."""
    for table in ("opportunity_evidence", "opportunity_parcel"):
        quals = [r[0] for r in db.execute(
            """SELECT qual FROM pg_policies
               WHERE tablename = %s AND cmd = 'SELECT'""", (table,)).fetchall()]
        assert quals, f"{table} has no SELECT policy"
        assert any("opportunity" in (q or "") for q in quals), (
            f"{table}'s SELECT policy does not defer to opportunity")
