# Where property data can come from

A survey of candidate sources for Crown, classified by the Constitution's lanes.
Nothing here has been added to the data rights register — that is a scoping
decision, and `seeds/proposed/003_candidate_sources.sql` is ready to apply once
it is made.

Every host below was tested from the build environment on 2026-09-20 and every
one is refused by the network policy. Reachability and licence are separate
questions; these are all licence-clear-or-clearable, and none is reachable yet.

## The thing to understand first

**No open source contains owner names.** Victoria splits it deliberately:

- the **cadastre** (Vicmap Property) tells you the parcel — its boundary, its
  area, its identifier, whether it is Crown or freehold
- the **Titles Register** (Landata) tells you who owns it

They are different systems under different terms, and the bridge between them is
licensed. Every "find land and show me the owners" product is buying that bridge,
or is standing on someone who did. That is what Gate 0 is about, and it is why
`RP_DATA_SEAT` sits in the register as `BLOCKED` rather than merely absent.

## Lane B — open, commercially reusable, attribution required

These are usable today on a normal network, under CC-BY 4.0 (or CC-BY 3.0 AU).
Between them they answer nearly every geographic question Crown needs.

| Source | What it gives | What it does not give |
|---|---|---|
| **Vicmap Property** | Parcel and property polygons, parcel identifiers (SPI), **parcel area**, Crown vs freehold, easements, cadastral roads. Maintained by DTP from local and state government. | Any owner. No names, no addresses, no contact. |
| **Vicmap Planning** | Zones and overlays for all 79 LGAs, Urban Growth Boundary and Growth Area, planning scheme codelists. Updated weekly. | Anything about who holds the land. |
| **VPA open data** | Greenfield Precinct Structure Plan boundaries and approved PSP land use, as an ArcGIS open data portal. | — |
| **Planning scheme amendments** | Already registered as `VIC_PLANNING_AMENDMENTS`. The signal Ticket 01 runs on. | — |
| **VicPlan** | The viewer over the above, and per-property planning reports. | — |

Attribution wording has to be carried on anything derived from these, which the
register already has a column for and the seeded source already populates.

**What this combination can actually answer**, lawfully, with no licence
negotiation: *every freehold parcel in a given LGA over a given area, with its
zone, its overlays, whether it sits inside an approved PSP, and whether a current
amendment touches its geography.* For a land aggregation business that is most of
the question.

## Lane A — licensed, needs an agreement before a single row is stored

| Source | What it gives | The condition |
|---|---|---|
| **Landata / Titles Register** | The Register Search Statement names the registered proprietor. This is a public register. | Per-search, and a **Proprietor Name Search** (search *by* owner rather than by parcel) is only available through Information Brokers. Bulk extraction is a separate commercial arrangement. |
| **RP Data / CoreLogic** | Parcel, owner and sales history in one product. | Already in the register as `BLOCKED`: a seat subscription is not a platform or API agreement. Ingesting, caching or redistributing from a seat breaches it. |
| **Valuer General property sales** | Sale prices and dates. | Licence terms need confirming before use; some VG products carry marketing restrictions. |

## The part that is not a licence problem

Even holding a lawful title licence does not settle whether owner names may be
used to contact people.

- Victoria has previously varied LANDATA licence conditions specifically to stop
  real estate agents obtaining owner names and addresses through Valuer General
  records for marketing. This exact use has been restricted before.
- **APP 7** (Privacy Act 1988) governs direct marketing. Publicly available
  personal information is not exempt: an organisation needs consent, or that
  consent be impracticable to obtain, and must provide a simple opt-out on every
  communication.
- The OAIC's own guidance names land title registers as a source direct
  marketers draw on, and says to check the register's own statutory restrictions
  with the relevant body — here, the state land title office.

None of that makes owner outreach impossible. It makes it a thing with a
compliance design, a lawful basis and a suppression list — not a query result.
That design belongs in Gate 0, alongside the licence.

Migration 0007 stops that distinction being prose. `data_source` now carries
`carries_personal_information` and `privacy_basis`, and a source that identifies
living individuals cannot be made ingestible until the basis is written down —
which APP is relied on, the consent position, and where the suppression list
lives. `scripts/confirm_source.py` asks for it, and the database refuses the row
without it either way.

A Lane A source additionally needs `--agreement` naming the signed agreement on
file. A link to a product page is not an agreement, and the tool says so.

## Recommendation

1. **Take the Lane B stack now.** Vicmap Property plus Vicmap Planning plus VPA
   PSP data is a real product surface and needs no negotiation. Add them to the
   register with `is_ingestible = true` once a named adviser signs the entries —
   the register still shows one exception open for the source already in use.
2. **Keep owner identification behind Gate 0**, which is what Ticket 01 already
   says. Do not let a parcel-level feature creep in through a query interface
   before the licence and the privacy basis exist.
3. **Ask the title question as two questions**, because they have different
   answers: *may we hold this data* (licence) and *may we use it to contact this
   person* (APP 7 plus any register-specific restriction). A title licence
   answers only the first.

## Sources

- [Vicmap Property](https://www.land.vic.gov.au/maps-and-spatial/spatial-data/vicmap-catalogue/vicmap-property) · [on DataVic](https://discover.data.vic.gov.au/dataset/vicmap-property)
- [Vicmap Planning](https://discover.data.vic.gov.au/dataset/vicmap-planning)
- [Spatial data licensing](https://www.land.vic.gov.au/maps-and-spatial/spatial-data/how-to-access-spatial-data/licensing)
- [VPA open data](https://vpa.vic.gov.au/strategy-guidelines/open-data/) · [portal](https://data-planvic.opendata.arcgis.com/)
- [Using VicPlan](https://www.planning.vic.gov.au/planning-schemes/using-vicplan)
- [Where to find information about land titles](https://www.land.vic.gov.au/land-registration/for-individuals/where-to-find-information-about-land-titles)
- [LANDATA title search](https://www.landata.online/title-search/)
- [OAIC — APP 7 direct marketing](https://www.oaic.gov.au/privacy/australian-privacy-principles/australian-privacy-principles-guidelines/chapter-7-app-7-direct-marketing) · [OAIC — direct marketing guidance](https://www.oaic.gov.au/privacy/privacy-guidance-for-organisations-and-government-agencies/organisations/direct-marketing)
