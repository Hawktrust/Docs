# The basis Crown relies on to contact people

**Status: a proposed position, written to be argued with. Not legal advice and
not a substitute for a lawyer. Every recommendation here is marked so Crown can
strike it.**

Section 4 of the privacy policy asks which basis Crown relies on for direct
marketing. That question has been sitting open as a blank. This is the work of
answering it, rather than a note saying it needs answering.

---

## The thing that gets conflated

Two different laws apply, and they are usually treated as one.

| | Governs | Applies to |
|---|---|---|
| **Privacy Act, APP 7** | *using personal information* for direct marketing | every channel — post, phone, email |
| **Spam Act 2003, s16** | *sending a commercial electronic message* | email and SMS only |

Satisfying APP 7 does not satisfy the Spam Act. They are separate tests and the
Spam Act is the stricter one, because it has no impracticability escape. This
distinction decides how Crown may make first contact, and it is the single most
consequential thing in this document.

---

## APP 7 — may Crown use the information at all

Crown collects landholder names from public registers, which means **from a
third party rather than from the individual**. That puts it in APP 7.3, not
7.2. Under 7.3 Crown may use the information for direct marketing only if:

- **(a)** the individual consented, **or** it is impracticable to obtain that
  consent; **and**
- **(b)** Crown provides a simple means of opting out; **and**
- **(c)** each message prominently draws attention to that opt-out.

And separately, **APP 7.6(c)**: if asked, Crown must tell the person **where it
got their information**.

### (a) — consent or impracticability

Consent is absent by definition in a cold approach. So the question is whether
obtaining it is impracticable.

**The honest argument for impracticability:** the only way Crown could ask a
landholder for consent is to contact them, and contacting them is the thing
consent is needed for. That circularity is genuine, and it is the strongest
form the argument takes.

**Why it is not a free pass:** the OAIC reads impracticability narrowly. Cost
and inconvenience are not enough on their own. An argument that would excuse
any cold approach by anybody is an argument a regulator will not accept, and
Crown should not plan on it doing more work than it can.

**Recommendation:** rely on impracticability for landholders, and write down
*why* in those terms rather than asserting it. Crown holds no channel to the
person that does not itself constitute the approach.

### (b) and (c) — already built

The opt-out exists: a signed link on every message, no account needed, and the
suppression is honoured against person, organisation, address and parcel so
being reached under a different detail does not defeat it. `contact_suppression`
and `crown/optout.py`.

What is **not** yet enforced is (c): that the opt-out is *prominent*. The schema
requires an artefact to carry one; nothing checks where it sits in the message.
That is a gap and it is named again at the end of this document.

### APP 7.6(c) — where we got it

Crown can answer this better than most. The data rights register records, per
source, what it is and on what basis it is used, and every evidence record
carries its provenance. **This is a strength worth stating in the policy**: a
person asking "how did you get my details" gets a specific register named, not
a shrug.

---

## The Spam Act — may Crown *email* them

This is where the analysis turns, and it is the part most likely to be missed.

A commercial electronic message needs consent under s16. Consent is either
**express**, or **inferred** under Schedule 2 — and inferred consent has a
narrow, specific basis: **conspicuous publication** of the address, where

1. the address was published **by the person, or with their agreement**, in
   connection with their **work-related** business, functions or duties; and
2. the publication carried no statement refusing commercial messages; and
3. the message is **relevant to those work-related functions**.

Now apply it to a landholder whose details appear on a planning permit:

- the address was published **by the council**, in the course of a statutory
  process — not by the person, and not with their agreement that it be used for
  marketing;
- a person who owns land, or is selling their home, is **not acting in a
  work-related capacity**;
- an approach about selling their land is not relevant to work-related
  functions they do not have.

**All three limbs fail.** The conclusion follows and it is uncomfortable:

> **Cold-emailing an individual landholder identified from a public register is
> very likely a breach of the Spam Act, regardless of how well APP 7 is
> satisfied.**

Publication in a register is not publication by the person, and a statutory
disclosure is not an invitation.

### What this does not stop

**Post is not a commercial electronic message.** The Spam Act does not reach it
at all. A letter to a landholder needs APP 5 and APP 7 satisfied — which the
collection notice and the opt-out do — and nothing more.

**Professional contacts at firms are a different case entirely.** An agent's or
a developer's work address, published on their own company website, in a
message about land relevant to their job, satisfies all three limbs of
conspicuous publication comfortably. This is the audience email works for.

**A reply is express consent.** Once a landholder writes back, the channel
opens.

---

## The recommended position, per audience

| Audience | APP 7 basis | First contact | Email allowed |
|---|---|---|---|
| **Landholders from public registers** | impracticability (APP 7.3(a)) | **post only** | only after they reply, or otherwise consent expressly |
| **Professional contacts at firms** | impracticability, with a much easier case | email | yes — inferred consent, conspicuous publication, work-related |
| **Buyers under an existing mandate** | **consent**, from the mandate itself | either | yes — the mandate is the express consent |

**Record each of these in `data_source.privacy_basis`**, which is where the
system already looks. The database refuses to switch on a source that
identifies people without one.

### What Crown loses by accepting this

The fast, cheap channel to the audience Crown most wants to reach. That is a
real commercial cost and it is the reason this conclusion is worth arguing with
rather than accepting because a document said it.

### What Crown gains

A first approach by post is slower and better. It cannot be mistaken for spam,
it arrives at the property rather than at an inbox, and it is the difference
between a business that looks like a broker and one that looks like a list.

---

## Gaps this analysis exposed in the system

**1. Nothing recorded the channel. ~~Open.~~ Closed by migration 0024.**

`outbound_artifact` knew its type and its recipient and not how it was going
out, so this document's conclusion was a paragraph somebody had to remember.
It is now a constraint:

- `channel` (`POST` / `EMAIL`) and `recipient_class`
  (`LANDHOLDER_FROM_REGISTER` / `PROFESSIONAL_CONTACT` / `MANDATED_BUYER`) are
  required on anything addressed to a person;
- a trigger refuses `EMAIL` + `LANDHOLDER_FROM_REGISTER` unless an express
  consent is on record, on INSERT **and** on UPDATE, because a channel changed
  afterwards is the obvious way around a rule enforced only at insert;
- `contact_consent` records express consent — what the person actually did, in
  a sentence, because "they consented" is a conclusion rather than evidence;
- a mandate is explicitly **not** accepted as a landholder's consent: it is
  consent from a different person about a different thing;
- a suppression still outranks a consent, because stopping is always available.

**There is no `PHONE` channel, and its absence is deliberate.** The Do Not Call
Register Act wants numbers washed before telemarketing and Crown has not built
that. A value the schema appears to bless and the law does not would be worse
than having none. Add it in the same migration that adds the wash.

**2. Nothing checked the opt-out was prominent. ~~Open.~~ Closed by migration
0025.**

APP 7.3(c) wants the opt-out drawn to the reader's attention, not merely
present. The link cannot be in the body when the body is written — it is an
HMAC over the artefact id and the artefact does not exist yet — so the body
carries `{{opt-out}}` where the link goes and `crown/message.py` substitutes it
at send time. Prominence is then a property of where the marker sits, which is
decidable. Five rules, enforced by trigger on INSERT and UPDATE:

| | |
|---|---|
| present | a message with no way out is not a message |
| once | one is a way out; several is a maze |
| not buried | at most 400 characters may follow it |
| on its own line | inside a paragraph is how an opt-out gets read past |
| introduced in words | a bare link draws attention to nothing |

`build_content()` now assembles a compliant body itself, so every artefact
Crown produces satisfies this by construction. "Remember to include the opt-out
prominently" is precisely the instruction that gets forgotten on the one
message that matters.

**What these rules cannot decide**, and it is most of what prominent means to a
person: font size, colour, contrast, whether the mail client renders it,
whether a human notices. They decide whether the way out was put somewhere a
reader would find it. That is a smaller claim than the Act makes, and it is
stated rather than implied — a check that appears to settle a question it has
only narrowed is worse than an honest partial one.

---

## What Crown must do with this document

1. **Read the Spam Act conclusion and decide whether to accept it.** If Crown's
   lawyer disagrees, that changes the channel strategy and this document should
   be replaced rather than amended around.
2. **Name who decided.** The policy has a column for it because an unattributed
   position is one nobody defends when it is questioned.
3. **Have it reviewed with the other three documents together.** The basis
   chosen here determines wording in all of them.

---

**Prepared:** 2026-09-22. **Reviewed by a lawyer:** no. **Adopted:** no.
