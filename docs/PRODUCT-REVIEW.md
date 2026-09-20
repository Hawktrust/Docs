# Product review — where the vision leaks

A review of the Crown AI prospecting vision as described on 2026-09-20. The
ambition is right and most of it is buildable. What follows is where it leaks:
places where the product assumes data it cannot lawfully get, treats a
relationship as a database field, or produces a confident number from a weak
input.

Ranked by what would hurt most.

---

## 1. The RP Data seat would end the account, not unlock the product

**This is the most urgent item here.** Cotality's terms prohibit two things the
vision depends on:

> Systematic retrieval of information, services or products from the Services to
> create or compile, directly or indirectly, a collection, compilation, database,
> or directory without written permission from Cotality is prohibited.

and, specifically:

> Cotality is prohibited from offering any feature or service that would permit
> the Licensed Material to be searched by any name, such as the purchaser(s) name
> or vendor(s) name, and the Customer must not Access or Use the Licensed
> Material (such as systematic or bulk Downloads) for the purpose of carrying out
> or facilitating such a search.

Contravention means access "may be suspended or terminated immediately."

Read against the vision, a seat login cannot be used to:

- populate Crown's database with parcels, owners or sales — that is systematic
  retrieval to compile a database, verbatim
- **track which developer is buying** — that is a search by purchaser name, which
  the terms prohibit by name and which Cotality is itself barred from offering

Crown's own data rights register already says this. `RP_DATA_SEAT` sits in it as
`BLOCKED` with the note "Seat subscription only — no platform/API agreement on
file. Do not ingest, cache or redistribute." The register was right.

**What the seat is legitimately for:** a human opening one property, for one
deal, to check a fact. That is the product Cotality sold. Keep using it that way.

**The actual unlock** is the sentence "without written permission from Cotality."
A platform or API agreement is a real, purchasable thing and it is the
difference between a prohibited product and a licensed one. That is a commercial
conversation, not an engineering problem, and it is on the critical path for
half the vision. Start it now — it will take longer than the software.

I have not used, and will not ask for, those credentials.

---

## 2. Four things the vision treats as search filters that are not data

The search is specified as "any combination of council, suburb, acreage, zoning,
overlays, planning status, dwelling status, on-market/off-market status and
development potential." Four of those have no source behind them.

| Filter | Reality |
|---|---|
| **Owner details** | Not in any open source. Cadastre and Titles Register are deliberately separate; the bridge is licensed, and using owner names to contact people is APP 7 territory on top of that. See `DATA-SOURCE-SURVEY.md`. |
| **Dwelling status** (with or without a house) | Not in Vicmap Property. Real routes: council rates data (not open), VBA building permit data, or imagery/derived footprints. Each is its own lane decision. Today this filter has nothing behind it. |
| **Off-market status** | Not a dataset anywhere, by definition. Off-market is a fact about a relationship, not about a parcel. A system can record what an agent told a named person on a date — that is evidence with provenance — but it cannot *search* for it. Modelling it as a filter will produce an empty or misleading column. |
| **On-market status** | Obtainable, but the major portals' terms prohibit scraping. This is a licensing question with the portals, not a crawler question. |

None of these is fatal. Each needs a decision about which lane it enters through
and what it costs. The leak is having them in a specification as though they were
already available.

---

## 3. "Alert me where big developers are buying" — the signal you asked for is the late one

Detecting acquisition through title transfers or sales data is Lane A, expensive,
and for RP Data explicitly prohibited. But a transfer is also the *last* event in
the sequence. By the time it registers, the deal is done and the neighbours have
been approached.

The earlier signals are public, free, and nobody listed them:

1. **Planning permit applications** — council registers are public. A developer
   lodging on a site is intent, months before or around settlement, and names the
   applicant.
2. **Council meeting agendas and minutes** — published, name applicants and
   objectors, and record officer recommendations before decisions.
3. **Panels Victoria hearings and submissions** — name the parties to an
   amendment. Who bothered to make a submission on a rezoning tells you who holds
   land inside it.
4. **PSP consultation submissions** — same logic, earlier still.
5. **Planning scheme amendments** — already Crown's signal source.
6. **Gazette** — the legal moment of a rezoning.

A developer who lodges a permit, appears at a panel and makes a PSP submission
has told you what they are doing, in public, without a title search. **That is a
better product than the one specified**, and it is Lane B.

Adjoining-parcel activity is then a spatial question over the same open data —
Vicmap Property gives you the neighbours.

---

## 4. Architectural leaks

### A parallel confidence score will drift

The vision specifies "Confidence score: confirmed, probable or speculative." The
system already classifies every piece of evidence — `evidence_class` (FACT,
HYPOTHESIS, …), `reliability` (AUTHORITATIVE … UNVERIFIED) and, since 0003,
`retrieval_method`. A second, separately-maintained confidence field will drift
from those within weeks and then contradict them in front of a client.

**Fix:** derive the score. Confirmed = rests on at least one directly-retrieved
FACT. Probable = rests on HYPOTHESIS or operator capture. Speculative = anything
weaker. One source of truth, and the derivation is readable.

### An automatic "Acquire" breaks the Constitution

Every opportunity receiving a Decision of Acquire / Negotiate / Option / JV /
Watch / Avoid is a consequential output. Constitution §4 says nothing
consequential leaves without a stored approval ID, and the schema enforces it for
exports and outreach. A recommendation that reaches a client or an IC without
passing the same gate is the rule being true everywhere except where it matters.

**Fix:** a recommendation is an outbound artifact. Same gate.

### An IC brief that cites live evidence is unauditable

"Recommended price ceiling, next action and evidence links" — six months later
the zoning has changed, the amendment is gazetted and the comparable sales are
different. The brief now says something nobody can reconstruct, and the question
"what did we know when we recommended this?" has no answer.

**Fix:** snapshot. A brief stores the evidence it rested on, as it was, at the
moment it was approved. Immutable, like attribution.

### There is no suppression list

APP 7 requires a simple means of opting out of direct marketing, and requires it
to work. The vision describes alerts, outreach and briefs, and contains no
mechanism for "this person asked us not to contact them." That is not a
nice-to-have; it is the part regulators check first, and it has to exist before
the first outreach, not after the first complaint.

**Fix:** a suppression table that outbound generation checks, and cannot bypass.

### Crown is on three sides of the same deal

This is the one nobody has raised and it is the most dangerous.

Crown Capital & Development invests **for its own book** ($2M–$200M strategy). It
also assesses **client suitability** based on their budget and risk tolerance.
It also assesses **developer suitability**. Three principals, one ranked pipeline.

When a parcel scores well, who is told first? If Crown's own strategy wants it
and a client's mandate also fits, the system as specified will surface it to
whoever opens the dashboard. That is a conflict of interest running silently
through the core of the product, and it is the kind of thing that ends
relationships and invites regulatory attention regardless of intent.

**Fix:** every opportunity records the principal it is being worked for, and the
system refuses to produce outbound artifacts for two competing principals on the
same parcel without an explicit, recorded disclosure. Not a policy document — a
constraint.

### Proximity scoring manufactures precision

The Infrastructure Investment Program is a legitimate input and the vision is
already right that proximity alone should not produce a buy. The residual risk is
subtler: a number like "infrastructure score 0.72" *looks* like knowledge. If
that factor enters the score, it must carry its own note — which project, which
commitment stage, how far — exactly as the five matching factors do today, and it
must be marked indeterminate rather than zero when the link is weak.

### Indicative economics are the biggest liability per line of code

Residual land value, infrastructure contributions, holding costs and scenario
returns are assumption-dominated. Change the sales rate or the contribution rate
slightly and the answer moves enormously. Presented as system output next to
provenanced planning evidence, they borrow a credibility they have not earned.

**Fix:** every economic figure ships with the assumption set that produced it,
versioned like the matching weights, and is labelled an estimate. If an IC brief
cannot show the inputs beside the number, it should not show the number.

---

## 5. Regulatory: the risk is the structure, not the advice

Real property is not a financial product under the Corporations Act, so advice
about property investment does not itself require an AFS licence.

The exposure is elsewhere. The vision includes **joint ventures** and a **$2M–$200M
strategy** assessed against **client budget, finance, timeframe and expected
return**. Pooled investment structures can be managed investment schemes, and
those *are* financial products. The trigger is not "we gave property advice"; it
is "we pooled other people's money into a structure."

Get advice on the deal structures, not on whether you may talk about property.
Purchase, option agreement, delayed settlement and nomination are conveyancing.
Joint venture and development management may not be.

---

## 6. What I would build first

The vision is roughly three products. Sequenced by what is buildable now:

1. **The land intelligence layer** — every parcel in the seven LGAs over a size
   threshold, with zone, overlays, PSP status and any amendment touching its
   geography. Entirely Lane B, needs no negotiation, and answers most of the
   Whittlesea query today apart from owners and dwellings.
2. **The public-intent signal layer** — permits, agendas, panels, submissions,
   gazette. Lane B, and earlier than the transfer data everyone else watches.
   This is the differentiator.
3. **The identity layer** — owners, contacts, outreach. Gated behind the Cotality
   written permission or a Landata agreement, *and* a privacy basis, *and* a
   suppression list. Slowest, most expensive, most regulated. Do it last and do
   it properly.

Most competitors have (3) and treat (2) as manual research. Crown has the
provenance discipline to make (2) systematic, which is the part that is actually
hard to copy.

---

## Sources

- [Cotality AU End User Terms](https://www.corelogic.com.au/legals/end-user-terms) · [AU Third Party Restrictions](https://www.cotality.com/au/legal/third-party-restrictions) · [Terms of Use](https://www.cotality.com/legal/terms-of-use)
- [ASIC — Do you need an AFS licence?](https://www.asic.gov.au/for-finance-professionals/afs-licensees/do-you-need-an-afs-licence)
- [OAIC — APP 7 direct marketing](https://www.oaic.gov.au/privacy/australian-privacy-principles/australian-privacy-principles-guidelines/chapter-7-app-7-direct-marketing)
- `docs/DATA-SOURCE-SURVEY.md` for the lane-by-lane source position
