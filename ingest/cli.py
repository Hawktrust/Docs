"""Run the ingestion for one LGA.

    python -m ingest.cli --lga Wyndham
    python -m ingest.cli --lga Wyndham --from-file saved.json

With no --from-file the pipeline fetches the registered source URL live. That is
the intended production path; it needs egress to the source host.
"""
import argparse
import json
import sys
from datetime import datetime, timezone

from crown import db

from . import registry
from .adapters import vic_planning
from .fetch import Retrieval, RetrievalBlocked, fetch
from .pipeline import ingest

SOURCE_CODE = "VIC_PLANNING_AMENDMENTS"
# The amendments index for the LGAs in Ticket 01. Recorded here so the exact URL
# fetched is a reviewable constant, not a string built at runtime.
SOURCE_URL = "https://www.planning.vic.gov.au/guides-and-resources/amendments"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Crown AI signal ingestion")
    parser.add_argument("--lga", required=True, help="e.g. Wyndham")
    parser.add_argument("--from-file",
                        help="a saved payload in the adapter's interchange shape; "
                             "omit to fetch the registered source live")
    parser.add_argument("--dsn", help="override CROWN_DSN")
    parser.add_argument("--leads",
                        help="a relay leads file; queues the leads for direct "
                             "verification instead of ingesting")
    parser.add_argument("--verify", action="store_true",
                        help="attempt direct retrieval of every queued lead")
    args = parser.parse_args(argv)

    with db.connect(args.dsn) as conn:
        # The register decides whether this source may be touched at all.
        try:
            source = registry.resolve(conn, SOURCE_CODE)
        except (registry.SourceNotRegistered, registry.SourceNotIngestible) as exc:
            print(f"refused by the data rights register: {exc}", file=sys.stderr)
            return 2

        if args.leads:
            from . import leads as leads_module
            queued = leads_module.record(conn, source, leads_module.load(args.leads))
            conn.commit()
            print(f"queued {len(queued)} lead(s) for direct verification; "
                  f"none entered the graph")
            return 0

        if args.verify:
            from . import verify as verify_module
            ok = failed = 0
            for queue_id, _, lead in verify_module.pending(conn, source.id):
                try:
                    verify_module.verify(conn, queue_id, source)
                    ok += 1
                except verify_module.VerificationFailed as exc:
                    failed += 1
                    print(f"  {lead['amendment_number']}: {exc}", file=sys.stderr)
            conn.commit()
            print(f"verified {ok}, still queued {failed}")
            return 0 if failed == 0 else 5

        if args.from_file:
            with open(args.from_file) as fh:
                payload = json.load(fh)
            retrieval = Retrieval(
                url=SOURCE_URL,
                retrieved_at=datetime.now(timezone.utc),
                status_code=200,
                body="",
                content_type="application/json",
            )
        else:
            try:
                retrieval = fetch(SOURCE_URL)
            except RetrievalBlocked as exc:
                # Nothing was retrieved, so nothing is written. This is the
                # correct outcome for a failed fetch: no placeholder rows.
                print(f"retrieval failed, nothing ingested: {exc}", file=sys.stderr)
                return 3
            try:
                payload = vic_planning.from_html(retrieval.body, retrieval.url)
            except vic_planning.SourceFormatUnknown as exc:
                print(f"retrieved, but not parseable: {exc}", file=sys.stderr)
                return 4

        report = ingest(conn, source, retrieval, payload, args.lga)
        conn.commit()
        print(report.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
