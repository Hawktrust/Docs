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

**No amendment has entered the graph, for any LGA.** Egress from this environment
is a strict allowlist. Everything relevant is refused with a 403 at the CONNECT:

| Host | Result |
|---|---|
| `www.planning.vic.gov.au` | blocked |
| `planning-schemes.app.planning.vic.gov.au` | blocked |
| `data.vic.gov.au` | blocked |
| `www.wyndham.vic.gov.au` | blocked |
| `en.wikipedia.org` (control) | blocked |

The allowlist permits the Anthropic API, GitHub and the package registries, and
nothing else. `WebFetch` is refused for every domain, so it is not an alternative
route. The proxy's own documentation says a policy denial must be reported rather
than routed around, so it has not been.

Running the live path produces exactly this, and writes nothing:

```
$ python -m ingest.cli --lga Wyndham
retrieval failed, nothing ingested: ... ProxyError('Tunnel connection failed: 403 Forbidden')
$ echo $?
3
```

### What did get through, and why it is not evidence

One channel is open: a server-side web search, which does not pass through this
container's proxy. It returned **real amendment identifiers** for all three LGAs
and the canonical URL pattern
`https://planning-schemes.app.planning.vic.gov.au/{Scheme}/amendments/{Number}`.

It is not good enough to base evidence on, and this is measured rather than
assumed. Cross-checking each claim with a second, independently worded search:

- **C232melt** — one search reported gazettal on 7 May 2026, the other on
  8 May 2026.
- **C272hume** — one search described heritage design guidelines and seven added
  properties; the other described materials recycling at Merrifield and the
  deletion of HO259. Two different amendments under one number.

A summary of a page is not the page. Identifiers and URL structure survived
cross-checking because they come from the shape of the results rather than from
a summary of them; every date, title and status did not.

So the leads go to `evidence_review_queue` — the place the schema already
provides for records that cannot fill their mandatory provenance — and never into
the graph:

```
$ python -m ingest.cli --lga Wyndham --leads seeds/relay_leads.json
queued 7 lead(s) for direct verification; none entered the graph

$ python -m ingest.cli --lga Wyndham --verify
  C266wynd: ... could not be retrieved: 403 Forbidden
  ... (7 of 7)
verified 0, still queued 7
```

Migration 0003 makes this structural rather than a matter of discipline.
`evidence_record.retrieval_method` records how a record was actually obtained,
and a CHECK forbids anything but `DIRECT_FETCH` from being `AUTHORITATIVE` or
`STRONG`. Read with `fact_needs_strong_source` from 0001, that makes it
impossible for a relayed claim to be classified `FACT` — the database refuses,
whatever a future ingestion path believes.

### The way through that does not need the network policy to change

`tools/collector.html` — one self-contained file, opened in any browser, making
no network requests of its own. A named human pastes the real page into it, and
it produces a bundle the pipeline accepts:

```
python -m ingest.cli --capture crown-capture-....json --as you@crown.local
```

The raw bytes and their sha256 come with it and are retained, the hash is
recomputed on import, and the operator has to confirm every field. Migration
0006 grades it `OPERATOR_CAPTURE`: allowed to be `STRONG`, so a gazetted
amendment captured this way can be a `FACT`, but never `AUTHORITATIVE`. A
capture also closes the queued lead for that amendment.

This is the fastest route to acceptance criterion 1: three pages, one per LGA.

### What still finishes the automated path

Step 1 below is done, and it was not enough. That is the finding of 2026-09-27,
and it replaces the assumption this section used to carry.

1. ~~Allowlist `planning-schemes.app.planning.vic.gov.au`~~ — **done** in the
   Crown Prospecting environment. The host answers `200`.
2. **Allowlist `api.app.planning.vic.gov.au`.** This is the host that matters
   and the one nobody knew to ask for. `planning-schemes` is a static Vue app:
   every path on it, including each queued lead's canonical URL, returns the
   same 1.5 KB shell with no amendment content. The app reads its own
   `/config.json`, which names `https://api.app.planning.vic.gov.au/planning/v2`
   as the API. That host is still denied at CONNECT.
3. Run `python -m ingest.cli --lga Wyndham --verify`. It retrieves each queued
   lead's canonical URL and promotes it.
4. Write `from_html` against the real response, and replace
   `test_live_page_parser_refuses_to_guess`.

Steps 2 and 4 need a human. Step 3 is built and tested — `tests/test_relay_leads.py`
exercises the promotion path with an injected fetcher and shows a promoted record
arriving as `DIRECT_FETCH` / `AUTHORITATIVE` / `FACT`. Run live on 2026-09-27 it
fetched all eleven leads successfully and promoted none, because there was
nothing in any of the eleven bodies to promote.

There is still no parser for the live page, and `from_html()` still raises
`SourceFormatUnknown` — but for a sharper reason than before. The page has now
been observed, and what it contains is nothing. A parser cannot be written
against markup that does not exist, and one that produced a record anyway would
emit real URLs and real retrieval timestamps around content nobody was served.

## Tests

```
CROWN_ADMIN_DSN=postgresql://postgres:...@127.0.0.1:5432/postgres python -m pytest tests/ -q
```

Each test builds a throwaway database from `migrations/0001_ticket01_thin_loop.sql`
and drops it afterwards. Fixture amendments are prefixed `TEST-` and never touch
a database anyone reads a figure from.
