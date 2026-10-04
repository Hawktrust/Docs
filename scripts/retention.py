#!/usr/bin/env python3
"""Apply Crown's retention periods.

    python scripts/retention.py                 # show what is due, change nothing
    python scripts/retention.py --apply         # destroy or de-identify it

Defaults to a dry run. A sweep that acts by default is one somebody runs by
accident against the wrong database, and this one cannot be undone.

For a scheduler:

    30 3 * * 0  cd /srv/crown && CROWN_DSN=... python scripts/retention.py --apply
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crown import db, retention    # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="actually destroy or de-identify; default is a dry run")
    parser.add_argument("--dsn", help="override CROWN_DSN")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    try:
        with db.connect(args.dsn) as conn:
            rows = retention.apply(conn, dry_run=not args.apply)
            conn.commit()
    except Exception as exc:                       # noqa: BLE001
        print(f"retention run failed: {exc}", file=sys.stderr)
        return 1

    if not rows:
        if not args.quiet:
            print("nothing is past its retention period")
        return 0

    verb = "removed" if args.apply else "would remove"
    if not args.quiet:
        for category, table, object_id, _ in rows:
            print(f"{verb}: {category} {table} {object_id}")
    print(f"{verb} {len(rows)} record(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
