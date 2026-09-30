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
