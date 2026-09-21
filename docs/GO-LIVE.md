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

### Nothing addressed to a person exists without a way out

The `outreach_identifies_sender_and_recipient` CHECK refuses the row. The
application refuses it earlier, with a message that says which of the three
things is missing, because "constraint violated" is not an instruction.

Only `OUTREACH_DRAFT` is covered today. **A `BUYER_BRIEF` sent by email is also
a commercial electronic message**, and when Crown starts emailing those rather
than handing them over, add the type to `ADDRESSED_TO_A_PERSON` in
`crown/outbound.py` and to the CHECK — rather than exempting it somewhere.

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

Neither exists.

### A privacy policy

**APP 1.3** requires a clearly expressed, up-to-date policy, available free of
charge, covering what is collected, how it is held, how to access and correct
it, and how to complain. It must be published before collection begins.

Does not exist.

### A data breach response plan

The **Notifiable Data Breaches** scheme requires assessing a suspected breach
within 30 days and notifying the OAIC and affected individuals where serious
harm is likely. A plan written during an incident is not a plan.

Does not exist.

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
| **Scheduler** | none | `alerts.run()` and the staleness check need to be invoked by something. Nothing does. A daily cron entry is enough to start; the deduplication already makes re-runs safe. |
| **Backups** | none | Every table that matters is append-only or audited, which protects against tampering and not against loss. Point-in-time recovery, tested by restoring — an untested backup is a belief. |
| **Migrations** | forward only | Sixteen numbered migrations, no down-steps, applied by hand. Fine so far. The first migration applied to a database holding real records is the one where that stops being fine. |
| **Observability** | none | No structured logging, no error reporting, no health endpoint. The audit trail records decisions, not failures — a crashed alert run leaves no trace anywhere. |
| **Retention** | none | Nothing expires. Evidence has a shelf life and says when it is stale; personal information has no retention rule at all, and APP 11.2 requires destroying or de-identifying it when it is no longer needed. |
| **Secret rotation** | none | `CROWN_SECRET` signs session cookies *and* opt-out tokens. Rotating it invalidates every live opt-out link, which would breach the 30-day functionality requirement in s18. Either keep a previous-secret list for token verification, or give opt-out tokens their own secret with its own rotation schedule. **This is the one operational item with a legal edge.** |

---

## 4. The order to do it in

1. **Ingest one real record.** Everything else is theory until AC1 passes, and
   it is five minutes with `tools/collector.html`.
2. **Decide the privacy basis and write the policy and collection notice.**
   These gate the first message, not the first deployment, and they take longer
   to get right than to write.
3. **Give opt-out tokens their own secret.** Small change, and doing it after
   the first message is sent is doing it too late.
4. **Deployment, backups, scheduler.** Ordinary work, none of it surprising.
5. **Re-read `launch_readiness`.** It will not go green on its own.

---

## What the readiness gate does not check

It reads the database. It cannot know whether a policy exists, whether a person
consented, whether the backup restores, or whether the privacy basis recorded in
the register is one anybody senior agreed to.

A green gate means nothing in the data contradicts a launch. It does not mean
launch. Section 2 of this document is the part that decides that, and no query
will ever tell you it is done.
