# How Crown gets a property owner's name, lawfully

**Status:** the path is built (migration 0031) and both gates on it are closed.
Two pieces of work by a person open them. Nothing in this repository asserts a
licence position, because this build environment cannot reach landata.online.

---

## 1. The question, and the honest answer

RP Data, Pricefinder and similar platforms show a registered proprietor. The
reason they can is not technical and it is not a loophole: **Cotality (formerly
CoreLogic) and its peers hold commercial licences to state land registry data.**
They pay for a bulk feed and resell access under terms they negotiated.

Crown does not hold such a licence. Three things follow:

- **Crown cannot take the data from those platforms.** A seat on RP Data is a
  licence to use it, not a licence to extract it. CoreLogic's end-user terms
  prohibit systematic retrieval to compile a database, and separately prohibit
  using the licensed material to carry out or facilitate a search by purchaser
  or vendor name. That position is on file in the data rights register
  (`RP_DATA_SEAT`, `automated_access = PROHIBITED`).
- **`.id` and similar sites are not a substitute.** `.id` publishes ABS-derived
  demographics by area. There are no owner names in it. Nor in Vicmap Property:
  the cadastre and the Titles Register are separate systems, and no amount of
  joining the cadastre to itself produces a person.
- **The route that is open to Crown is the register itself.** Victoria's Titles
  Register is the authoritative record of who owns a parcel, and anyone may
  search it, per property, for a fee.

That is the path this document describes. It is slower and it costs money per
search, which is the actual difference between Crown's position and Cotality's.
It is also defensible, which the alternative is not.

## 2. The route

**Provider.** Land Use Victoria, through LANDATA (operated by SERV) or through
an Information Broker. Registered in the data rights register as
`LANDATA_TITLES`, lane `A_LICENSED`.

**Unit of work.** One property, one search, one fee. A current title search
returns the volume/folio, the registered proprietor, and the encumbrances.

**What Crown does not use:**

- **A Proprietor Name Search** — searching by person rather than by property. It
  is available only through Information Brokers, and it is the shape most likely
  to breach both a licence condition and APP 7. Crown does not need it: the
  system already produces a shortlist of parcels, and the lawful search is
  against the parcels on it.
- **A bulk extract.** A separate commercial arrangement, and the thing Crown is
  not licensed for. The schema refuses to record a prospecting search that does
  not name the parcel or the opportunity it came from, so the register is read in
  answer to a question Crown already had rather than swept for questions to ask.

## 3. The two gates, and the work that opens them

Both are enforced by the database (migration 0031), on insert and on update, so
they apply to every writer and not only to code that goes through
`crown/title.py`. Read the current state at any time:

```sql
SELECT * FROM title_search_readiness;
```

or `python -c "from crown import db, title; print(title.blockers(db.connect()))"`.

### Gate one — the licence has been read

**Until this is done, no title search can be recorded at all.**

1. Open an account with LANDATA, or engage an Information Broker.
2. **Read the licence terms.** Specifically: what may be done with the search
   result, whether there is any restriction on marketing use, and whether
   automated retrieval is permitted at all. Victoria has previously varied
   LANDATA licence conditions precisely to stop owner names and addresses being
   used for marketing, so this is the clause to find.
3. Record that it was read, by name:

```sql
UPDATE data_source
SET licence_reference = '<the licence or agreement reference>',
    terms_reference   = '<URL or document reference>',
    terms_read_by     = '<the name of the person who read it>',
    terms_read_at     = now()
WHERE code = 'LANDATA_TITLES';
```

If the licence turns out to prohibit the use Crown intends, that is the answer
and the path stops here. Recording it is still the right thing: the register's
job is to hold the answer so the question is not relitigated.

### Gate two — a basis for holding the owner's name

**Until this is done, a search can be recorded and paid for, and its result is a
volume/folio and a date.** The proprietor columns are refused.

This is a different question from the licence, and it is answered by different
work. The licence settles whether Crown may *obtain and hold* the search. APP 7,
plus any register-specific restriction, settles whether Crown may hold the
*owner's name* for the use Crown has in mind — approaching them.

What has to be written down:

- which APP is relied on for the intended use, and the reasoning;
- the consent position for the channel (see
  `docs/compliance/CONSENT-POSITION.md` — the conclusion there is **post**, not
  email, for a landholder found in a register);
- where the suppression list is and how a request not to be contacted reaches
  it (it is `contact_suppression`, and `crown/outbound.py` checks it before
  every send).

```sql
UPDATE data_source
SET privacy_basis = '<which APP, the reasoning, the consent position, the suppression route>'
WHERE code = 'LANDATA_TITLES';
```

**This is the item for the lawyer.** It belongs with the five documents in
`docs/compliance/` rather than being drafted here, because it is the one that
decides whether the approach itself is lawful.

### Then sign the register entry

```
python scripts/confirm_source.py LANDATA_TITLES --adviser "Your Name"
```

## 4. What the system then does

```python
from crown import title

search_id = title.request(
    conn,
    searched_for="1\\PS123456",          # SPI, address, or volume/folio
    purpose="OPPORTUNITY_SHORTLIST",     # or MANDATE_MATCH / VENDOR_INSTRUCTION / OWNER_REQUEST
    fee_cents=2920,
    requested_by=user_id,
    parcel_id=parcel_id,                 # or opportunity_id
)

title.record_result(
    conn, search_id,
    retrieved_at=when_the_search_came_back,
    volume_folio="12345/678",
    registered_proprietor="...",         # refused until gate two is open
    proprietor_address="...",
    is_company=False,
)
```

Four properties of that record, each a control rather than a convention:

- **It is attributed and purposed.** Who asked, why, and against what. A search
  with no stated purpose cannot be shown to be within one, and there is no
  `RESEARCH` or `GENERAL` purpose, because those are the absence of a purpose.
- **It is costed.** `title_search_spend` gives spend by month and purpose, and
  counts searches that returned nothing. A prospecting system that cannot say
  what a lead costs keeps buying leads nobody can justify.
- **It is frozen.** Once the result is recorded it cannot be edited. The
  register's answer is evidence as at a date; if it has changed, that is a new
  search. A name cannot be added to a search recorded without one — which closes
  the workflow where the gate is shut, the search happens anyway, and the name is
  filled in once the paperwork catches up.
- **It expires.** Twelve months, then the name and address are replaced with a
  tombstone and the search, its fee and its purpose remain. The register moves:
  a name two years old is both unnecessary and probably wrong.

## 5. What is deliberately not built

- **No automated retrieval from LANDATA.** `retrieval_method = 'DIRECT_FETCH'`
  is refused while the source's `automated_access` is anything but `PERMITTED` or
  `PUBLISHER_FEED`. A person logging into the portal is `OPERATOR_CAPTURE` and is
  ordinary permitted use; a crawler wearing that label would not be.
- **No scraping of a platform Crown has a seat on.** Asked and answered above.
- **No search by owner name.** See §2.
- **No phone contact off the back of a search.** There is no `PHONE` channel in
  this schema, because the Do Not Call Register wash is not built. Adding the
  channel before the wash would create a route the schema appears to bless and
  the law does not.

## 6. Cost, so the decision is informed

A current title search is a per-property fee in the low tens of dollars; confirm
the current figure with LANDATA or the broker rather than from this document.
What matters for planning is the shape: **searching 200 shortlisted parcels is a
per-search bill, not a subscription.** That is why the shortlist comes first and
the search second — the system's job is to make the 200 into the 20 worth paying
for.
