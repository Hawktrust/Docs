# Egress allowlist request

This is the list to hand to whoever controls the network policy. It is no longer
what stands between Crown and acceptance criterion 1 — see below — but it is still
what stands between Crown and knowing about an amendment in the month it happens.

Re-tested **2026-09-27** in the **Crown Prospecting** environment
(`env_018LhDUE8DAFRNybsGenzTQ5`), which was created specifically to open the
Victorian planning hosts. It did open them, though not the one that mattered.

**AC1 now passes**, by a route found while testing this: DTP's own official
*List of Amendments* PDF, served from the publisher's own bucket, which is
reachable. 522 real amendments across Wyndham, Melton and Hume, `DIRECT_FETCH`
and `AUTHORITATIVE`. The detail is under *The S3 bucket*, below.

**The request below still stands**, because that document is two years behind and
answers a different question. The list gives Crown the approved history of a
scheme; only the API gives it what changed this month, and it is the API that is
still refused.

## The finding about the portal, in one paragraph

`planning-schemes.app.planning.vic.gov.au` is now allowlisted and answers `200`.
All eleven queued leads were fetched successfully. **None of them yielded a
single byte of amendment content**, because that host is a static Vue
single-page app: every path on it — including every lead's canonical URL —
returns the same 1,551-byte shell whose `<body>` is `<div id="app"></div>`. The
app then reads its own `/config.json`, which names
`https://api.app.planning.vic.gov.au/planning/v2` as the API that holds the
data. **That host is a separate hostname and is still denied at CONNECT.** The
allowlist opened the shop front and not the warehouse. One more hostname closes
this.

## The one host still required for current amendment data

| Host | Why | Status 2026-09-27 |
|---|---|---|
| `api.app.planning.vic.gov.au` | **The amendment data itself.** Named by the portal's own `/config.json` as `apiUrl`. Serves `/planning/v2/…`, which is what the portal calls to render an amendment page. Nothing else serves this content. | **403 at CONNECT — policy denial** |

Verbatim, so it is not mistaken for a fault at the far end:

```
> CONNECT api.app.planning.vic.gov.au:443 HTTP/1.1
< HTTP/1.1 403 Forbidden
< Connection: close
* CONNECT tunnel failed, response 403
curl: (56) CONNECT tunnel failed, response 403
```

With it open, `python -m ingest.cli --lga Wyndham --verify` retrieves each queued
lead and promotes it. That path is built, tested, and — as of 2026-09-27 — proven
to reach the network correctly: all eleven leads fetched, `HTTP 200`. Only the
parse step fails, and only because there is nothing in the body to parse. It is
also the only way to resolve the two CONTRADICTED leads, which the amendment list
cannot touch because both are more recent than it.

`spatial.planning.vic.gov.au` (`mapUrl` in the same config) is also still
`403 at CONNECT`. It is not needed for Ticket 01.

## Hosts previously listed as 403 that are now open

The previous version of this document said every host answered `403` and that
this was "a blanket policy rather than a per-host block". That is no longer
true, and the distinction between *who* returns the 403 now matters.

| Host | Tunnel | Then what | Usable? |
|---|---|---|---|
| `planning-schemes.app.planning.vic.gov.au` | established | `HTTP 200` | Reachable, but serves no data. See above. |
| `www.planning.vic.gov.au` | established | `HTTP 403` from **Cloudflare**, not the proxy | No. See below. |
| `prd-vicplanning-app.s3.ap-southeast-2.amazonaws.com` | established | objects `200`; bucket listing `403 AccessDenied` from S3 | Partly. See below. |

### `www.planning.vic.gov.au` — allowed by policy, refused by Cloudflare

This host is **no longer a policy denial**. The proxy completes the tunnel
(`HTTP/1.1 200 Connection Established`) and the `403` comes from the origin:

```
< HTTP/2 403
< server: cloudflare
<!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title>
```

That is Cloudflare's bot interstitial — a JavaScript challenge served to a
non-browser client. **Nothing in this repository will attempt to solve it.**
Defeating a bot challenge is evasion, not retrieval, and a record obtained that
way would misrepresent how it was obtained. This host is wanted for the DTP
terms page behind the CC BY 4.0 position in the register; the right way to read
it is an operator with a browser, which is the route already built. No further
policy change is requested for it.

### The S3 bucket — real, official, and two years stale

`prd-vicplanning-app.s3.ap-southeast-2.amazonaws.com` is DTP's own production
bucket, named by the portal's `/config.json` as `amendmentListUrl`. It is
reachable, and it serves DTP's official *List of Amendments* PDF per scheme at
`amlist/amlist_s_{schemeCode}.pdf`. These were fetched successfully:

| Object | Bytes | `Last-Modified` | Newest amendment in it |
|---|---|---|---|
| `amlist/amlist_s_wynd.pdf` | 453,658 | 2024-08-22 | `VC238`, 3 AUG 2023 |
| `amlist/amlist_s_melt.pdf` | 485,975 | 2024-08-22 | `VC238`, 3 AUG 2023 |
| `amlist/amlist_s_hume.pdf` | 535,391 | 2024-08-22 | `VC238`, 3 AUG 2023 |
| `amlist/amlist_s_wsea.pdf` | 620,790 | 2024-08-22 | `VC238`, 3 AUG 2023 |

They are genuine: each is headed `LIST OF AMENDMENTS`, marked `OFFICIAL`, and
carries amendment number, *in operation from* date and description.

**This is now the route AC1 passes by, and the reasoning that first ruled it out
was wrong.** Recorded because the mistake is instructive.

The first reading of these files was that they could not satisfy AC1: they hold
only two of the eleven queued leads — `C261hume` (6 JUN 2022) and `C255wsea`
(22 OCT 2021) — which is two LGAs where AC1 wants three. That is true of the
queued leads and irrelevant to the criterion. AC1 asks for a real amendment from
each of three LGAs, not for those particular eleven. The lists carry the full
approved history of each scheme, so they answer it comfortably.

What was ingested on 2026-09-27, through `--amendment-list`:

| LGA | Amendments | Earliest | Latest |
|---|---|---|---|
| Wyndham | 176 | 1999-11-18 | 2022-11-25 (`C264wynd`) |
| Melton | 155 | 1999-11-25 | 2023-07-13 (`C219melt`) |
| Hume | 191 | 2000-11-02 | 2023-07-27 (`C271hume`) |

522 records, `DIRECT_FETCH` / `AUTHORITATIVE` / `FACT` / `REAL`, with
`source_url` set to the PDF that was actually retrieved. `REAL_EVIDENCE_EXISTS`
passes. Re-running ingests nothing and reports 176 duplicates, so AC2 still holds.

Three limits travel with it, and none is hidden:

1. **The list is behind the present.** `Last-Modified` 2024-08-22, newest entry
   3 AUG 2023, so it is silent about every amendment since — including all eleven
   queued leads. It cannot answer "what changed this month". Each record carries
   the document's own `Last-Modified` in `list_as_at` so a reader never has to
   assume otherwise. **This does not replace the allowlist request above**; it
   supplies history where the API would supply currency.
2. **No geography finer than the LGA.** The descriptions name streets in prose,
   and extracting a suburb from a sentence is inference. `geography` is left
   absent, so the opportunity rule falls back to the LGA.
3. **Four entries across the four lists were skipped, not guessed.** DTP's own
   text layer states some days ambiguously — `218 NOV 2005` is 18 or 28 or 21 —
   and a wrong gazettal date is exactly the failure the CONTRADICTED leads warn
   about. The run reports the count and the CLI exits 8 so a caller cannot miss it.

Statewide `VC` and `GC` amendments are read but not ingested by default. VC238
changed all 79 planning schemes; ingesting it would raise a CONFIRMED opportunity
in every LGA in Victoria on the strength of a provisions tweak that says nothing
about anybody's land. `--include-statewide` takes them.

## Worth permitting in the same change

All still `403 at CONNECT` on 2026-09-27. None is required for Ticket 01; all
are registered in `data_source` with a position on their terms, so a policy
change is the only thing between them and use.

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
nothing in it has been verified against the live services because they are still
unreachable from here. Treat it as a lead. It covers zones, overlays and hazard
layers only — it does not ingest amendments at all.

## What is reachable

The Anthropic API, GitHub, the package registries (`pypi.org`,
`files.pythonhosted.org`, npm, crates, Go), and — new in this environment —
`planning-schemes.app.planning.vic.gov.au`, `www.planning.vic.gov.au` (Cloudflare
challenge) and `prd-vicplanning-app.s3.ap-southeast-2.amazonaws.com`.

`en.wikipedia.org` is still `403 at CONNECT`, retested as a control. So the
policy is now a genuine per-host allowlist, not the blanket denial this document
previously described.

`robots.txt` on `planning-schemes.app.planning.vic.gov.au` permits what Crown
wants — it disallows only `*/search`, `*/amendments?q` and `*/404/*`, so
`/{Scheme}/amendments/{Number}` is allowed. `ingest.fetch` enforces robots, and
it did not block any of the eleven fetches.

## What the verified run actually produced

```
python -m ingest.cli --lga Wyndham --leads seeds/relay_leads.json
  queued 11 lead(s) for direct verification; none entered the graph

python -m ingest.cli --lga Wyndham --verify
  … 11 × "was retrieved but not parseable" …
  verified 0, still queued 11          (exit 5)
```

| Measure | Result |
|---|---|
| Leads fetched over the network | 11 of 11, `HTTP 200` |
| Leads promoted to evidence | **0** |
| `evidence_record` rows | **0** |
| Leads still unresolved in the queue | 11 of 11 |
| Audit events | 11 × `LEAD_QUEUED`, 11 × `LEAD_VERIFICATION_UNPARSEABLE` |
| Evidence grade achieved | **none** — from the leads. `AUTHORITATIVE` was reached the same day from the amendment list, by a different document |

No lead was promoted and no row from a lead claims any grade. `AUTHORITATIVE` —
which migration 0006's `retrieval_method_limits_reliability` reserves for
`DIRECT_FETCH` — was reached, but from the amendment list rather than from any of
these eleven pages. The pipeline behaved exactly as
designed: a fetch that returns nothing writes nothing, leaves the lead queued,
and records why. `LEAD_VERIFICATION_UNPARSEABLE` rather than
`LEAD_VERIFICATION_BLOCKED` is the honest distinction — the page was reached.

`scripts/readiness.py` reported, before the amendment list was ingested:

```
[BLOCK] REAL_EVIDENCE_EXISTS: 0 evidence record(s) with origin REAL
```

and after:

```
[ pass] REAL_EVIDENCE_EXISTS: 522 evidence record(s) with origin REAL
```

### The two contradicted leads are still contradicted

`C232melt` (two different gazettal dates) and `C272hume` (two substantively
different descriptions) were to be settled by the page itself. They were not.
Nothing was retrieved that bears on either, so both discrepancies stand open and
`corroboration: CONTRADICTED` in `seeds/relay_leads.json` remains correct. No
relay claim has been promoted, and none should be.

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
- **Solving the Cloudflare challenge on `www.planning.vic.gov.au`.** Not
  attempted, and should not be. The host is permitted by policy; the origin is
  refusing a non-browser client. Presenting as a browser to get past it is
  evasion, and it would put a record in the graph whose stated retrieval method
  misdescribes how it was obtained.
- **Tunnelling or otherwise routing around the denial.** Not attempted. The
  proxy's own documentation is explicit that a policy denial is to be reported.
  `HTTPS_PROXY` was not unset and TLS verification was not disabled.

## The two routes that need no policy change

**1. A person with a browser.** This is not a workaround — it is the publisher's
own page, opened by a named human, which is ordinary permitted use under every
set of terms read so far. It is now the *only* route to a real record, and the
2026-09-27 findings strengthen the case for it: a browser runs the JavaScript
that the portal requires, so it sees the amendment that no HTTP client on the
current allowlist can see. The tooling is built and tested:

1. Open the amendment page.
2. Open `tools/collector.html` (or click the bookmarklet in
   `tools/capture-bookmarklet.js`), paste the page source, confirm each field.
3. `python -m ingest.cli --capture crown-capture-<hash>.json --as you@crown.local`

The bundle carries a sha256 that is recomputed on import, the raw HTML is
retained in `capture_artifact`, and `captured_by` names the person. Migration
0006 grades it `OPERATOR_CAPTURE`: it may be `STRONG`, so a gazetted amendment
captured this way can be a `FACT` — but never `AUTHORITATIVE`, which stays
reserved for a fetch the system made and can repeat. **AC1 passes on the third
bundle imported this way — one per LGA.**

**2. Ask the publisher.** DTP holds the register-level permit data behind PPARS
and publishes only activity statistics from it. Whether an extract naming
applicants and addresses is available, and on what terms, is a question with one
answer for the whole state. It is worth asking before any engineering. The same
conversation can settle whether `api.app.planning.vic.gov.au` may be called by a
non-browser client at all, which is worth knowing before the allowlist change
above is made.
