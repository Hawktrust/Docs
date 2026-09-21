# Collection notice — DRAFT, NOT IN FORCE

**Status: draft. Not reviewed by a lawyer. Not in use.**

APP 5 requires notifying a person, at or before the time personal information
about them is collected, of who is collecting it, why, and who it may go to.

Crown collects from public registers rather than from the person. That does not
remove the obligation — it makes it awkward, which is a different thing. Where
information is collected from someone other than the individual, the notice must
be given as soon as practicable after collection, and the usual answer is that
the first contact carries it.

Two versions follow because they do different jobs.

---

## A. The short form, for the first message

This goes in every first approach, near the opt-out link. It must be readable by
someone who did not ask to hear from Crown and is mildly annoyed to have.

> **Why you are hearing from us.** `[DECIDE: legal entity]` identified your
> property through Victorian public planning and property registers — the same
> records anyone can search. We hold your name and the property address, and we
> use them to contact owners about land that may suit a buyer we work with.
>
> We did not get your details from a broker, a list, or social media.
>
> You can stop this immediately: [remove me]. You can also ask what we hold and
> have it corrected, at `[DECIDE: contact]`. Our privacy policy is at
> `[DECIDE: URL]`.

Three things that wording does deliberately:

- **It says where the information came from.** "Public registers" is the single
  most common question a cold approach provokes, and answering it before it is
  asked is both required and disarming.
- **It says where it did not come from.** Not required. Worth saying, because
  the assumption is otherwise, and the assumption is what makes people angry.
- **It puts the opt-out before the access and correction rights.** Most people
  want the first one. Making them read past it to find it is a way of technically
  complying.

## B. The standing notice, for the privacy page

> **Collecting information about people we have not met**
>
> Most of what Crown holds is about land, not people: boundaries, areas, zoning,
> overlays, planning amendments and permit activity, all published as open data
> by the State of Victoria.
>
> Some public registers name people — the applicant on a planning permit, a
> party to a panel submission. Where we record such a name, we record it from a
> register the publisher made public, and we record in our own data rights
> register which source it came from, whether that source identifies living
> individuals, and the basis on which we may use it.
>
> We collect it to identify land that may suit a buyer we work with, and to
> contact the parties connected with it.
>
> `[DECIDE]` Who it may be disclosed to. If a buyer receives a brief naming a
> landholder, that is a disclosure and must be stated here. If briefs name only
> the property and not the person, say that instead — and make sure it is true.
>
> If you do not want to hear from us, tell us and we will stop. We keep a record
> that you asked, so that the request is not undone by accident later.

---

## What has to be true before either is used

- [ ] `[DECIDE]` Does a `BUYER_BRIEF` ever name an identified landholder? If so,
      that is a disclosure to a third party and section B must say so. The
      schema does not currently prevent it.
- [ ] `[DECIDE]` The privacy policy must exist and be published first. A notice
      pointing at a policy that does not exist is worse than no notice.
- [ ] The opt-out link must be live. It is — `crown/optout.py`, and the
      readiness gate blocks a launch if any message lacks one.

---

**Last reviewed:** never. **Approved by:** nobody.
