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
| Decides whether to notify | `[DECIDE]` | `[DECIDE]` |
| Technical lead for containment | `[DECIDE]` | `[DECIDE]` |
| Talks to affected people | `[DECIDE]` | `[DECIDE]` |

One name per row. "The team" is not a name, and at 2am it means nobody.

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
`[DECIDE]` Decide now, calmly, how Crown will treat that, because deciding it
during an incident will be decided by whoever wants the smaller number.

## If it is notifiable

1. **OAIC**, via the online form, as soon as practicable.
2. **Affected individuals** — what happened, what data, what they should do.
3. `[DECIDE]` Whether to notify all individuals or only those at risk, where the
   two differ.

## Afterwards

Write down what happened and what changed, within two weeks while it is still
accurate. `[DECIDE]` Where that record lives.

## Exercising it

`[DECIDE]` A plan nobody has walked through is a document, not a plan. Run one
tabletop before go-live: pick a scenario — *an app credential is found in a
public repository* is the realistic one — and walk it end to end with the people
named above. Thirty minutes.

---

**Last reviewed:** never. **Exercised:** never. **Approved by:** nobody.
