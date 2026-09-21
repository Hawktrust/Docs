# What is missing before Crown contacts a real person

Two questions get confused with each other. *Does it work?* is answered by the
test suite. *May we turn it on?* is a different question with a different list,
and this is that list.

Some of it is now enforced. `launch_readiness` in migration 0016 is the machine
-checkable part — run `python scripts/readiness.py`, which exits non-zero while
anything blocking fails, or open `/readiness`. The rest of this document is the
part no query can check, which is exactly why it has to be written down.

---

## 1. Built and enforced

### The recipient can stop it themselves

`contact_suppression` has honoured requests since migration 0008, and its
`source_of_request` column has listed `OPT_OUT_LINK` the whole time. There was
no opt-out link. `recorded_by` was `NOT NULL` against `app_user`, so the only
way a person could stop being contacted was to reach somebody at Crown and ask
them to type it in.

That is not a gap in convenience:

- **APP 7.3** requires a *simple* means of opting out of direct marketing.
- **Section 18, Spam Act 2003** requires a commercial electronic message to
  contain a *functional* unsubscribe facility the recipient can use, working for
  at least 30 days after the message.

Both words mean the recipient does it themselves. A phone call to the sender is
neither. Migration 0016 and `crown/optout.py` close it:

- the link carries a signed capability, not a database key — an HMAC over
  (artefact, scope, identifier), so it cannot be forged without the application
  secret, and re-sending a message reproduces the same link rather than growing
  a table of live capabilities to leak;
- `GET /opt-out/<token>` shows a confirmation and changes nothing, because mail
  scanners follow links without a human ever seeing them;
- `POST` records the suppression with `recorded_by` left NULL — a suppression
  nobody at Crown typed in is the one that proves the mechanism works;
- the anonymous caller can *add* a suppression and do nothing else. Not read one
  back, not release one, not reach another table. The insert deliberately has no
  `RETURNING`, because an `INSERT` that returns rows is subject to the table's
  SELECT policies and opting out must not become a way to read who else has.

Clicking twice is a no-op, not an error. People forward messages and click again
when unsure.

### Crown knows who it sends as

**Section 17, Spam Act 2003**: the message must accurately identify who
authorised it and how to contact them, and stay accurate for 30 days.
`outbound_identity` holds one active row — legal entity, ABN, postal address,
contact email — and it is versioned rather than edited, so an artefact keeps the
identity it was sent under. An `OUTREACH_DRAFT` cannot be created without one.

### The opt-out link survives a secret rotation

`CROWN_SECRET` signed session cookies *and* opt-out tokens, so rotating it —
routine, and something you want to do often — would silently have broken every
live unsubscribe link and breached the 30-day requirement in s18. They are
separate now:

| Variable | Signs | Rotate |
|---|---|---|
| `CROWN_SECRET` | session cookies | as often as you like |
| `CROWN_OPTOUT_SECRET` | opt-out links | keeping the old value below for 30+ days |
| `CROWN_OPTOUT_SECRET_PREVIOUS` | nothing — verification only | drop entries once 30 days have passed |

It falls back to `CROWN_SECRET` when unset so nothing breaks on upgrade, and the
readiness gate reports that fallback as blocking rather than letting it pass.

### Nothing addressed to a person exists without a way out

The `outreach_identifies_sender_and_recipient` CHECK refuses the row. The
application refuses it earlier, with a message that says which of the three
things is missing, because "constraint violated" is not an instruction.

Covers `OUTREACH_DRAFT` and, since 0018, `BUYER_BRIEF`. A mandate supplies the
consent a cold approach lacks, but consent is one of three requirements — ss17
and 18 want sender identification and a way to stop regardless. A brief handed
over in a meeting needs neither, and the schema cannot tell that apart from one
that was emailed, so it requires them of both.

---

## 2. Blocking, and not code

### A real record has never been ingested

AC1. `REAL_EVIDENCE_EXISTS` fails and will keep failing until either the egress
allowlist opens one host or somebody captures a page in a browser. See
`docs/EGRESS-ALLOWLIST-REQUEST.md`; the capture route needs no policy change and
takes about five minutes.

### Consent, and what Crown is relying on

APP 7 governs direct marketing, and **publicly available personal information is
not exempt**. An organisation needs consent, or that consent be impracticable to
obtain, and must provide the opt-out that now exists. The register has a
`privacy_basis` column and refuses to switch on a source that identifies people
without one — but the basis recorded there is a sentence, and a sentence is not
a decision somebody senior has made.

**Write down, before the first message:** which APP is relied on for each
audience, whether consent is claimed or impracticability is, and who decided.

### A collection notice

**APP 5** requires notifying a person, at or before collection, that their
personal information is being collected, by whom, why, and who it may go to.
Crown collects from public registers rather than from the person, which does not
remove the obligation — it makes it awkward, which is not the same thing. The
usual answer is a notice on the first contact plus a standing privacy page.

**Drafted, not in use:** `docs/compliance/COLLECTION-NOTICE.draft.md`, in both
forms — the short one for a first message, and the standing one for the privacy
page.

### A privacy policy

**APP 1.3** requires a clearly expressed, up-to-date policy, available free of
charge, covering what is collected, how it is held, how to access and correct
it, and how to complain. It must be published before collection begins.

**Drafted, not in force:** `docs/compliance/PRIVACY-POLICY.draft.md`. Written
from what the system actually does rather than from a template, with every
decision Crown must make marked `[DECIDE]`. It needs those filled and a
lawyer's review before it is published.

### A data breach response plan

The **Notifiable Data Breaches** scheme requires assessing a suspected breach
within 30 days and notifying the OAIC and affected individuals where serious
harm is likely. A plan written during an incident is not a plan.

**Drafted, never exercised:** `docs/compliance/BREACH-RESPONSE.draft.md`. It
needs names against three roles and one thirty-minute tabletop. It also names
the judgement worth making calmly in advance: most of what Crown holds about
people came from public registers, but the *combination* it assembles is not,
and deciding during an incident how to treat that means deciding it under
pressure to find the smaller number.

### Telephone contact, if that is ever the channel

The **Do Not Call Register Act 2006** requires numbers to be washed against the
register before telemarketing, and a wash is valid for 30 days. Crown does not
hold phone numbers today. If that changes, this becomes a hard blocker with a
subscription attached, and `contact_suppression` is not a substitute for it.

---

## 3. Operational, before it is anyone's job to rely on

None of this is legal exposure; all of it is the difference between a system
that runs and a system somebody can run.

| | State | What it needs |
|---|---|---|
| **Deployment** | none | A WSGI server (the Flask dev server is not one), `CROWN_SECRET` and `CROWN_DSN` from a secret store, TLS terminated in front. `CROWN_INSECURE_COOKIES` must be unset in production — it exists for the test client and turns off `Secure` on the session cookie. |
| **Scheduler** | **built** | `scripts/run_alerts.py`, safe to re-run and quiet on a quiet day. Still needs a cron entry: `15 7 * * * cd /srv/crown && CROWN_DSN=... python scripts/run_alerts.py --quiet` |
| **Backups** | none | Every table that matters is append-only or audited, which protects against tampering and not against loss. Point-in-time recovery, tested by restoring — an untested backup is a belief. |
| **Migrations** | forward only | Sixteen numbered migrations, no down-steps, applied by hand. Fine so far. The first migration applied to a database holding real records is the one where that stops being fine. |
| **Observability** | partial | `/health` answers without a session and says only up or not up. Still no structured logging and no error reporting; the audit trail records decisions, not failures, so a crashed alert run leaves only the stderr line `run_alerts.py` prints. |
| **Retention** | none | Nothing expires. Evidence has a shelf life and says when it is stale; personal information has no retention rule at all, and APP 11.2 requires destroying or de-identifying it when it is no longer needed. |
| **Secret rotation** | **built** | `CROWN_OPTOUT_SECRET` signs opt-out links, `CROWN_OPTOUT_SECRET_PREVIOUS` keeps retired secrets verifying, and the readiness gate blocks a launch while the fallback to `CROWN_SECRET` is still in use. |

---

## 4. The order to do it in

1. **Ingest one real record.** Everything else is theory until AC1 passes, and
   it is five minutes with `tools/collector.html`.
2. **Record the outbound identity.** One row: legal entity, ABN, postal address,
   contact email. ADMIN or COMPLIANCE only, and frozen once written.
3. **Fill the `[DECIDE]` marks in the three drafts and have them reviewed.**
   These gate the first message, not the first deployment, and they take longer
   to get right than to write. The privacy basis is the one that matters most.
4. **Deployment and backups.** Ordinary work, none of it surprising. Set
   `CROWN_OPTOUT_SECRET` while you are setting the others.
5. **Decide retention.** Nothing expires today, and APP 11.2 requires it.
6. **Re-read `launch_readiness`.** It will not go green on its own.

---

## What the readiness gate does not check

It reads the database. It cannot know whether a policy exists, whether a person
consented, whether the backup restores, or whether the privacy basis recorded in
the register is one anybody senior agreed to.

A green gate means nothing in the data contradicts a launch. It does not mean
launch. Section 2 of this document is the part that decides that, and no query
will ever tell you it is done.
