# Data breach response plan — DRAFT, NOT IN FORCE

**Status: draft. Not reviewed by a lawyer. Not exercised.**

The Notifiable Data Breaches scheme requires an entity to assess a suspected
eligible data breach within **30 days**, and to notify the OAIC and affected
individuals where serious harm is likely.

A plan written during an incident is not a plan. This is a draft of one, short
enough to be followed by somebody who is having a bad day.

`[DECIDE]` marks a choice only Crown can make.

---

## Who decides

| Role | Who | Reachable how |
|---|---|---|
| Decides whether to notify | Inder | inder@crownrea.com.au · `[DECIDE: mobile]` |
| Technical lead for containment | Inder | as above |
| Talks to affected people | Inder | as above |

One name per row. "The team" is not a name, and at 2am it means nobody.

**Three rows, one person, and that is a weakness worth naming.** Crown is one
person today, so this is honest rather than aspirational — but the decider and
the container being the same human means nobody is checking the containment
decision while it is being made, and the person talking to affected people is
the person who wants the incident to be small. When Crown is two people, split
the first row from the other two before splitting anything else.

`[DECIDE: mobile]` A phone number. Email is the wrong channel for an incident
whose first symptom may be that email is compromised, and a role reachable only
by the thing that is broken is not reachable.

## The first hour

1. **Write down the time you found out.** The 30 days runs from awareness, and
   reconstructing that later is unpleasant.
2. **Contain it.** Revoke the credential, take the process off the network, or
   shut the service down. Availability is cheaper than disclosure.
3. **Do not delete anything.** Not logs, not the suspect account, not the
   evidence. The audit trail is append-only by design and cannot be edited —
   that is a feature here. Preserve everything else too.
4. **Tell the decider**, even if it turns out to be nothing.

## What Crown actually holds, so scope can be assessed quickly

This is why a plan written in advance is worth the trouble — during an incident
nobody should be working this out from first principles.

| Data | Personal information? | Where |
|---|---|---|
| Parcels, zoning, overlays, amendments | No | `parcel`, `parcel_planning`, `evidence_record` |
| Names from public registers | Yes, but already public | `market_actor`, `outbound_artifact.contact_identifier` |
| Suppression list | **Yes, and sensitive by implication** | `contact_suppression` |
| User accounts | Yes | `app_user` |
| Passwords | Hashed (scrypt), not recoverable | `app_user.password_hash` |
| Every decision taken | Yes, attributed | `audit_event` |

**The suppression list deserves particular care.** It is a list of people who
asked not to be contacted. Its disclosure would be more harmful than the
contact data it protects, because it reveals a choice a person made rather than
a fact anyone could look up. Note also that opt-out tokens are signed
capabilities rather than stored rows — there is no table of live unsubscribe
links to leak, which is one class of breach Crown cannot have.

## Assessing whether it is notifiable

Within 30 days, and sooner if it is obvious. Three questions:

1. Was there unauthorised access, disclosure, or loss of personal information?
2. Is serious harm to any individual **likely**?
3. Has remedial action prevented that harm?

If 1 and 2 are yes and 3 is no, it is notifiable.

**A judgement worth making in advance:** most of what Crown holds about people
came from public registers, and it is tempting to conclude that its disclosure
causes no harm because it was already public. Sometimes true. But the
*combination* Crown assembles — this person, this parcel, this valuation, this
inferred intent to sell — is not public, and the aggregation is the product.
**Crown treats the aggregation as personal information in its own right, and
a disclosure of it as a disclosure of personal information.** Proposed
2026-09-23, for Crown to ratify.

The reasoning, so it can be argued with rather than inherited: each fact is
public, and the combination is not. A person's name is in a planning register;
their parcel is in the cadastre; a valuation is a market estimate; an inferred
intent to sell is Crown's own conclusion about them. Nobody published the four
together, and the four together are what Crown sells. Treating it as
non-personal because the parts are public would mean the product is valuable
enough to build a business on and worthless enough to leak, which cannot both
be true.

Deciding it now costs a harder assessment during an incident. Deciding it then
means it gets decided by whoever wants the smaller number.

## If it is notifiable

1. **OAIC**, via the online form, as soon as practicable.
2. **Affected individuals** — what happened, what data, what they should do.
3. **Notify everyone in the affected set, not only those assessed as at
   risk.** Proposed 2026-09-23, for Crown to ratify. The Act permits the
   narrower option, and the narrower option requires Crown to be confident
   about which individuals are at risk during the week it is least able to
   judge that. The cost of over-notifying is an awkward email; the cost of
   under-notifying is a person who was not told, found out later, and was
   right to be angry. Where the sets are large enough that this stops being
   proportionate, say so in writing at the time and record why.

## Afterwards

Write down what happened and what changed, within two weeks while it is still
accurate. **The record lives in `docs/incidents/` in this repository**, one
file per incident, named by date. Proposed 2026-09-23. It is version
controlled, it is where the rest of Crown's reasoning already lives, and it
cannot be quietly edited afterwards without that showing. It must not contain
personal information about affected individuals — reference the audit trail by
correlation id instead, which is what the correlation id is for.

## Exercising it

A plan nobody has walked through is a document, not a plan. **Run this
tabletop before go-live**, thirty minutes, and write the date in the footer:

> `CROWN_OPTOUT_SECRET` is found in a screenshot posted publicly. It signs
> every live opt-out link.

That scenario is chosen because it is the realistic one and because it is
genuinely awkward: rotating the secret immediately is the obvious move and it
breaks every unsubscribe link Crown has sent in the last 30 days, which is its
own s18 breach. The right answer is to rotate `CROWN_OPTOUT_SECRET` and move
the compromised value into `CROWN_OPTOUT_SECRET_PREVIOUS`, so new links are
signed with the new secret and old ones keep verifying — which the system
already supports, and which nobody will think of at the time unless they have
thought of it before.

Walk it end to end: who notices, who is called, what is rotated, in what order,
what is written down, and whether it is notifiable. `[DECIDE]` The date it was
run.

---

**Last reviewed:** never. **Exercised:** never. **Approved by:** nobody.
