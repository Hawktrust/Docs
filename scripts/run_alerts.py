#!/usr/bin/env python3
"""Run the alert detectors once. This is what a scheduler calls.

`crown/alerts.py` has had five detectors and a deduplication key since migration
0012, and nothing has ever invoked them on a schedule. A detector nobody runs is
a detector that does not exist, so a watchlist quietly reported nothing and
looked exactly like a quiet day.

Safe to run as often as you like. Every alert computes a key from what it is
about and the database refuses a second one, so a re-run after a crash says
nothing twice.

    python scripts/run_alerts.py
    python scripts/run_alerts.py --dsn postgresql:///crown_ai --quiet

A daily entry is enough to start:

    15 7 * * *  cd /srv/crown && CROWN_DSN=... python scripts/run_alerts.py --quiet

Exits 0 when the pass completed, 1 when it failed. It does not exit non-zero
for a quiet day — nothing to report is an answer, not an error, and a scheduler
that alerts on it teaches people to ignore it.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg                                              # noqa: E402

from crown import alerts                                    # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", help="override CROWN_DSN")
    parser.add_argument("--quiet", action="store_true",
                        help="print only when something was raised")
    args = parser.parse_args(argv)

    dsn = args.dsn or os.environ.get("CROWN_DSN")
    if not dsn:
        print("set CROWN_DSN or pass --dsn", file=sys.stderr)
        return 2

    try:
        with psycopg.connect(dsn) as conn:
            report = alerts.run(conn)
            conn.commit()
    except psycopg.Error as exc:
        # The audit trail records decisions, not failures. A crashed run would
        # otherwise leave no trace anywhere at all, so it says so on stderr
        # where a scheduler will capture it.
        print(f"alert run failed: {exc}", file=sys.stderr)
        return 1

    if report.created or report.suppressed or not args.quiet:
        print(report.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
