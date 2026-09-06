# Crown AI — migrations

## 0001_ticket01_thin_loop.sql

The Ticket 01 (Thin Loop) schema. Postgres 15+ (verified on 16.13). Lane B sources
only — no parcel, owner, title or partner tables; those are Gate 0 work.

The whole file runs in one transaction: it either applies completely or not at all.
It is a numbered, one-shot migration, not re-runnable against a database that already
has it (`CREATE TYPE` will conflict). Apply it to a fresh database:

```
createdb crown_ai
psql -v ON_ERROR_STOP=1 -d crown_ai -f migrations/0001_ticket01_thin_loop.sql
```

It needs `pgcrypto` (for `gen_random_uuid()`), so the applying role must be able to
`CREATE EXTENSION` — i.e. run the migration as a superuser/owner role, not as the
application role.

## Transcription notes

The schema was transcribed from the Ticket 01 schema PDF. A few lines were cut off at
the right margin of that document and have been reconstructed; if any of these differ
from the author's intent, they are the places to check:

- `evidence_class` final label read as `UNKNOWN` (PDF cut at `'UNKN…'`).
- `reliability` final label read as `UNVERIFIED` (confirmed by the
  `unverified_cannot_be_fact` constraint that references it).
- `outbound_artifact.artifact_type` third value read as `BUYER_BRIEF` (PDF cut at
  `'BUYER_B…'`).
- The two `notes` strings in the seed block were cut mid-sentence and completed:
  "…Ticket 01 covers Wyndham, Melton and Hume." and "…Do not ingest, cache or
  redistribute."

Everything else is verbatim.

## Open items for the application build

These are properties of the schema as specified, not migration failures. They matter
for the acceptance criteria and need a decision before Ticket 01 can pass:

1. **RLS without policies.** `buyer_mandate`, `match_result` and `outbound_artifact`
   have row-level security enabled but no policies, so a non-owner application role
   sees zero rows and cannot write to them. `opportunity` and `approval` have one
   policy each (SELECT and INSERT respectively) — other verbs on those tables are
   likewise closed. Policies for the remaining tables and verbs still need writing.
2. **RLS does not constrain the table owner.** A role that owns these tables bypasses
   RLS entirely unless the tables are set to `FORCE ROW LEVEL SECURITY`. AC9 depends
   on the application connecting as a role that does *not* own the schema.
3. **Shared append-only trigger message.** `audit_append_only()` raises
   "audit_event is append-only…" for `attribution` writes too, because both tables
   share the function. Enforcement is correct; only the message is misleading.
