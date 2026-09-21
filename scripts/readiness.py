#!/usr/bin/env python3
"""Ask whether Crown may be turned on, from a terminal or a deploy pipeline.

Exits 0 when every blocking check passes, 1 when any fails, so a pipeline can
refuse to promote a build that is not ready without anybody having to remember
to look. Advisory failures print and do not change the exit code.

    python scripts/readiness.py
    python scripts/readiness.py --dsn postgresql:///crown_ai
    python scripts/readiness.py --quiet        # exit code only
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg                                              # noqa: E402

from crown import readiness                                 # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", help="override CROWN_DSN")
    parser.add_argument("--quiet", action="store_true",
                        help="print nothing; the exit code is the answer")
    args = parser.parse_args(argv)

    dsn = args.dsn or os.environ.get("CROWN_DSN")
    if not dsn:
        print("set CROWN_DSN or pass --dsn", file=sys.stderr)
        return 2

    with psycopg.connect(dsn) as conn:
        report = readiness.check(conn)

    if not args.quiet:
        print(report.report())
        if report.blockers:
            print("\nNothing above is a bug. Each line names what would close "
                  "it.", file=sys.stderr)

    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
