# Captured pages

Bundles exported by `tools/collector.html`. Each one is a real page from a
Victorian planning register, the bytes it was read from, and a person's
attestation that they opened it and checked every field.

## Why they are committed

The build environment cannot reach `planning.vic.gov.au` — every host returns
403 at the CONNECT tunnel, and so does a control host, so it is a blanket
network policy rather than a per-host block. A person with a browser can reach
it, and `collector.html` turns what they see into a bundle.

Without this directory that would be a one-off: somebody captures a page, it
goes into whatever database happens to exist, and the next database built from
this repository has no real evidence again. AC1 would keep coming back.

A bundle is a file. Committed, it makes AC1 a property of the repository rather
than an act somebody has to remember, and every database built from here can
be given the same real record:

```bash
python -m ingest.cli --capture captures/*.json --as you@crownrea.com.au
```

`scripts/import_captures.sh` does exactly that over every bundle here.

## What a bundle contains, and what it does not

It holds the page's raw HTML and its sha256, so anything drawn from it can be
rechecked against the bytes it came from rather than trusted. It holds the
operator's confirmation, which the importer refuses a bundle without, and the
importer records that the retrieval method was `OPERATOR_CAPTURE` rather than
`DIRECT_FETCH` — a distinction the schema cares about, because who looked
matters as much as what they saw.

**It holds no personal information.** An amendment page names a scheme, a
number, a status and a geography. Where a register page does name an individual,
that is a `data_source` question answered in the rights register before the page
is captured, not a judgement made here.

## The licence these rest on

Victorian planning scheme data is published by the Department of Transport and
Planning under **CC BY 4.0**, which is recorded in `data_source` for
`VIC_PLANNING_AMENDMENTS` along with the date the terms were read and by whom.
Attribution is required and the register carries it. Capturing a page in a
browser is reading a published page; it is not circumventing anything, and the
403 above is Crown's own network policy rather than the publisher's.
