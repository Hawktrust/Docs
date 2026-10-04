# Lara verification — Greater Geelong

**Status: PARTIAL.** Two of the three amendments are established in full. The
third, the NWGGA precinct question and C487ggee's locality are not.

**Provenance: relay-rendered, not a direct fetch.** Everything below was
obtained by a third-party fetcher rendering DTP's own pages. The quoted text is
verbatim rather than summarised, which is stronger than the September search
relay, but Crown did not fetch the bytes and cannot attest they came from DTP.
So **nothing here has been promoted into the evidence graph.** These remain
leads in `evidence_review_queue`, with richer claims attached. A direct fetch
from an environment with egress is what would make them `DIRECT_FETCH` /
`AUTHORITATIVE` / `FACT`.

Source pages, both retrieved 2026-10-04:
- `https://planning-schemes.app.planning.vic.gov.au/Greater%20Geelong/amendments/C444ggee`
- `https://planning-schemes.app.planning.vic.gov.au/Greater%20Geelong/amendments/C453ggee`

Scheme context, as the portal states it: *"Planning scheme last updated by VC323
on Friday 02 October 2026."* Greater Geelong carries 711 amendments in total.

---

## 1. The headline: C444ggee and C453ggee are a coordinated pair, not a conflict

This corrects the reading recorded in `seeds/relay_leads.json` on 2026-10-02 and
repeated to Crown in conversation. The note there said *"two live amendments over
one landholding with competing zoning"* and advised believing neither status
until both pages were read. Both pages have now been read, and the two
amendments are not in competition. They are being processed together:

| | C444ggee | C453ggee |
|---|---|---|
| Status | Approval Under Consideration | Approval Under Consideration |
| Exhibition start | Wed 08 October 2025 | Wed 08 October 2025 |
| Submissions due / exhibition end | Sun 16 November 2025 | Sun 16 November 2025 |
| Panel requested | Tue 27 January 2026 | Tue 27 January 2026 |
| Panel appointed | Wed 11 February 2026 | Wed 11 February 2026 |
| Planning authority decision | **Adopted** | **Adopted** |
| Decision date | **Mon 24 August 2026** | **Mon 24 August 2026** |
| Outcome | Pending | Pending |
| Gazettal | *(none recorded)* | *(none recorded)* |
| Last updated | Thu 03 September 2026 | Fri 04 September 2026 |
| Planning authority | Greater Geelong City Council | Greater Geelong City Council |

Identical exhibition window, identical panel, adopted the same day. These were
exhibited as a package and decided as a package.

**What they actually do** is split one growth front into a residential part and
an industrial part:

- **C444ggee** — rezones 76-156 Canterbury Road East and 705-765, **775** and
  785-805 Princes Highway, Lara, from Farming Zone to **General Residential Zone
  Schedule 1 (GRZ1)**, applying the Environmental Audit Overlay (EAO) and
  Development Plan Overlay Schedule 48 (DPO48).
- **C453ggee** — rezones 76-156 Canterbury Road East, 705-765 and 785-805
  Princes Highway and **610 Rennie Street**, Lara, from Farming Zone to
  **Industrial 1 Zone (IN1Z)** and **Industrial 3 Zone (IN3Z)**, applying Design
  and Development Overlay Schedule 55 (DDO55), **to facilitate the development of
  the Lara Business Park**.

The address ranges are textually overlapping — both name 76-156 Canterbury Road
East and the 705-765 and 785-805 Princes Highway parcels — because a single
title can be split between the two rezonings. C444ggee uniquely adds 775 Princes
Highway; C453ggee uniquely adds 610 Rennie Street. **The precise boundary between
the residential and industrial parts is not established here** and would need the
Explanatory Report or the amendment maps, which the portal itself flags: *"The
description below is a brief summary... To verify content of the final approved
amendment see the Explanatory Report."*

## 2. Why "Adopted, outcome Pending" is the stage that matters

Both amendments have cleared exhibition, cleared a panel, and been **adopted by
the council on 24 August 2026**. They now sit with the Minister for approval, and
neither has been gazetted. For prospecting that is the sharpest possible moment:
the rezoning is no longer speculative, the council has committed, and the land is
still Farming Zone on the ground until gazettal.

## 3. What is NOT established

| Question | State |
|---|---|
| C477ggee (Greater Avalon Employment Precinct West) | **NOT ESTABLISHED.** Its detail page was not retrieved. Only the brief description from the amendment list is on file. |
| C487ggee — which UGZ3 precinct, and is it Lara? | **NOT ESTABLISHED.** Schedule 3 to Clause 37.07 was not read. It names a Railway Station Carpark and no locality. Lara has a station, which is a reason to read the schedule, not a reason to call it Lara. |
| Which NWGGA precincts fall in Lara | **NOT ESTABLISHED.** VPA lists seven PSPs — state-led Batesford North, McCanns Lane/Merrawarp, Batesford South, Heales Road East; council-led Creamery Road, Elcho Road West, Elcho Road East — and says it is still *"reviewing the existing body of work and scoping the project program"* with no definitive timeline. Heales Road and Elcho Road are Lara roads, but a precinct boundary has **not** been inferred from a road name. |
| Is `prd-vicplanning-app.s3.ap-southeast-2.amazonaws.com` DTP's own document store? | **NOT ESTABLISHED.** Nothing retrieved here points at that bucket. It was named by a session that could not substantiate it. Do not ingest from it until an API response or DTP page is shown to reference it — the CC BY 4.0 position in the data rights register is DTP's and does not travel to a third party's bucket. |

## 4. Egress, as measured

From the no-allowlist environment (`env_015vPXTkGYMDNbkZbf1EdJ98`, "Docs"),
2026-10-02:

```
https://www.planning.vic.gov.au/     curl: (56) CONNECT tunnel failed, response 403
https://api.app.planning.vic.gov.au/ curl: (56) CONNECT tunnel failed, response 403
https://vpa.vic.gov.au/              curl: (56) CONNECT tunnel failed, response 403
```

`www.planning.vic.gov.au` additionally sits behind a Cloudflare bot
interstitial at the origin. An allowlist entry does not defeat that, and a
spoofed user-agent is ruled out: getting the bytes that way would misdescribe
`retrieval_method`, which is the one thing this schema exists to prevent. The
content is reachable through the API instead.

`planning-schemes.app.planning.vic.gov.au` is a Vue single-page app. A direct
fetch returns a ~1.5KB empty shell and a `200`, which is why an earlier attempt
looked like a success and carried nothing. The content is behind
`api.app.planning.vic.gov.au`. **An allowlist that permits the portal but not the
API permits the shell and not the data.**

## 5. Why two sessions in the Crown Prospecting environment delivered nothing

Both `session_01DuTwSpWnwg5Cu5Mx7tGnxv` and
`session_01AszBVFn213wC9wNoAePAY6` ran in `env_018LhDUE8DAFRNybsGenzTQ5`
("Crown Prospecting"), did substantial work, and pushed nothing. The second one
diagnosed it: it wrote its findings to `/home/user/LARA-VERIFICATION.md` — the
home directory, not the repository — and asked for `add_repo` for
`hawktrust/docs`.

**That environment has no repository source configured, and its sessions are
given no GitHub or session-management tools.** A session there can reach the web
and cannot touch the repo: no clone, no remote, no branch, therefore no push, no
matter how the instruction is worded. The first session's confusing complaint
about "repo access to `ingest/verify.py`" was literally true and I discounted it.

The fix is a configuration change to that environment — add `hawktrust/docs` as a
source — not a better prompt. Until then, work needing both egress and the
repository cannot be done in one place: that environment has the network, this
one has the repository.

## 6. Did the relay's reliability finding hold for Greater Geelong?

**No, and in the relay's favour.** `seeds/relay_leads.json` records that the
September relay was *"reliable for identifiers and URL structure, and unreliable
for detail"* — two searches for `C232melt` disagreed on a gazettal date, two for
`C272hume` described different amendments.

For Greater Geelong the detail was accurate. The brief descriptions matched
verbatim, and the status the relay reported for C444ggee — "Approval Under
Consideration" — is exactly what the page says. The difference is the mechanism:
September's leads came from search *summaries*, whereas these came from a fetcher
*rendering the page*. Those are different trust levels and the register should
stop treating them as one thing.

**What was wrong was not the relay. It was my inference from it** — reading two
amendments over shared addresses as competing, when the dates show a coordinated
pair. The relay reported facts correctly and the conclusion drawn from them was
wrong, which is the failure mode a provenance model does not catch.
