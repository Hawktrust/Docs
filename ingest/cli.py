"""Run the ingestion for one LGA.

    python -m ingest.cli --lga Wyndham
    python -m ingest.cli --lga Wyndham --from-file saved.json

With no --from-file the pipeline fetches the registered source URL live. That is
the intended production path; it needs egress to the source host.
"""
import argparse
import io
import json
import sys
from datetime import datetime, timezone

from crown import db

from . import registry
from .adapters import vic_planning
from .fetch import Retrieval, RetrievalBlocked, fetch, fetch_many
from .pipeline import ingest

SOURCE_CODE = "VIC_PLANNING_AMENDMENTS"
# The amendments index for the LGAs in Ticket 01. Recorded here so the exact URL
# fetched is a reviewable constant, not a string built at runtime.
SOURCE_URL = "https://www.planning.vic.gov.au/guides-and-resources/amendments"


def _prefetch(targets, workers: int):
    """Retrieve every URL up front, then hand the results back one at a time.

    Returns a fetcher with the signature the verify paths already inject, so
    concurrency is confined to this function: the pipeline still writes one
    record at a time, on this thread, in the order the leads were queued. A
    psycopg connection is not thread-safe, and an ingestion that wrote rows from
    four threads would be impossible to review afterwards.

    With workers == 1 nothing is prefetched and the real fetcher is returned
    unchanged, so the default path is exactly what it was.
    """
    if workers <= 1 or not targets:
        return fetch

    urls = [t[0] for t in targets]
    validators = {url: (etag, last_modified) for url, etag, last_modified in targets
                  if etag or last_modified}
    results = fetch_many(urls, workers=workers, validators=validators)
    by_url = dict(zip(urls, results))

    def replay(url, timeout=30, *, etag=None, last_modified=None):
        result = by_url.get(url)
        if result is None:
            # Not prefetched — ask for it now rather than pretend it is missing.
            return fetch(url, timeout=timeout, etag=etag, last_modified=last_modified)
        if isinstance(result, Exception):
            raise result
        return result

    return replay


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
    parser.add_argument("--amendment-list", action="store_true",
                        help="ingest this LGA's amendments from DTP's official "
                             "List of Amendments PDF. Real, directly fetched from "
                             "the publisher's own bucket, and behind the present: "
                             "the list stops where DTP last regenerated it")
    parser.add_argument("--include-statewide", action="store_true",
                        help="with --amendment-list, also ingest VC and GC "
                             "amendments. Off by default: a statewide provisions "
                             "amendment changes all 79 schemes and signals nothing "
                             "about one geography")
    parser.add_argument("--revalidate", nargs="?", const=0, type=int,
                        metavar="N",
                        help="ask the source whether each directly-fetched record "
                             "has changed, oldest verification first; N limits how "
                             "many. Moves last_verified_at on a 304 and never "
                             "claims a fetch that did not happen")
    parser.add_argument("--capture", nargs="+", metavar="BUNDLE",
                        help="one or more bundles exported by the capture tools; "
                             "all three LGAs can go in one command")
    parser.add_argument("--workers", type=int, default=1, metavar="N",
                        help="fetch N pages at once during --verify or "
                             "--revalidate (default 1, serial). Pages are "
                             "retrieved in parallel and written to the database "
                             "one at a time; requests to any one host stay "
                             "spaced apart whatever N is")
    parser.add_argument("--as", dest="operator",
                        help="the email of the person who took the capture")
    args = parser.parse_args(argv)

    with db.connect(args.dsn) as conn:
        # The register decides whether this source may be touched at all.
        try:
            # A capture is a person with a browser, so it does not need the
            # publisher's terms to permit a crawler. Everything else does.
            source = registry.resolve(conn, SOURCE_CODE,
                                      automated=not bool(args.capture))
        except (registry.SourceNotRegistered, registry.SourceNotIngestible,
                registry.AutomatedAccessNotPermitted) as exc:
            print(f"refused by the data rights register: {exc}", file=sys.stderr)
            return 2

        if args.capture:
            from . import capture as capture_module
            if not args.operator:
                print("--capture needs --as you@crown.local: a capture is "
                      "attributable or it is not evidence", file=sys.stderr)
                return 2
            operator = conn.execute(
                "SELECT id FROM app_user WHERE email = %s AND is_active",
                (args.operator,)).fetchone()
            if operator is None:
                print(f"no active user {args.operator}", file=sys.stderr)
                return 2
            refused = 0
            for path in args.capture:
                try:
                    capture_report = capture_module.ingest_capture(
                        conn, source, capture_module.load(path), operator[0])
                except capture_module.BadCapture as exc:
                    # One bad bundle does not discard the good ones, but it is
                    # never quietly skipped either.
                    print(f"{path} refused: {exc}", file=sys.stderr)
                    conn.rollback()
                    refused += 1
                    continue
                conn.commit()
                print(capture_report.summary())
                print()
            if refused:
                print(f"{refused} of {len(args.capture)} bundle(s) refused",
                      file=sys.stderr)
            return 6 if refused else 0

        if args.leads:
            from . import leads as leads_module
            queued = leads_module.record(conn, source, leads_module.load(args.leads))
            conn.commit()
            print(f"queued {len(queued)} lead(s) for direct verification; "
                  f"none entered the graph")
            return 0

        if args.amendment_list:
            from .adapters import vic_amendment_list as amendment_list
            try:
                url = amendment_list.url_for(args.lga)
            except amendment_list.ListFormatUnexpected as exc:
                print(exc, file=sys.stderr)
                return 2
            try:
                fetched = fetch(url)
            except RetrievalBlocked as exc:
                print(f"retrieval failed, nothing ingested: {exc}", file=sys.stderr)
                return 3
            if not isinstance(fetched, Retrieval) or fetched.content is None:
                print(f"{url} returned no document body; nothing ingested",
                      file=sys.stderr)
                return 3
            try:
                parsed = amendment_list.from_pdf(
                    io.BytesIO(fetched.content), args.lga,
                    list_as_at=fetched.last_modified,
                    scheme_local_only=not args.include_statewide)
            except amendment_list.ListFormatUnexpected as exc:
                print(f"retrieved, but not the list this reads: {exc}",
                      file=sys.stderr)
                return 4
            print(parsed.summary())
            report = ingest(conn, source, fetched, parsed.records, args.lga)
            conn.commit()
            print(report.summary())
            # Entries whose date the document states ambiguously are not a
            # failure, but a run that reported only its successes would be
            # telling the reader something false by omission.
            return 8 if parsed.skipped else 0

        if args.revalidate is not None:
            from . import verify as verify_module
            limit = args.revalidate or None
            due = verify_module.revalidation_due(conn, limit=limit)
            counts = {"UNCHANGED": 0, "CHANGED": 0, "UNAVAILABLE": 0}
            replay = _prefetch(
                [(url, etag, last_modified)
                 for _id, url, etag, last_modified, _verified in due],
                args.workers)
            for evidence_id, url, _etag, _last_modified, _verified in due:
                try:
                    counts[verify_module.revalidate(
                        conn, evidence_id, fetcher=replay)] += 1
                except verify_module.VerificationFailed as exc:
                    print(f"  {url}: {exc}", file=sys.stderr)
            conn.commit()
            print(f"asked the source about {len(due)} record(s): "
                  f"{counts['UNCHANGED']} unchanged, {counts['CHANGED']} changed "
                  f"upstream, {counts['UNAVAILABLE']} could not be checked")
            # A record that changed upstream is not an error, but it is the one
            # outcome that needs a person: re-ingesting it is a separate act.
            return 7 if counts["CHANGED"] else 0

        if args.verify:
            from . import verify as verify_module
            ok = failed = 0
            queued = verify_module.pending(conn, source.id)
            replay = _prefetch([(lead["canonical_url"], None, None)
                                for _q, _s, lead in queued], args.workers)
            for queue_id, _, lead in queued:
                try:
                    verify_module.verify(conn, queue_id, source, fetcher=replay)
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
                fetched = fetch(SOURCE_URL)
            except RetrievalBlocked as exc:
                # Nothing was retrieved, so nothing is written. This is the
                # correct outcome for a failed fetch: no placeholder rows.
                print(f"retrieval failed, nothing ingested: {exc}", file=sys.stderr)
                return 3
            if not isinstance(fetched, Retrieval):
                # This fetch asked no conditional question, so a "not modified"
                # answer is meaningless here. Refusing beats ingesting a payload
                # from a body that was never sent.
                print(f"{SOURCE_URL} answered 'not modified' to an unconditional "
                      "request; nothing was asked, so nothing is ingested",
                      file=sys.stderr)
                return 3
            retrieval = fetched
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
