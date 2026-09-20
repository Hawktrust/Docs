# Crown AI — Ticket 01, the thin loop

One signal source, one geography type, one evidence record type, one scoring
function, one approval step, one attribution record:

```
SIGNAL -> EVIDENCE -> OPPORTUNITY -> BUYER MATCH -> HUMAN APPROVAL -> ATTRIBUTION
```

Everything is real except the buyer mandates, which are synthetic and labelled
as such — with one exception that matters and is documented below: no real
planning amendments have been ingested, because the build environment cannot
reach the source.

## Layout

| Path | What it is |
|---|---|
| `migrations/` | the schema, RLS policies, retrieval provenance, integrity fixes |
| `seeds/` | named users, the weight config, synthetic mandates, relay leads, candidate sources |
| `ingest/` | `SIGNAL -> EVIDENCE`: retrieval, provenance validation, review queue |
| `crown/` | the rest of the loop, plus the web app |
| `tests/` | the acceptance criteria, as tests |
| `tools/` | capture a real page from your own browser |
| `scripts/demo.sh` | build a throwaway demo database and run the app |

## Running it

```bash
createdb crown_ai
psql -v ON_ERROR_STOP=1 -d crown_ai -f migrations/0001_ticket01_thin_loop.sql
psql -v ON_ERROR_STOP=1 -d crown_ai -f migrations/0002_rls_policies.sql
psql -v ON_ERROR_STOP=1 -d crown_ai -f migrations/0003_retrieval_method.sql
psql -v ON_ERROR_STOP=1 -d crown_ai -f migrations/0004_integrity_fixes.sql
psql -v ON_ERROR_STOP=1 -d crown_ai -f seeds/001_users_and_config.sql
psql -v ON_ERROR_STOP=1 -d crown_ai -f seeds/002_buyer_mandates.sql

python -m ingest.cli --lga Wyndham          # blocked; see below
CROWN_DSN=postgresql://crown_app@/crown_ai CROWN_SECRET=... \
  flask --app crown.web:create_app run
```

The application connects as `crown_app`, which owns nothing. That is not a
convention — row-level security does not constrain a table's owner, so an
application connecting as the owner would bypass every policy.

To see the loop without live data: `scripts/demo.sh`.

## Tests

```bash
CROWN_ADMIN_DSN=postgresql://postgres:...@127.0.0.1:5432/postgres python -m pytest -q
python -m mypy
python -m pip-audit -r requirements.txt
```

Each test builds a database from the real migrations and seeds, and drops it
afterwards. CI runs the same three checks.

## Acceptance criteria

| # | Criterion | Status | Where |
|---|---|---|---|
| 1 | Real amendment from each of 3 LGAs, full provenance | **FAIL** | no amendment ingested yet; unblocked by `tools/collector.html` without waiting on the network policy |
| 2 | Re-running ingestion produces zero duplicates | PASS | `tests/test_ingest.py` |
| 3 | Missing provenance rejected to review queue | PASS | `tests/test_ingest.py` |
| 4 | Opportunity linked to evidence, named human owner | PASS | `tests/test_opportunity.py` |
| 5 | Ranked buyers, per-factor contributions, why-not | PASS | `tests/test_matching.py` |
| 6 | Weight change in config changes ranking | PASS | `tests/test_matching.py` |
| 7 | Synthetic records labelled, excluded from counts | PASS | `tests/test_synthetic_labelling.py` |
| 8 | Export without approval ID fails server-side | PASS | `tests/test_outbound_gate.py` |
| 9 | Forged role header rejected | PASS | `tests/test_authorisation.py` |
| 10 | Audit table append-only | PASS | `tests/test_audit_append_only.py` |
| 11 | Attribution traces to source URL and retrieval date | PASS | `tests/test_attribution_trace.py` |
| 12 | Test suite green in CI | **NOT ATTEMPTED** | workflow defined; no run has executed |

AC12 is **not** claimed. The workflow is defined and every one of its steps
passes locally, but the pull request shows zero check runs — GitHub Actions has
never executed it, so there is no green CI to point at. Enabling Actions on the
repository is the missing step. Branch protection on `main` is then needed
separately for "a failing check blocks the merge".

AC4 and AC11 pass against fixture evidence, because AC1 is blocked and there is
no real evidence to link an opportunity to. The mechanisms are demonstrated; they
have not been demonstrated on a real amendment.

## The one criterion that fails

Acceptance criterion 1 requires a real, current amendment from each LGA in scope
— Wyndham, Melton, Hume and, since 2026-09-20, Whittlesea — in the database with
complete provenance. **The graph is empty.**

Egress is a strict allowlist: `planning.vic.gov.au`, the planning schemes app,
`data.vic.gov.au` and the council sites are all refused, `WebFetch` is refused
for every domain, and the only reachable hosts are the Anthropic API, GitHub and
the package registries.

A server-side web search did get through, and it produced real amendment
identifiers for all three LGAs — but cross-checking showed it cannot be trusted
for detail: two searches disagreed on when C232melt was gazetted, and two
described different amendments under the number C272hume. Those seven leads are
in `evidence_review_queue` with their canonical URLs, marked with whether they
corroborated or contradicted, and none of them is evidence.

Migration 0003 enforces that distinction in the database rather than leaving it
to discipline: a record that was not directly fetched cannot be authoritative,
and therefore cannot be a `FACT`.

See `ingest/README.md` for the full account, and
`docs/EGRESS-ALLOWLIST-REQUEST.md` for the exact hosts to permit.

## Alerts and the Investment Committee brief

`/alerts` runs the detection pass; `/brief/<id>` is the one-page output.
Migration 0012 adds `watchlist`, `alert` and the `stale_evidence` view.

Five detectors: new evidence in a watched geography, a market move, a Public
Acquisition Overlay appearing on watched land, evidence past its shelf life, and
a source in use without a complete register entry.

- **Nothing is said twice.** Every alert computes a dedupe key from what it is
  about, and the database refuses a second one — "we already told you that" is
  the difference between a product people read and one they filter to a folder.
- **Confidence is derived, and weak alerts are withheld rather than sent** — and
  the withholding is recorded, so nobody has to wonder whether the system missed
  something or chose not to speak.
- **Evidence goes stale at different speeds.** A relayed claim expires in 30 days
  because it was never verified; a gazetted fact lasts a year. That is what makes
  `last_verified_at` more than a column.

The brief assembles from records that already exist and invents nothing. It
shows the **evidence snapshot as it was when the recommendation was made**, not
as it is now, because the question a brief has to survive is *what did we know
when we recommended this?* It translates every overlay into the risk it carries
rather than handing the reader a code to look up. And it will not print a price
ceiling without the assumptions that produced it.

## Market signals — who is moving, and where

`crown/signals.py` ranks geographies by weighted, recency-decayed signal.
Migration 0011 adds `market_actor`, `actor_signal` and `signal_weight_config`.

Three questions with three different answers:

**Big firms.** Listed developers disclose material acquisitions to the ASX and
publish landbank tables by region; they lodge permits, appear at panels and make
PSP submissions. All public, all free, all earlier than a title transfer.

**Government.** Already in the data. A Public Acquisition Overlay is a planning
control marking land an authority proposes to acquire, and it sits in the
overlay list the land layer already holds — `signals.government_intent()` is a
query, not a new source.

**Buyer agents.** Their buying is client-confidential and will stay that way.
Their recommendations are public, and are opinion rather than action — weighted
lowest of everything, because a suburb reaching a hotspot list is the end of a
move, not the start.

Weights live in `signal_weight_config`, changeable without a deploy, and every
change is audited by trigger — the same discipline as the match weights.
Every score decomposes into the signals that produced it, each with its source
URL: a ranking nobody can interrogate is a ranking nobody should act on.

### Elected officials count, and are never named

Registers of interests are published so the public can scrutinise the people in
them, which is not the purpose Crown would be pursuing. Noticing that a region
attracts investment is a fair read of a public register. Naming an individual
politician in a prospecting brief is a misuse of a transparency mechanism and
reputationally indefensible.

The schema enforces the difference: `market_actor.publishable_by_name` cannot be
true for an `ELECTED_OFFICIAL`, such a signal contributes to a geography's score
but returns no name, and `actor_signal_publishable` excludes them from anything
built for output. Their weight is also among the lowest, because a declared
interest is weak evidence of anything.

## Land search

`/land` answers the prospecting query — council, suburb, acreage, zone,
overlays, planning status, dwelling — over the cadastre. Migration 0010 adds
`parcel`, `parcel_planning` and `parcel_dwelling`.

Ticket 01 ruled out parcel-level resolution along with owner-level. They are
different problems: owners are licensed and privacy-bound, parcels are Creative
Commons and carry no personal information at all. This is the parcel half, built
ahead of the data, so the day Vicmap Property is ingested the query already works.

```
/land?lga=Whittlesea&min_acres=20&max_acres=150&status=DRAFT
```

Three things it is careful about:

- **Zoning is history, not a column.** `parcel_planning` holds an observation per
  date, because the change in zoning is the signal Crown trades on.
- **An unobserved dwelling is UNKNOWN, never No.** Modelling it as a boolean on
  the parcel would have made every parcel read "no house" the moment the table
  was created — a lie with a default value. Filtering on it says the result is
  partial.
- **No result carries an owner**, because the source does not have one.

`nearby()` finds parcels within a radius by centroid distance and says so: that
is a proxy for adjacency, not adjacency. True touching needs PostGIS, which this
cluster does not have.

## Prospecting controls

`docs/PRODUCT-REVIEW.md` reviews the prospecting vision and finds where it leaks.
Four of those leaks were code, and migration 0008 closes them.

- **Suppression.** A person who asks not to be contacted is not contacted,
  whatever an approval says. Checked in the path that creates outbound
  artifacts, across person, address, parcel and organisation at once — so a
  request to stop contacting someone is not defeated by addressing the company.
  A suppression is never deleted; releasing one records who and why.
- **Principal and conflict.** Crown invests for its own book, advises clients and
  matches developers — three principals, one ranked pipeline. An opportunity now
  records who it is worked for, and the same geography being worked for two
  principals stops outbound until a disclosure is on record.
- **Recommendations are gated.** An Acquire reaching a client or an investment
  committee is consequential, so it takes an approval id like any export, and it
  is append-only afterwards.
- **Confidence is derived, never typed.** CONFIRMED rests on a directly
  retrieved FACT, PROBABLE on an operator capture or a retrieved HYPOTHESIS,
  SPECULATIVE otherwise. A second confidence field would drift from the evidence
  classification within weeks and then contradict it in front of a client. A
  relay-sourced lead cannot reach CONFIRMED, because 0003 already forbids relayed
  evidence from being a FACT.
- **Economics ship with their assumptions**, enforced by the tool and the
  database. A residual land value moves enormously on a small change to a sales
  rate; printed beside provenanced planning evidence it borrows a credibility it
  has not earned.
- **Briefs snapshot their evidence.** What the recommendation rested on, as it
  was, at the moment it was made — so "what did we know when we recommended
  this?" has an answer six months later.

## The data rights register

Seven sources, one ingestible. Being in the register is documentation, not
permission: a source is switched on only when a named adviser signs its entry.

```
python scripts/confirm_source.py --list X --adviser x     # show the register
python scripts/confirm_source.py VICMAP_PROPERTY --adviser "Your Name"
```

The open spatial stack — Vicmap Property, Vicmap Planning, VPA precinct
structure plans — is adopted and needs one signature each. Between them they
answer every freehold parcel in an LGA over a given area, with its zone, its
overlays and its PSP status, under Creative Commons Attribution.

Two entries need more than a signature, and the database enforces it:

- **Lane A** (`LANDATA_TITLES`) needs `--agreement` naming the signed agreement
  on file. A link to a product page is not an agreement.
- **A source that identifies living individuals** needs `--privacy-basis`:
  which APP is relied on for the intended use, the consent position, and where
  the suppression list lives. A licence answers whether Crown may *hold* the
  data. It does not answer whether Crown may *use* it to contact anyone.

`docs/DATA-SOURCE-SURVEY.md` has the full survey and why owner names are not in
any open source.

## Getting real amendments in while the source is unreachable

The build environment cannot reach any Victorian planning host, and that is not
going to change on our say-so. A person with a browser is not so constrained,
and that is a real channel rather than a workaround: it is the publisher's own
page, opened by a named human, with the bytes kept.

Two tools, both self-contained, both making **no network requests at all** —
which you can confirm in the network tab, or by running them offline.
`tools/bookmarklet.html` installs a one-click capture that reads the page
you are on; `tools/collector.html` takes a pasted page instead, for when a
bookmarklet is inconvenient.

1. Open `tools/bookmarklet.html` and drag **Crown capture** to your bookmarks bar.
2. On each amendment page, click it. A panel reads what it can and marks every
   field as a *suggestion*; it will not export until you have checked each one.
3. Tick the confirmation and save.
4. `python -m ingest.cli --lga Wyndham --capture crown-capture-*.json --as you@crown.local`
   — one command takes all four.

What makes the result evidence rather than hearsay:

- **The bytes are kept.** `capture_artifact` stores the raw HTML, so anything
  drawn from it can be rechecked against what was actually on the page.
- **The bytes are fingerprinted.** The bundle carries a sha256 recomputed on
  import; a bundle whose hash does not match its own content is refused. The
  collector's hash implementation is checked against Python's in the test suite.
- **A person is on the hook.** `captured_by` names them, and the operator
  confirms each field rather than accepting what a parser guessed.

Graded honestly: a capture may be `STRONG`, so a gazetted amendment captured
this way **can be a `FACT`** — better than a search intermediary's summary. It
can never be `AUTHORITATIVE`; that stays reserved for a fetch the system made
and can make again. The database enforces both.

A capture also closes any queued lead waiting on that amendment.

## Defects found reviewing this, and fixed

Each was reproduced before it was fixed, and each reproduction is kept as a
regression test in `tests/test_integrity.py`. All five were reachable from
ordinary use.

1. **`buyer_mandate_real` bypassed row-level security.** A view runs with its
   owner's rights unless declared otherwise, so the view the schema tells you to
   use for "any figure shown to a person" was the one path that ignored the
   policies on the table beneath it — a connection with no identity set could
   read real mandates through it. Now `security_invoker`.
2. **A match could be approved twice.** A double-clicked button was enough.
   Now `UNIQUE (match_result_id)` on `approval`, and the UI answers 409 instead
   of falling over.
3. **One approval could produce unlimited attribution records.** Attribution is
   append-only, so those duplicates could never be removed — permanently wrong
   rows in the record that answers "which signal created this". Now
   `UNIQUE (approval_id)`.
4. **An approved match could be rescored underneath its approval.** A match
   approved at 0.7639 read 0.5444 after a recompute, with the approval still
   pointing at it. Recomputing now skips decided matches, and a trigger enforces
   it whatever code does the writing.
5. **The stage rule counted revisions of one amendment as separate amendments.**
   Ingestion writes a new evidence record when a payload changes upstream, so a
   council editing a page escalated an opportunity from DEVELOPING to
   HIGH_CONFIDENCE. The rule now takes the strongest class per amendment.

Security hardening in the same pass: CSRF tokens on every state-changing
request (approving is the act the system exists to gate), `HttpOnly` /
`SameSite=Strict` / `Secure` session cookies, and the app now refuses to start
without `CROWN_SECRET` rather than generating one that silently invalidates
every session on restart.

## Reviewed as an auditor and as a CEO

A second pass asked two different questions: *can you prove what happened?* and
*does this tell me the truth about my business?* Six more things were wrong.

**Could not be answered before, can now:**

1. **"Who signed in, and who tried?"** Nothing recorded authentication at all.
   Sign-in, sign-out and failed sign-in are now audited — and so is every
   refused action, because an attempt that fails is worth more to an auditor
   than one that succeeds.
2. **"Who changed the numbers that pick the buyer?"** The five scoring weights
   are configuration precisely so they can change without a deploy, which meant
   changing them left no trace. A trigger now records every change with its
   before and after, whatever writes it — application, migration, or a psql
   prompt.
3. **"Who did this?"** `actor_user_id` and `actor_agent` were both nullable
   with nothing requiring either, so an audit row could be attributed to nobody.
   Now a CHECK requires one.
4. **"Did they approve their own work?"** Nothing connected `approver_id` to
   `owner_user_id`. The analyst who raised an opportunity could approve the
   match on it. Now refused by trigger. *If this is impractical at Crown's
   headcount, that trigger is the one thing to drop — but drop it deliberately.*
5. **"What are we ingesting without permission?"** The register carries
   `register_confirmed_by`, described as NULL until a named adviser signs. The
   one ingestible source has been ingestible from the start with it empty.
   `data_rights_exception` now reports it, and the compliance page shows it.
   **It is not empty today.**
6. **Demo data was laundering into real figures.** Five demo evidence records
   produced four opportunities recorded as `REAL` — the `origin` column exists
   to prevent exactly this and the rule engine never set it. An opportunity is
   now only as real as the evidence under it, a match only as real as both sides
   of it, and the overview counts accordingly.

**Added because a person could not see the answer:**

- `/overview` — the honest state, zeros included, with a banner saying plainly
  that no real evidence has been ingested. Demo records are reported separately
  and never folded into a figure.
- `/compliance` (ADMIN, COMPLIANCE) — data rights exceptions, the queue waiting
  on a human, every change to the scoring weights, and the audit trail. An
  append-only table nobody can read is a table nobody checks.
- Outbound artifacts now carry the chain that justifies them — geography, the
  rule that staged it, the evidence with its provenance, the buyer, every factor
  of the score, and the approval. A gated export that says only `{"note": ""}`
  is gated and useless.

## Authentication

Passwords are hashed with scrypt (N=2^15, r=8, 16-byte salt, ~160 ms per hash),
using the standard library so there is no dependency to keep current. The
parameters travel with each digest, so they can be raised later without
invalidating existing passwords.

- Five failed attempts locks an account for fifteen minutes, and the correct
  password does not open it while it is locked.
- An unknown account and a wrong password return the same message, and take
  comparable time, so neither reveals which addresses are real.
- Seeded accounts have **no password**, which means nobody can be them until
  someone sets one: `python scripts/set_password.py hawk@crown.local`.
- Signing in starts a fresh session, so a fixed session id is not inherited.
- A session idle for eight hours stops being signed in.

Every sign-in, sign-out, failed attempt and lockout is audited.

## Three design notes worth reading before extending this

1. **Three of the five scoring factors are indeterminate at Ticket 01 scope.**
   An opportunity here is geographic and carries no asset type, price or land
   size, so asset fit, price fit and size fit have nothing to compare against.
   They are reported as indeterminate and excluded from the weighted mean rather
   than scored zero, which would make every mandate look like a poor fit for
   reasons that are not its fault. Giving an opportunity those attributes is
   Gate 0 work.
2. **Geographic fit rewards specificity.** A mandate naming one geography fits
   better than one naming five. Without that, every non-excluded mandate scored
   an identical 1.0 on geography and no change to the weights could reorder
   anything — AC6 would have been unsatisfiable.
3. **Demo evidence is flagged, not implied.** `seeds/dev_only_demo_evidence.sql`
   exists so the loop can be walked locally. Every row it writes is
   `DEMO_SYNTHETIC` and titled `DEMO RECORD`. It is not part of the production
   seed set.
