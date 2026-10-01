# Privacy policy — DRAFT, NOT IN FORCE

**Status: complete draft, pending legal review and Crown's ratification. Not
published. Do not rely on it until both have happened.**

APP 1.3 requires a clearly expressed, up-to-date privacy policy, available free
of charge, published **before** personal information is collected. This is one,
written from what the system actually does rather than from a template.

**Every section below is answered.** Where a decision was Crown's to make, a
position has been proposed rather than left blank, because a policy full of
blanks cannot be reviewed — a lawyer can only argue with a document that says
something. Each proposed position is listed in the appendix with the reasoning
behind it, so nothing has been decided quietly.

Marks remain only where the answer is a fact nobody has yet: a URL that does
not exist, a person not yet named, a hosting decision not yet taken.

---

## 1. Who we are

**Crown Real Estate Agents Pty Ltd**, ABN 86 690 344 597, of 208/2 Infinity
Drive, Truganina VIC 3029.

That address is both Crown's registered office and its postal address —
confirmed by Crown 2026-09-22 — so a formal notice, a complaint and an ordinary
letter all reach the same place. The distinction matters because "registered
office" is a term of art: it is where documents can be served under the
Corporations Act, and a policy that named only a mailing address would leave a
person no way to serve one.

The ABN was confirmed against ABN Lookup by Crown on 2026-09-22; migration 0023
records who checked and when.

Everything in this section is taken from the active row in `outbound_identity`,
which is what every message Crown sends will carry. That row is the
authoritative copy and this paragraph follows it: to change the identity,
supersede the row first and then restate it here. Editing only this paragraph
leaves the messages saying something the policy contradicts, which under s17 of
the Spam Act 2003 is a misidentified sender rather than a typo.

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

**To identify land that may suit a buyer Crown is acting for, and to approach
the parties connected with that land.**

That is the whole purpose. It is written narrowly on purpose. Crown does not
build profiles of people, does not sell or licence what it holds, and does not
use it to assess anybody's creditworthiness, tenancy or character. A purpose
written wide today is a purpose to be justified later.

## 4. The basis we rely on, and how we may contact you

Two laws apply and they are not the same test. **APP 7** governs whether Crown
may use your information for direct marketing at all. The **Spam Act 2003**
separately governs whether Crown may email you. Publicly available personal
information is not exempt from either.

Where Crown obtained your details from a public register rather than from you,
it relies on **APP 7.3**: that obtaining your consent beforehand is
impracticable, because the only way to ask would be to make the very approach
consent is needed for. Crown does not claim you consented, because you did not.

**How that limits the way Crown contacts you:**

| If you are | First contact | By email |
|---|---|---|
| A landholder Crown found in a public register | **by post** | only after you reply, or otherwise agree |
| A professional contact at a firm, at your published work address | email or post | yes, where the message relates to your work |
| A buyer Crown already acts for under a mandate | either | yes — the mandate is your consent |

Crown does not cold-email landholders. A register publishes an address because
a statute requires it, not because the person offered it, and Crown does not
treat a statutory disclosure as an invitation.

**If you ask where Crown got your information, you will be told which register,
specifically.** Crown records the source of every record it holds, along with
the terms that source is used under. That is APP 7.6(c), and Crown can answer
it precisely rather than generally.

The reasoning behind this position, including the Spam Act analysis that
produces the post-only rule, is set out in `CONSENT-POSITION.md` in full.

`[DECIDE]` Who at Crown ratified this position, and on what date. An
unattributed position is one nobody defends when it is questioned.

## 5. How to stop hearing from us

Every message Crown sends carries a link that removes you, immediately, without
an account and without contacting anybody. Using it is the fastest route and it
is recorded so that it is not undone by accident.

You can also reply to any message, or write to info@crownrea.com.au, or to
208/2 Infinity Drive, Truganina VIC 3029.

A request to stop is honoured against the person, the organisation, the address
and the parcel — whichever we were given — so being reached under a different
detail does not defeat it.

## 6. Access and correction

You may ask what personal information Crown holds about you, and ask for it to
be corrected. APP 12 and APP 13. Write to info@crownrea.com.au.

**Crown answers within 30 days.** In practice most requests are a database
query and are answered far sooner, but 30 days is what Crown undertakes,
because a commitment made here is one you can hold Crown to and it should hold
during a busy month as well as a quiet one.

Crown's audit trail records decisions and cannot be edited or deleted, by
design. Where information is corrected, the correction is recorded alongside
rather than replacing what was there — which is the honest way to keep both an
accurate present and a truthful history, and should be explained to anyone who
asks rather than discovered by them.

## 7. How it is held, and for how long

Personal information is held in a database with row-level access control, so
that a user sees only what their role permits. Passwords are stored as scrypt
hashes and never in readable form.

**How long Crown keeps it.** APP 11.2 requires personal information to be
destroyed or de-identified once it is no longer needed for any permitted
purpose. Crown's periods:

| What | Kept for | Why |
|---|---|---|
| Contact details of someone never contacted | **12 months** from collection | if no approach has been made in a year, the reason for holding it has lapsed |
| Contact details of someone approached | **7 years** from last contact | the ordinary limitation period for a dispute about that approach |
| A request not to be contacted | **indefinitely** | deleting it would let the request be undone by accident, which is the one outcome worse than keeping the record |
| Audit records of decisions | **indefinitely** | they exist to show what was done and why, which a deletion schedule would defeat |
| User accounts | until closed, then **7 years** | attribution of decisions already taken |

A suppression outliving the contact data it suppresses is deliberate: a list of
people not to contact is useless if it expires before the data that would let
Crown contact them.

**This is enforced.** Migration 0026 holds these periods as data, a view shows
what is due before anything is touched, and `scripts/retention.py` applies
them. An expired message is de-identified rather than deleted: the recipient's
name is removed and the record of Crown's decision stays, because the audit
trail exists to show what Crown did and erasing it would be a deletion schedule
for evidence.

A request not to be contacted is never expired. It has to outlive the data it
protects, or honouring it becomes impossible and the person is contacted again
by a system that forgot — the one place where keeping information is the
privacy-protective choice.

## 8. Overseas disclosure

**Crown's intention is that all personal information is held in Australia**,
and it discloses none of it overseas.

`[DECIDE]` Confirm this once the hosting is chosen. APP 8 requires the policy
to name the countries if any processor, hosting provider or backup destination
sits outside Australia, and it makes Crown accountable for what that recipient
does. This sentence must be checked against the deployment before the policy is
published, not after.

## 9. Complaints

Complaints go to info@crownrea.com.au. If you are not satisfied with how
Crown handles one, you may escalate to the Office of the Australian Information
Commissioner.

One inbox, deliberately, and not the one anybody signs in with. Migration 0022
separated the published contact point from the login: an address printed on a
cold approach has to keep working when the person behind it is away, and an
address that names one human does not. Whether a second inbox is worth opening
depends on somebody different reading it, which at Crown's size is not yet
true.

The system requires at least one active ADMIN or COMPLIANCE account precisely
so that somebody exists to answer; the readiness gate blocks a launch without
one. That account exists and has no password set, so
`SOMEBODY_CAN_ANSWER_A_PERSON` is still failing — it is not answerable until
somebody can actually sign in.

**info@crownrea.com.au is read every business day by Inder.** Proposed
2026-09-23, for Crown to ratify — it is what a 30-day response commitment needs
behind it, and a commitment with nothing behind it is the one a complainant
discovers first.

The gate can check the address is shaped like one. Nothing can check that a
person opens it, and a published address nobody reads satisfies s17's letter
while defeating the whole point of APP 1.4. This is the sentence to revisit
first when Crown gets busy.

## 10. Changes to this policy

The current version always lives at `[DECIDE: URL]` — the one thing still
missing, because the policy needs somewhere to live before it can say where
that is — and each version carries the date it took effect. Crown keeps the
superseded versions available at the same place, so a person can see what the
policy said when they were contacted rather than only what it says now.

Where a change materially affects how Crown uses information it already holds,
Crown notifies the people affected directly rather than relying on them to
re-read the page.

---

## Appendix — positions proposed, for Crown to ratify or strike

Everything in this appendix was written on Crown's behalf and has not been
agreed by Crown. It is collected here rather than left as blanks in the body so
that a lawyer can review a document that says something, and so that nothing
was decided quietly.

| § | Position taken | If Crown disagrees |
|---|---|---|
| 3 | Purpose stated narrowly: identify land for a buyer, approach the parties connected with it | widen it only with a reason; a wide purpose is one to justify later |
| 4 | APP 7.3 impracticability for register-sourced landholders, not consent | the alternative is not contacting them at all |
| 4 | **No cold email to individual landholders; post for first contact** | this is the costly one, and the reasoning is in `CONSENT-POSITION.md` |
| 4 | Email permitted to professional contacts and mandated buyers | |
| 6 | 30-day response undertaking | shorten it only if the inbox is watched daily |
| 7 | 12 months / 7 years / indefinite retention by category | |
| 8 | All data held in Australia | must be checked against the actual deployment |
| 9 | info@ read every business day | |
| 10 | Superseded versions stay published | |

**Still genuinely unknown**, and not for Crown to invent: the policy's URL, who
ratified the §4 position, who reads info@, and whether the hosting is onshore.

---

**Last reviewed:** never. **Approved by:** nobody.
**Positions proposed:** 2026-09-22, by Claude, on Crown's instruction to draft
rather than to enumerate. Ratification is Crown's and has not happened.
