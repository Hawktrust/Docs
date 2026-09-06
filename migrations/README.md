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

## 0002_rls_policies.sql

Completes the row-level security 0001 left as an "example policy shape", and
closes the hole that made those policies decorative.

Three things it does:

1. **Writes the missing policies.** `buyer_mandate`, `match_result` and
   `outbound_artifact` had RLS enabled and no policies at all, which denies
   everything to a non-owner role — the application could not read or write
   them. `opportunity` and `approval` had one policy each, leaving their other
   verbs closed.
2. **Adds `FORCE ROW LEVEL SECURITY`.** RLS does not apply to a table's owner.
   Without FORCE, an application connecting as the schema owner bypasses every
   policy and AC9 cannot hold, however carefully the policies are written.
3. **Creates the `crown_app` role** the application connects as, and revokes
   UPDATE, DELETE and TRUNCATE from it on the append-only tables — the trigger
   is the enforcement, this is defence in depth.

## Still open

**Shared append-only trigger message.** `audit_append_only()` raises
"audit_event is append-only…" for `attribution` writes too, because both tables
share the function. Enforcement is correct; only the message is misleading.
Left as-is rather than diverging from the schema as supplied.
