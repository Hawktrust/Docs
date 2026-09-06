# Signal ingestion — Ticket 01, item 1

`SIGNAL -> EVIDENCE`, the first leg of the thin loop. Scoped to one source
(`VIC_PLANNING_AMENDMENTS`) and driven one LGA at a time.

```
python -m ingest.cli --lga Wyndham                    # fetch the source live
python -m ingest.cli --lga Wyndham --from-file x.json # run on a saved payload
```

`CROWN_DSN` sets the connection. The pipeline connects as an ordinary
application role, never as the schema owner — see the RLS note in
`migrations/README.md` for why that matters.

## What a run does, per amendment

1. Resolves the source through the data rights register. A source that is
   absent, or registered with `is_ingestible = false`, is refused before any
   network call — `RP_DATA_SEAT` cannot be reached even by accident.
2. Lands the raw payload in `raw_ingest`, keyed `(source_id, source_ref,
   content_hash)`. A re-run of the same payload is a no-op.
3. Validates provenance against the twelve mandatory fields.
4. Writes an `evidence_record`, or routes the failure to
   `evidence_review_queue` with the missing field names.
5. Writes one `audit_event` row per transition, all sharing a run correlation id.

Classification is a rule, stated once in `adapters/vic_planning.py`: gazetted is
`FACT`, exhibited-but-undecided is `HYPOTHESIS`, anything else is `UNKNOWN`.
Ingestion never emits `INFERENCE` — an inference is something Crown concluded,
and ingestion concludes nothing.

## Blocked: no live data has been ingested

**No real amendment has been ingested, for Wyndham or any other LGA.** Egress to
`planning.vic.gov.au` and `data.vic.gov.au` is denied by the session's
organization network policy — the proxy answers `403` to the CONNECT, and its
own documentation says such denials must be reported rather than routed around.

Running the live path produces exactly this, and writes nothing:

```
$ python -m ingest.cli --lga Wyndham
retrieval failed, nothing ingested: GET https://www.planning.vic.gov.au/... 
  (Caused by ProxyError('Tunnel connection failed: 403 Forbidden'))
$ echo $?
3
```

That is the intended behaviour. A failed retrieval yields no rows at all, rather
than placeholder evidence that would later be indistinguishable from the real
thing.

Two consequences worth being explicit about:

- **Acceptance criterion 1 cannot be met from this environment.** It requires a
  real, current amendment from each of Wyndham, Melton and Hume with complete
  provenance. Unblocking the host is a prerequisite, not a detail.
- **There is no parser for the live page.** `from_html()` raises
  `SourceFormatUnknown` on purpose. The page has never been observed from here,
  and a parser written against a guessed DOM would emit records carrying real
  URLs and real retrieval timestamps around content that was never checked —
  a build that looks correct and is not. The parser should be written once
  against the real markup, and `test_live_page_parser_refuses_to_guess` should
  be replaced at that point.

Everything downstream of the parser is implemented and tested, so the work to
finish item 1 is: allowlist the host, observe the page, write `from_html`.

## Tests

```
CROWN_ADMIN_DSN=postgresql://postgres:...@127.0.0.1:5432/postgres python -m pytest tests/ -q
```

Each test builds a throwaway database from `migrations/0001_ticket01_thin_loop.sql`
and drops it afterwards. Fixture amendments are prefixed `TEST-` and never touch
a database anyone reads a figure from.
