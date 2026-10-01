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

## A. The short form, for the first letter

This goes in every first approach, near the way to stop. It must be readable by
someone who did not ask to hear from Crown and is mildly annoyed to have.

The first letter is addressed to **"The Owner"** at the property. It carries no
name, because Crown does not collect owner names before an owner gets in touch.

> **Why you are hearing from us.** Crown Real Estate Agents Pty Ltd (ABN 86 690
> 344 597) chose this property using Victorian government land and planning
> data — the same records anyone can search. We have not looked up who owns it,
> and this letter is addressed to "The Owner" for that reason. We hold the
> property's address and our own view of whether it may interest a buyer we act
> for or be worth selling.
>
> We did not get your details from a broker, a list, or social media.
>
> **Don't want to hear from us?** Visit `[DECIDE: short URL]/stop`, or email or
> write to us, and we will not write again. If you do not reply, we will write
> at most once more and then stop.
>
> **Interested?** Scan the code or visit `[DECIDE: short URL]` to tell us how
> you would like us to contact you.
>
> You can ask what we hold and have it corrected, at info@crownrea.com.au or
> 208/2 Infinity Drive, Truganina VIC 3029. Our privacy policy is at
> `[DECIDE: URL]`.

Four things that wording does deliberately:

- **It says where the information came from** and that Crown did not look up
  the owner. "How did you get my details" is the most common question a cold
  approach provokes; answering it first is both required and disarming.
- **It says what Crown holds, including its own assessment.** That assessment
  is personal information about the owner, and a notice that mentioned only the
  address would understate what Crown holds.
- **It says where it did not come from.** Not required. Worth saying, because
  the assumption is otherwise, and the assumption is what makes people angry.
- **It puts stopping before everything else.** Most people want that first.
  Making them read past it to find it is a way of technically complying.

## B. The standing notice, for the privacy page

> **Contacting property owners we have not met**
>
> We use Victorian government land and planning data — boundaries, areas,
> zoning, overlays, planning amendments and permit activity — to find properties
> that may suit a buyer we act for, or whose owners may want to sell.
>
> We do not look up who owns those properties. We do not use the Titles
> Register, RP Data, Pricefinder or similar products to find owners' names, and
> we do not take names from council planning registers. Our first letter is
> addressed to "The Owner".
>
> We do hold our own assessment of each property — an estimated value, and
> whether we think it may suit a buyer or be worth selling. Where the owner can
> be identified, that assessment is personal information about them. You can
> ask to see it and ask us to correct it.
>
> **We do not email or text property owners who have not asked us to**, with or
> without their name.
>
> **Who sees it.** A brief prepared for a buyer names the land, the planning
> position, the evidence it rests on and why we think it fits what that buyer is
> looking for. **It does not name the owner.**
>
> If you ask, we will tell you exactly which records we used.
>
> If you do not want to hear from us, tell us and we will stop. We keep a record
> that you asked, so that the request is not undone by accident later.

---

## What has to be true before either is used

- [ ] **Owner names must stop being recorded from planning permits** before
      section B is true. The planning adapter currently records applicants as
      market actors; keep the permit as a signal about the land and drop the
      person.
- [ ] **A capped follow-up.** Section A promises at most one more letter.
      Nothing enforces that yet.
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
