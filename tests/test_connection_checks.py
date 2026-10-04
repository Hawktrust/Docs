"""Whether the role Crown connects as can be constrained at all.

Row-level security is this system's authorisation model — twenty tables, and
every policy assumes the connection is subject to them. Three things defeat that
silently, and a bypassing connection reads `launch_readiness` perfectly happily
and sees nothing wrong, which is what makes it worth a check of its own.

The realistic failure is not exotic. Managed Postgres hands out an
administrative user, that user is the obvious thing to paste into CROWN_DSN, and
the application works — it just answers every query as though no policy existed.
"""
import psycopg
import pytest

from crown import readiness


def codes(report):
    return {c.code: c for c in report.checks}


def test_the_owner_connection_is_refused_as_a_superuser(db):
    """The suite's own `db` fixture connects as the superuser that owns the
    schema. That is right for setting a test up and wrong for running the
    application, and the check says so rather than trusting the DSN."""
    check = codes(readiness.check(db))["THE_APPLICATION_ROLE_IS_NOT_A_SUPERUSER"]
    assert not check.passes
    assert "SUPERUSER" in check.detail
    assert "crown_app" in check.closes_it


def test_the_application_connection_passes(app_db):
    """crown_app owns nothing and has no exemptions. This is the connection the
    application is supposed to make."""
    checks = codes(readiness.check(app_db))
    assert checks["THE_APPLICATION_ROLE_IS_NOT_A_SUPERUSER"].passes
    assert checks["THE_APPLICATION_ROLE_CANNOT_BYPASS_RLS"].passes


def test_bypassrls_is_caught_even_without_superuser(database):
    """BYPASSRLS defeats FORCE ROW LEVEL SECURITY specifically — the property
    the schema leans on so that even a table's owner is constrained. A role can
    hold it without being a superuser, which makes it the quieter of the two."""
    owner_dsn, app_dsn = database
    with psycopg.connect(owner_dsn, autocommit=True) as admin:
        admin.execute("ALTER ROLE crown_app BYPASSRLS")
    try:
        with psycopg.connect(app_dsn) as conn:
            check = codes(readiness.check(conn))["THE_APPLICATION_ROLE_CANNOT_BYPASS_RLS"]
            assert not check.passes
            assert "BYPASSRLS" in check.detail
    finally:
        with psycopg.connect(owner_dsn, autocommit=True) as admin:
            admin.execute("ALTER ROLE crown_app NOBYPASSRLS")


def test_every_policy_table_forces_its_policies(db):
    """Without FORCE, a table's owner is exempt from its own policies. All
    twenty force them today; this is what notices if the twenty-first does not,
    because a test of the policies themselves would still pass."""
    check = codes(readiness.check(db))["ROW_LEVEL_SECURITY_APPLIES_TO_THE_OWNER"]
    assert check.passes, check.detail


def test_an_unforced_table_is_reported_by_name(db):
    """Named, because "one table is exposed" sends somebody hunting through
    twenty-eight migrations."""
    db.execute("ALTER TABLE contact_suppression NO FORCE ROW LEVEL SECURITY")
    check = codes(readiness.check(db))["ROW_LEVEL_SECURITY_APPLIES_TO_THE_OWNER"]
    assert not check.passes
    assert "contact_suppression" in check.detail
    db.rollback()


def test_these_are_blocking_not_advisory(db):
    """A connection that bypasses authorisation is not a warning."""
    for code in ("THE_APPLICATION_ROLE_IS_NOT_A_SUPERUSER",
                 "THE_APPLICATION_ROLE_CANNOT_BYPASS_RLS",
                 "ROW_LEVEL_SECURITY_APPLIES_TO_THE_OWNER"):
        assert codes(readiness.check(db))[code].severity == "BLOCKING"


def test_the_gate_cannot_be_read_into_passing_by_a_bypassing_connection(db):
    """The point. Before this, every check in the report was a query against
    the database — so a connection exempt from the policies produced a clean
    report while being the problem."""
    report = readiness.check(db)
    assert not report.ready
    assert "THE_APPLICATION_ROLE_IS_NOT_A_SUPERUSER" in {
        c.code for c in report.checks if not c.passes}
