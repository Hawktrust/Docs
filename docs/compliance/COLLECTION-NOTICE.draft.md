# Collection notice — DRAFT, NOT IN FORCE

**Status: draft. Not reviewed by a lawyer. Not in use.**

APP 5 requires notifying a person, at or before the time personal information
about them is collected, of who is collecting it, why, and who it may go to.

Crown collects from public registers rather than from the person. That does not
remove the obligation — it makes it awkward, which is a different thing. Where
information is collected from someone other than the individual, the notice must
be given as soon as practicable after collection, and the usual answer is that
the first contact carries it.

**Crown agreed this approach 2026-09-22:** collecting from a register rather
than from the person does not remove the APP 5 duty, so the first contact
carries the notice. That settles the shape of the document. The `[DECIDE]`
marks below are details inside it, and they are still open.

Two versions follow because they do different jobs.

---

## A. The short form, for the first message

This goes in every first approach, near the opt-out link. It must be readable by
someone who did not ask to hear from Crown and is mildly annoyed to have.

> **Why you are hearing from us.** Crown Real Estate Agents Pty Ltd (ABN 86 690
> 344 597) identified your property through Victorian public planning and
> property registers — the same records anyone can search. We hold your name and
> the property address, and we use them to contact owners about land that may
> suit a buyer we work with.
>
> We did not get your details from a broker, a list, or social media.
>
> You can stop this immediately: [remove me]. You can also ask what we hold and
> have it corrected, at info@crownrea.com.au or 208/2 Infinity Drive,
> Truganina VIC 3029. Our privacy policy is at `[DECIDE: URL]`.

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
> **Who sees it.** A brief prepared for a buyer names the land, the planning
> position, the evidence it rests on and why Crown thinks it fits what that
> buyer is looking for. **It does not name you.** Crown does not pass a
> landholder's name to a buyer, and the system is built so that a brief carries
> no landholder identity at all.
>
> If you ask, Crown will tell you which register your details came from.
>
> If you do not want to hear from us, tell us and we will stop. We keep a record
> that you asked, so that the request is not undone by accident later.

---

## What has to be true before either is used

- [x] **Does a `BUYER_BRIEF` ever name an identified landholder? No.**
      Answered from the code rather than asserted: `outbound.build_content()`
      assembles the geography, the stage rule, the buyer label, the five score
      contributions and the evidence provenance. No landholder identity is
      among them. `tests/test_brief.py` asserts that, so adding one later fails
      a test that names this notice — the point being that if the answer ever
      changes, section B has to change with it rather than quietly becoming
      untrue.
- [ ] **The privacy policy must be published before this notice is used.** A
      notice pointing at a policy that does not exist is worse than no notice.
      The policy is written and complete; it needs a URL, which needs a
      deployment. That ordering is the only thing left between this document
      and use.
- [ ] The opt-out link must be live. It is — `crown/optout.py`, and the
      readiness gate blocks a launch if any message lacks one.

---

**Last reviewed:** never. **Approved by:** nobody.
