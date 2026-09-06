# Egress allowlist request

Acceptance criterion 1 cannot pass until one host is reachable from the build
environment. This is the list to hand to whoever controls the network policy.

Everything below was tested on 2026-09-06. A `403` is the egress gateway
answering the CONNECT — an organisation policy denial, not a fault at the far
end and not something a retry fixes.

## Required for Ticket 01

| Host | Why | Status |
|---|---|---|
| `planning-schemes.app.planning.vic.gov.au` | Canonical amendment pages. Serves `/{Scheme}/amendments/{Number}` — the exact URLs of the seven leads already queued in `evidence_review_queue`. | 403 |
| `www.planning.vic.gov.au` | The amendments index, and the licence and attribution wording the data rights register still needs confirmed. | 403 |

The first of these is the one that matters. With it open,
`python -m ingest.cli --lga Wyndham --verify` retrieves each queued lead and
promotes it into the graph; that path is built and tested.

## Not required for Ticket 01, but worth permitting together

| Host | Why | Status |
|---|---|---|
| `plan-gis.mapshare.vic.gov.au` | Vicplan ArcGIS REST: planning scheme zones and overlays as machine-readable JSON. | 403 |
| `emapdev.ffm.vic.gov.au` | eMap FFM ArcGIS REST: Victorian flood database, fire history. | 403 |
| `www.legislation.vic.gov.au` | Government Gazette, where gazettal of an amendment is actually published. | 403 |
| `www.wyndham.vic.gov.au`, `www.melton.vic.gov.au`, `www.hume.vic.gov.au` | Council amendment pages: exhibition documents and panel reports the state site links to but does not host. | 403 (Wyndham tested) |
| `data.vic.gov.au` | Bulk open data, if an ETL route is ever preferred to live reads. | 403 |

The three GIS and gazette hosts are outside Ticket 01's single signal source and
are listed only so one policy change covers the next ticket as well. **No data
source row has been added for any of them** — the register still holds exactly
two sources, and adding more is a decision for whoever scopes Ticket 02.

Their endpoint structure is documented in a third-party repository,
`uprez-net/propure-main`, at `docs/adr/003-victoria-planning-data-endpoints.md`.
That is one company's engineering note, not a Victorian government
specification: it is dated 2026-01-15, and nothing in it has been verified
against the live services, because they are unreachable from here. Treat it as a
lead. It documents zones, overlays and hazard layers only — it does not ingest
planning scheme amendments at all, and treats them merely as a signal to refresh
its zoning cache.

## What is reachable

The allowlist currently permits the Anthropic API, GitHub
(`api.github.com`, `raw.githubusercontent.com`), and the package registries
(`pypi.org`, `files.pythonhosted.org`, npm, crates, Go). Nothing else.

`WebFetch` is refused for every domain, including `en.wikipedia.org` as a
control, so it is not an alternative route to any of the hosts above.

## Routes already ruled out

- **Server-side web search.** Reaches the pages and returns real amendment
  identifiers, but its detail contradicted itself under cross-checking — two
  searches gave different gazettal dates for C232melt and described different
  amendments under C272hume. Good enough for leads, not for evidence. See
  `ingest/README.md`.
- **A GitHub mirror of the data.** Searched; none exists.
- **Tunnelling or otherwise routing around the denial.** Not attempted. The
  proxy's documentation is explicit that a policy denial is to be reported.

## If the allowlist cannot change

Save an amendment page from a browser and the pipeline runs on it today:

```
python -m ingest.cli --lga Wyndham --from-file saved-amendments.json
```

The interchange shape is documented at the top of
`ingest/adapters/vic_planning.py`. A saved copy of one real page is also what is
needed to write `from_html`, which is deliberately unimplemented rather than
guessed.
