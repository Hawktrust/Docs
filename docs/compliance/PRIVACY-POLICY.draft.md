# Privacy policy — DRAFT, NOT IN FORCE

**Status: draft. Not reviewed by a lawyer. Not published. Do not rely on it.**

APP 1.3 requires a clearly expressed, up-to-date privacy policy, available free
of charge, published **before** personal information is collected. This is a
draft of one, written from what the system actually does rather than from a
template, so that the review is about the decisions and not about the facts.

`[DECIDE]` marks a choice only Crown can make.

---

## 1. Who we are

`[DECIDE]` Legal entity name, ABN, and registered address.

This must match the row in `outbound_identity`, which is what every message
Crown sends will carry. If the two disagree, the message misidentifies its
sender, which is a separate problem under s17 of the Spam Act 2003.

## 2. What we collect, and from where

Crown is a property-intelligence and prospecting system. It collects:

**About land, not people.** Parcel boundaries and identifiers, area, zoning,
planning overlays, planning scheme amendments, and planning permit activity.
These come from Victorian government open data published under Creative Commons
Attribution licences. **None of it is personal information.** It is the majority
of what Crown holds.

**About people, where a public register names them.** Where Crown records a
named individual — an applicant on a planning permit, a party to a panel
submission — that name came from a register the publisher made public. Crown's
data rights register records, for every source, whether it carries personal
information and on what basis it may be used. A source that identifies living
individuals cannot be switched on until that basis is written down; the database
refuses it.

**About the people who use Crown.** Names, email addresses, roles, and a record
of the decisions they took in the system.

**What Crown does not collect.** Owner names from the Titles Register, and
anything from RP Data or CoreLogic. Those are licensed products and Crown holds
no agreement for them. Crown does not scrape social media, marketplaces, or
property portals; their terms prohibit it and its register records that
position.

## 3. Why we collect it

`[DECIDE]` State the purpose plainly and narrowly. The current honest answer is:
to identify land that may suit a buyer, and to approach the parties connected
with it. Say so in those words rather than in a broader formulation that would
cover things Crown is not doing — a purpose written wide today is a purpose to
be justified later.

## 4. The basis we rely on for direct marketing

`[DECIDE]` **This is the most important decision in this document.**

APP 7 governs direct marketing, and publicly available personal information is
**not exempt**. An organisation needs consent, or must establish that obtaining
consent is impracticable, and must in either case provide a simple opt-out.

Crown must decide, per audience, which it relies on:

| Audience | Basis | Decided by |
|---|---|---|
| Landholders identified through public registers | `[DECIDE]` consent / impracticable | `[DECIDE]` |
| Buyers under an existing mandate | `[DECIDE]` — likely consent, from the mandate itself | `[DECIDE]` |
| Professional contacts at firms | `[DECIDE]` | `[DECIDE]` |

Record the answer in `data_source.privacy_basis` for each source, which is where
the system already looks for it.

## 5. How to stop hearing from us

Every message Crown sends carries a link that removes you, immediately, without
an account and without contacting anybody. Using it is the fastest route and it
is recorded so that it is not undone by accident.

You can also reply to any message, or write to `[DECIDE]` contact address.

A request to stop is honoured against the person, the organisation, the address
and the parcel — whichever we were given — so being reached under a different
detail does not defeat it.

## 6. Access and correction

You may ask what personal information Crown holds about you, and ask for it to
be corrected. APP 12 and APP 13. `[DECIDE]` Name the contact point and the
response time Crown commits to; 30 days is the usual undertaking.

Crown's audit trail records decisions and cannot be edited or deleted, by
design. Where information is corrected, the correction is recorded alongside
rather than replacing what was there — which is the honest way to keep both an
accurate present and a truthful history, and should be explained to anyone who
asks rather than discovered by them.

## 7. How it is held, and for how long

Personal information is held in a database with row-level access control, so
that a user sees only what their role permits. Passwords are stored as scrypt
hashes and never in readable form.

`[DECIDE]` **Retention is not yet decided and nothing currently expires.** APP
11.2 requires destroying or de-identifying personal information once it is no
longer needed for any permitted purpose. Crown needs a retention period per
category — contact records, suppression records, audit events — and suppression
records should outlive the contact data they suppress, or honouring a request
becomes impossible.

## 8. Overseas disclosure

`[DECIDE]` Whether any processor, hosting provider or service holding this data
is outside Australia. APP 8 requires naming the countries. This depends on the
deployment, which is not yet decided.

## 9. Complaints

`[DECIDE]` Name the contact point, and state that a complainant may escalate to
the Office of the Australian Information Commissioner if unsatisfied. The system
requires at least one active ADMIN or COMPLIANCE account precisely so that
somebody exists to answer; the readiness gate blocks a launch without one.

## 10. Changes to this policy

`[DECIDE]` How changes are notified, and where the current version lives.

---

**Last reviewed:** never. **Approved by:** nobody.
