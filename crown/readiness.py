"""May Crown be turned on?

The register answered one kind of question — is this source settled — and the
compliance page showed it. Nothing answered the question a launch actually
turns on, which is all of them at once. A go/no-go made from several
half-answers is a go/no-go made from none.

`launch_readiness` in migration 0016 is the list, written as a view so anybody
can read every condition without running anything. This module reads it, and
`scripts/readiness.py` exits non-zero while a BLOCKING check fails, so the
question can be asked by a deploy pipeline rather than remembered by a person.

The checks say what would close them, not just what is wrong. "0 evidence
records with origin REAL" is a fact; "ingest one real amendment, by allowlist or
by operator capture" is the next action, and a readiness report that omits it
makes the reader go and find somebody who knows.
"""
import os
from dataclasses import dataclass

BLOCKING = "BLOCKING"
ADVISORY = "ADVISORY"


@dataclass(frozen=True)
class Check:
    code: str
    severity: str
    passes: bool
    detail: str
    closes_it: str

    @property
    def blocking(self) -> bool:
        return self.severity == BLOCKING

    def line(self) -> str:
        mark = "pass" if self.passes else ("BLOCK" if self.blocking else "warn")
        text = f"[{mark:>5}] {self.code}: {self.detail}"
        return text if self.passes else f"{text}\n          → {self.closes_it}"


@dataclass(frozen=True)
class Report:
    checks: tuple

    @property
    def blockers(self) -> tuple:
        return tuple(c for c in self.checks if c.blocking and not c.passes)

    @property
    def warnings(self) -> tuple:
        return tuple(c for c in self.checks if not c.blocking and not c.passes)

    @property
    def ready(self) -> bool:
        """Advisory checks never hold a launch. That is what advisory means."""
        return not self.blockers

    def summary(self) -> str:
        if self.ready and not self.warnings:
            return "ready: every check passes"
        if self.ready:
            return (f"ready, with {len(self.warnings)} advisory "
                    f"{'note' if len(self.warnings) == 1 else 'notes'}")
        return (f"NOT READY: {len(self.blockers)} blocking "
                f"{'check' if len(self.blockers) == 1 else 'checks'} failing")

    def report(self) -> str:
        return "\n".join([self.summary(), ""] + [c.line() for c in self.checks])


def deployment_checks(environ=None) -> tuple:
    """The conditions the view cannot see.

    `launch_readiness` reads the database, so it can only check what the
    database knows. These two live in the deployment, and both are the kind of
    thing that is obvious in hindsight and invisible until then.
    """
    environ = os.environ if environ is None else environ
    checks = []

    # Opt-out links must work for thirty days (Spam Act s18). Session cookies
    # want rotating far more often. While one secret signs both, rotating it
    # breaks every live unsubscribe link — a routine operational task becomes a
    # breach, and nothing would report it.
    checks.append(Check(
        code="OPT_OUT_SECRET_IS_ITS_OWN",
        severity=BLOCKING,
        passes=bool(environ.get("CROWN_OPTOUT_SECRET")),
        detail=("CROWN_OPTOUT_SECRET is set"
                if environ.get("CROWN_OPTOUT_SECRET")
                else "opt-out links are signed with CROWN_SECRET"),
        closes_it=("set CROWN_OPTOUT_SECRET to its own value; rotating the "
                   "cookie secret would otherwise break every live unsubscribe "
                   "link and breach the 30-day requirement in s18"),
    ))

    # CROWN_INSECURE_COOKIES exists so the test client, which is not https, can
    # hold a session. In production it strips Secure from the cookie that
    # carries every authorisation decision.
    insecure = environ.get("CROWN_INSECURE_COOKIES") == "1"
    checks.append(Check(
        code="SESSION_COOKIES_ARE_SECURE",
        severity=BLOCKING,
        passes=not insecure,
        detail=("CROWN_INSECURE_COOKIES is set to 1" if insecure
                else "the session cookie carries Secure"),
        closes_it=("unset CROWN_INSECURE_COOKIES; it exists for the test "
                   "client and strips Secure from the cookie that carries "
                   "every authorisation decision"),
    ))
    return tuple(checks)


def connection_checks(conn) -> tuple:
    """Whether the role the application connects as can be constrained at all.

    Row-level security is this system's authorisation model: twenty tables, and
    every policy in the schema assumes the connection is subject to them. Three
    things defeat that silently, and none of them is visible in the application
    or reported by `launch_readiness`, because a bypassing connection reads the
    view perfectly happily and sees nothing wrong.

    This is the check that matters most at deployment and the one most likely to
    be got wrong, because managed Postgres hands out an administrative user by
    default and it is the obvious thing to paste into CROWN_DSN.
    """
    checks = []

    row = conn.execute(
        """SELECT current_user,
                  (SELECT rolsuper    FROM pg_roles WHERE rolname = current_user),
                  (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user)"""
    ).fetchone()
    role, is_super, bypasses = (row[0], bool(row[1]), bool(row[2])) if row \
        else ("unknown", True, True)

    # A superuser is exempt from row-level security entirely — FORCE included.
    checks.append(Check(
        code="THE_APPLICATION_ROLE_IS_NOT_A_SUPERUSER",
        severity=BLOCKING,
        passes=not is_super,
        detail=(f"connected as {role}, which is a SUPERUSER and is exempt from "
                "every row-level security policy in the schema"
                if is_super else f"connected as {role}, not a superuser"),
        closes_it=("point CROWN_DSN at crown_app. A managed database hands you "
                   "an administrative user and it is the obvious one to paste "
                   "in; it bypasses all twenty policies and nothing would say "
                   "so"),
    ))

    # BYPASSRLS defeats FORCE ROW LEVEL SECURITY specifically, which is the
    # thing the schema relies on to constrain even a table's owner.
    checks.append(Check(
        code="THE_APPLICATION_ROLE_CANNOT_BYPASS_RLS",
        severity=BLOCKING,
        passes=not bypasses,
        detail=(f"{role} has BYPASSRLS, which defeats FORCE ROW LEVEL SECURITY"
                if bypasses else f"{role} is subject to row-level security"),
        closes_it=f"ALTER ROLE {role} NOBYPASSRLS, or connect as crown_app",
    ))

    # Every RLS table is FORCEd today. Without FORCE, the table's owner is
    # exempt from its own policies — so a table added later without it would
    # quietly open a hole that no test of the policies themselves would catch.
    unforced = conn.execute(
        """SELECT count(*), coalesce(string_agg(relname, ', ' ORDER BY relname), '')
           FROM pg_class
           WHERE relkind = 'r' AND relrowsecurity AND NOT relforcerowsecurity"""
    ).fetchone()
    n, names = (unforced[0], unforced[1]) if unforced else (0, "")
    checks.append(Check(
        code="ROW_LEVEL_SECURITY_APPLIES_TO_THE_OWNER",
        severity=BLOCKING,
        passes=n == 0,
        detail=(f"{n} table(s) have policies the owner is exempt from: {names}"
                if n else "every table with policies FORCEs them"),
        closes_it=("ALTER TABLE ... FORCE ROW LEVEL SECURITY. Without it the "
                   "owner is exempt from its own policies, which a test of the "
                   "policies alone would not notice"),
    ))
    return tuple(checks)


def check(conn, environ=None) -> Report:
    """Read every launch condition — the database's and the deployment's.

    Blocking failures first, so the thing that stops a launch is not below the
    thing that does not.
    """
    rows = conn.execute(
        """SELECT check_code, severity, passes, detail, closes_it
           FROM launch_readiness"""
    ).fetchall()

    checks = (tuple(Check(*row) for row in rows)
              + deployment_checks(environ)
              + connection_checks(conn))
    return Report(checks=tuple(sorted(
        checks, key=lambda c: (c.passes, not c.blocking, c.code))))
