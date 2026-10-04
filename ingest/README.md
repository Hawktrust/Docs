# Signal ingestion — Ticket 01, item 1

`SIGNAL -> EVIDENCE`, the first leg of the thin loop. Scoped to one source
(`VIC_PLANNING_AMENDMENTS`) and driven one LGA at a time.

```
python -m ingest.cli --lga Wyndham --amendment-list   # real amendments, per LGA
python -m ingest.cli --lga Wyndham                    # fetch the amendments index
python -m ingest.cli --lga Wyndham --from-file x.json # run on a saved payload
python -m ingest.cli --lga Wyndham --verify           # retrieve every queued lead
python -m ingest.cli --lga Wyndham --verify --workers 8   # ... several at once
python -m ingest.cli --lga Wyndham --revalidate       # ask the source what changed
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

## Where the real amendments come from

`--amendment-list` reads DTP's official *List of Amendments*, one PDF per planning
scheme, from the publisher's own production bucket — the object the portal's
`/config.json` names as `amendmentListUrl`. Each page is headed with the scheme
name and marked OFFICIAL, and each entry gives an amendment number, the date it
came into operation, and a description. Ingested 2026-09-27:

| LGA | Amendments | Earliest | Latest |
|---|---|---|---|
| Wyndham | 176 | 1999-11-18 | 2022-11-25 (`C264wynd`) |
| Melton | 155 | 1999-11-25 | 2023-07-13 (`C219melt`) |
| Hume | 191 | 2000-11-02 | 2023-07-27 (`C271hume`) |

`DIRECT_FETCH` / `AUTHORITATIVE` / `FACT` / `REAL`, with `source_url` set to the
PDF actually retrieved — never a portal page that was not. This is what makes
acceptance criterion 1 pass.

**Three limits, none of them hidden.** The list is behind the present:
`Last-Modified` 2024-08-22, newest entry 3 AUG 2023, so it is silent about every
amendment since, including all eleven queued leads. Every record carries the
document's own date in `list_as_at`. No geography finer than the LGA is claimed,
because extracting a suburb from prose is inference. And entries whose day the
document states ambiguously — `218 NOV 2005` is 18 or 28 or 21 — are skipped,
counted, and reported, with the CLI exiting 8 so a caller cannot miss it.

Statewide `VC` and `GC` amendments are excluded by default: VC238 changed all 79
schemes, so ingesting it would raise a CONFIRMED opportunity in every LGA in
Victoria on the strength of a provisions tweak that says nothing about anybody's
land. `--include-statewide` takes them.

## Still blocked: current amendments

The list gives history. Knowing about an amendment in the month it happens needs
the portal's API, and that is still refused:

| Host | Result |
|---|---|
| `api.app.planning.vic.gov.au` | blocked — **this is the one that matters** |
| `planning-schemes.app.planning.vic.gov.au` | reachable, and serves no data |
| `prd-vicplanning-app.s3.ap-southeast-2.amazonaws.com` | reachable — the amendment list above |
| `www.planning.vic.gov.au` | reachable, Cloudflare bot challenge; not ours to defeat |
| `data.vic.gov.au` | blocked |
| `www.wyndham.vic.gov.au` | blocked |
| `en.wikipedia.org` (control) | blocked |

Retested 2026-09-27 in the Crown Prospecting environment. The amendment portal is
open now and it did not help for the queued leads: it is a static Vue app, every
path returns the same 1.5 KB shell, and its own `/config.json` names `api.app.planning.vic.gov.au` as
the API holding the data. That hostname is still refused at the CONNECT tunnel.
`docs/EGRESS-ALLOWLIST-REQUEST.md` has the full retest table.

The proxy's own documentation says a policy denial must be reported rather than
routed around, so it has not been.

So the eleven queued leads are still queued, and the two CONTRADICTED ones are
still contradicted — both are more recent than the amendment list, so it cannot
settle them. Running `--verify` reaches all eleven and promotes none, which is the
correct outcome for eleven empty bodies:

```
$ python -m ingest.cli --lga Wyndham --verify
  C266wynd: ... was retrieved but not parseable: no verified parser exists ...
verified 0, still queued 11
$ echo $?
5
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

## Fetching several pages at once

`--workers N` retrieves N pages in parallel. It is off by default, and what it
does *not* parallelise is the point: pages are fetched concurrently and written
to the database one at a time, on the main thread, in the order the leads were
queued. A psycopg connection is not thread-safe, and an ingestion that wrote rows
from four threads would be impossible to review afterwards.

Two properties hold whatever N is, and `tests/test_concurrent_fetch.py` pins
them: results come back in the order they were asked for, and a URL that fails
comes back in place as its exception rather than being dropped. Requests to any
one host also stay at least `DEFAULT_MIN_INTERVAL_SECONDS` apart — eight workers
must not become eight simultaneous requests to a council's web server. Different
hosts are paced separately, so four councils at once is four polite conversations
rather than one queue.

Measured against the live amendment host: eleven leads in 13.5s serially, 3.8s
with eight workers, with the pacing still in force.

## Re-verification: asking instead of re-reading

`--revalidate` asks the source whether a document has changed, using the `ETag`
or `Last-Modified` the original retrieval stored (migration 0028). A `304 Not
Modified` is the publisher confirming the page Crown read is still the page it
serves — a stronger statement than re-parsing our own guess at the markup, and it
costs one small request instead of a document.

The three outcomes are kept distinguishable because they support different claims:

| | what moves |
|---|---|
| `304` unchanged | `last_verified_at` and `last_revalidated_at`. **Not** `retrieved_at` — Crown did not retrieve the document, and no record may imply a fetch that did not happen |
| `200` changed | nothing. It is reported and audited; re-ingesting needs the parser and the provenance checks, so it is a separate act |
| unreachable | nothing. The record keeps the verification date it honestly had |

Only `DIRECT_FETCH` records may carry a validator, and the schema enforces it. An
operator capture's `ETag` belongs to a person's browser request, not to one Crown
can repeat, so a later `304` against it would refresh a verification date on a
record the system has never fetched.

This matters beyond tidiness: migration 0026 measures evidence shelf life from
`last_verified_at`, so a column that could never be refreshed honestly was
deciding what `NO_EVIDENCE_IS_PAST_ITS_SHELF_LIFE` reports.

## Tests

```
CROWN_ADMIN_DSN=postgresql://postgres:...@127.0.0.1:5432/postgres python -m pytest tests/ -q
```

Each test builds a throwaway database from `migrations/0001_ticket01_thin_loop.sql`
and drops it afterwards. Fixture amendments are prefixed `TEST-` and never touch
a database anyone reads a figure from.
