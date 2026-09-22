#!/usr/bin/env python3
"""Sign a data rights register entry, and turn the source on.

    python scripts/confirm_source.py VICMAP_PROPERTY --adviser "Your Name"

Being in the register is not permission to ingest. The register's own rule is
that a named adviser confirms an entry first; this is that act, recorded with
who and when, and audited. It refuses to turn on a source that is missing the
licence or attribution wording, because those are what a confirmation is
confirming.
"""
import argparse
import os
import sys

# Run from anywhere: `python scripts/x.py` puts scripts/ on the path,
# not the repository root, so `crown` would not import. The other
# scripts in this folder do the same.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crown import audit, db    # noqa: E402

BLOCKED_LANES = ("BLOCKED", "C_DERIVED_ONLY")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("code", help="the source code, e.g. VICMAP_PROPERTY")
    parser.add_argument("--adviser", required=True,
                        help="the named person taking responsibility for this entry")
    parser.add_argument("--agreement",
                        help="for a Lane A source: the reference of the signed "
                             "agreement on file. A link to a product page is not "
                             "an agreement.")
    parser.add_argument("--privacy-basis", dest="privacy_basis",
                        help="for a source that identifies people: the basis for "
                             "the intended use — which APP is relied on, the "
                             "consent position, and where the suppression list is")
    parser.add_argument("--dsn", help="override CROWN_DSN")
    parser.add_argument("--list", action="store_true",
                        help="show the register and stop")
    args = parser.parse_args(argv)

    with db.connect(args.dsn) as conn:
        if args.list:
            for entry in conn.execute(
                """SELECT code, lane::text, is_ingestible,
                          coalesce(register_confirmed_by, '—')
                   FROM data_source ORDER BY lane, code""").fetchall():
                print(f"  {entry[0]:26s} {entry[1]:15s} "
                      f"{'ingestible' if entry[2] else 'off':11s} {entry[3]}")
            return 0

        row = conn.execute(
            """SELECT id, lane::text, licence_reference, attribution_text,
                      register_confirmed_by, carries_personal_information
               FROM data_source WHERE code = %s""", (args.code,)).fetchone()
        if row is None:
            print(f"{args.code} is not in the register", file=sys.stderr)
            return 1

        source_id, lane, licence, attribution, already, personal = row
        if already:
            print(f"{args.code} was already confirmed by {already}", file=sys.stderr)
            return 1
        if lane in BLOCKED_LANES:
            print(f"{args.code} is lane {lane} and cannot be made ingestible. "
                  f"The database constraint refuses it, and so does this.",
                  file=sys.stderr)
            return 2
        missing = [name for name, value in
                   (("licence_reference", licence), ("attribution_text", attribution))
                   if not value]
        if missing:
            print(f"{args.code} is missing {', '.join(missing)}. A confirmation "
                  f"confirms those; fill them before signing.", file=sys.stderr)
            return 2

        # Lane A means somebody signed something. A URL is not that.
        if lane == "A_LICENSED" and not args.agreement:
            print(f"{args.code} is lane A_LICENSED and needs --agreement with the "
                  f"reference of the signed agreement on file. The licence_reference "
                  f"currently on the row is {licence!r}, which is a link, not an "
                  f"agreement.", file=sys.stderr)
            return 2

        # Holding is not using. A source that identifies people needs a basis for
        # the use Crown intends, and the database will refuse it without one.
        if personal and not args.privacy_basis:
            print(f"{args.code} identifies living individuals. Turning it on needs "
                  f"--privacy-basis: which APP is relied on for the intended use, "
                  f"the consent position, and where the suppression list lives. A "
                  f"licence answers whether Crown may hold this; it does not answer "
                  f"whether Crown may use it to contact anyone.", file=sys.stderr)
            return 2

        conn.execute(
            """UPDATE data_source
               SET register_confirmed_by = %s, register_confirmed_at = now(),
                   is_ingestible = true,
                   licence_reference = coalesce(%s, licence_reference),
                   privacy_basis = coalesce(%s, privacy_basis)
               WHERE id = %s""",
            (args.adviser, args.agreement, args.privacy_basis, source_id))
        audit.write(conn, audit.new_correlation_id(), "SOURCE_REGISTER_CONFIRMED",
                    "data_source", source_id,
                    new_state={"code": args.code, "confirmed_by": args.adviser,
                               "is_ingestible": True,
                               "agreement": args.agreement,
                               "privacy_basis": args.privacy_basis},
                    actor_agent="scripts.confirm_source")
        conn.commit()

    print(f"{args.code} confirmed by {args.adviser} and is now ingestible")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
