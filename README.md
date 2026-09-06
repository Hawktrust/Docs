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
| `seeds/` | named users, the weight config, twenty synthetic mandates, the relay leads |
| `ingest/` | `SIGNAL -> EVIDENCE`: retrieval, provenance validation, review queue |
| `crown/` | the rest of the loop, plus the web app |
| `tests/` | the acceptance criteria, as tests |
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
| 1 | Real amendment from each of 3 LGAs, full provenance | **FAIL** | blocked at egress; 7 real leads queued for verification |
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

Acceptance criterion 1 requires a real, current amendment from Wyndham, Melton
and Hume in the database with complete provenance. **The graph is empty.**

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

## Known weakness: authentication is a placeholder

`POST /login` takes an email and no password. Authorisation is real and tested —
roles come from the database, row-level security enforces them, forged headers
change nothing — but **authentication is not**. Anyone who can reach the app can
sign in as anyone. This is fine for a thin loop on a private host and must not
meet the internet. Putting real credentials or SSO behind `crown.auth.authenticate`
is the one change needed; nothing else in the request cycle assumes how identity
was established.

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
