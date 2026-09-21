# Egress allowlist request

Acceptance criterion 1 cannot pass until one host is reachable from the build
environment. This is the list to hand to whoever controls the network policy.

Re-tested **2026-09-21**. Every host below still answers `403`, and the proxy
names the reason: `gateway answered 403 to CONNECT (policy denial or upstream
failure)`. That is an organisation policy denial, not a fault at the far end and
not something a retry fixes. `en.wikipedia.org` is refused too, as a control, so
this is a blanket policy rather than a per-host block.

**Nothing in this document is a workaround.** Two routes exist that do not need
a policy change at all, and they are at the bottom: a person with a browser, and
asking the publisher. Only the allowlist unblocks the automated path.

## Required for Ticket 01

| Host | Why | Status |
|---|---|---|
| `planning-schemes.app.planning.vic.gov.au` | Canonical amendment pages. Serves `/{Scheme}/amendments/{Number}` — the exact URLs of the leads already queued in `evidence_review_queue`. | 403 |
| `www.planning.vic.gov.au` | The amendments index. Also the DTP terms page behind the CC BY 4.0 position every reading in the register now rests on. | 403 |

The first is the one that matters. With it open,
`python -m ingest.cli --lga Wyndham --verify` retrieves each queued lead and
promotes it into the graph; that path is built and tested.

## Worth permitting in the same change

Grouped by what they unlock. None is required for Ticket 01; all are registered
in `data_source` with a position on their terms, so a policy change is the only
thing between them and use.

**Planning permit activity — the register work of 2026-09-21**

| Host | Why | Register row |
|---|---|---|
| `reporting.ppars.planning.vic.gov.au` | Statewide planning permit activity reporting, monthly, from every responsible authority. Replaces scraping seven council sites. | `VIC_PPARS`, PERMITTED |
| `discover.data.vic.gov.au`, `data.vic.gov.au` | DataVic catalogue and bulk open data, including Casey's planning permit register with a documented API. | `COUNCIL_CASEY`, PUBLISHER_FEED |

**Spatial and gazettal**

| Host | Why | Register row |
|---|---|---|
| `plan-gis.mapshare.vic.gov.au` | Vicplan ArcGIS REST: zones and overlays as machine-readable JSON. Feeds `parcel_planning`. | `VICMAP_PLANNING` |
| `emapdev.ffm.vic.gov.au` | eMap FFM ArcGIS REST: flood database, fire history. | — |
| `www.legislation.vic.gov.au` | Government Gazette, where gazettal of an amendment is legally published. | — |
| `data-planvic.opendata.arcgis.com` | VPA open data: PSP boundaries and approved land use. | `VPA_PSP` |

**Councils** — `www.wyndham.vic.gov.au`, `www.melton.vic.gov.au`,
`www.hume.vic.gov.au`, `www.whittlesea.vic.gov.au`, `www.casey.vic.gov.au`,
`www.geelongcity.vic.gov.au`, `greatershepparton.com.au`.

Requested to **read their terms**, not to crawl them. Five of the seven are
`UNKNOWN` in the register precisely because their terms could not be fetched,
and one — Greater Geelong — is recorded `PROHIBITED` on a relayed reading that
should be confirmed against the page itself. Opening these closes a compliance
gap whether or not a single record is ever ingested.

The endpoint structure of the two ArcGIS hosts is documented in a third-party
repository, `uprez-net/propure-main`, at
`docs/adr/003-victoria-planning-data-endpoints.md`. That is one company's
engineering note dated 2026-01-15, not a Victorian government specification, and
nothing in it has been verified against the live services because they are
unreachable from here. Treat it as a lead. It covers zones, overlays and hazard
layers only — it does not ingest amendments at all.

## What is reachable

The Anthropic API, GitHub, and the package registries (`pypi.org`,
`files.pythonhosted.org`, npm, crates, Go). Nothing else. `WebFetch` is refused
for every domain.

## Routes already ruled out

- **Server-side web search.** Reaches the pages and returns real identifiers,
  but its detail contradicted itself under cross-checking — two searches gave
  different gazettal dates for C232melt and described different amendments under
  C272hume. It failed visibly again on 2026-09-21, returning three councils'
  community-engagement platform terms in place of the councils' own. Good enough
  for leads and for knowing what to go and read; never good enough for evidence.
  Everything it produced is marked as relayed in the register.
- **A GitHub mirror of the data.** Searched; none exists. Fetching Victorian
  planning content *through* an allowed host would be circumventing the policy
  rather than satisfying it, and is not attempted.
- **Tunnelling or otherwise routing around the denial.** Not attempted. The
  proxy's own documentation is explicit that a policy denial is to be reported.

## The two routes that need no policy change

**1. A person with a browser.** This is not a workaround — it is the publisher's
own page, opened by a named human, which is ordinary permitted use under every
set of terms read so far. The tooling is built and tested:

1. Open the amendment page.
2. Open `tools/collector.html` (or click the bookmarklet in
   `tools/capture-bookmarklet.js`), paste the page source, confirm each field.
3. `python -m ingest.cli --capture crown-capture-<hash>.json --as you@crown.local`

The bundle carries a sha256 that is recomputed on import, the raw HTML is
retained in `capture_artifact`, and `captured_by` names the person. Migration
0006 grades it `OPERATOR_CAPTURE`: it may be `STRONG`, so a gazetted amendment
captured this way can be a `FACT` — but never `AUTHORITATIVE`, which stays
reserved for a fetch the system made and can repeat. **AC1 passes on the first
bundle imported this way.**

**2. Ask the publisher.** DTP holds the register-level permit data behind PPARS
and publishes only activity statistics from it. Whether an extract naming
applicants and addresses is available, and on what terms, is a question with one
answer for the whole state. It is worth asking before any engineering.
