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


def check(conn) -> Report:
    """Read every launch condition. Blocking failures first, so the thing that
    stops a launch is not below the thing that does not."""
    rows = conn.execute(
        """SELECT check_code, severity, passes, detail, closes_it
           FROM launch_readiness"""
    ).fetchall()

    checks = tuple(Check(*row) for row in rows)
    return Report(checks=tuple(sorted(
        checks, key=lambda c: (c.passes, not c.blocking, c.code))))
