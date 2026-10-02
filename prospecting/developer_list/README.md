# Victorian developer list

One de-duplicated list of 196 Victorian property developers, with website, phone,
published email, office, decision makers, regional projects and where each detail
came from. Compiled 2 October 2026.

| File | What it is |
|---|---|
| `Victorian_Developer_List.xlsx` | The list. Tabs: Developer List, Outreach, Cross-check, UDIA All Members, Sources & Notes |
| `Victorian_Developer_List.csv` | The Developer List tab as CSV |
| `build/` | The scripts and raw source data that produce both files |

## Sources

- The developer list and regional project table supplied in chat (Geelong, Bendigo,
  Ballarat, Shepparton, Kilmore, Beveridge, Moe).
- The prospecting workbook `16872595-Developer_List_.xlsx` (Developer Universe,
  Regional Projects and Decision Makers tabs), exported to `build/workbook.json`.
- The UDIA Victoria members directory, all 34 pages
  (<https://udiavic.com.au/members-directory/>), in `build/udia_*.json`. Members
  categorised Developer, or listing a Developer specialty, are in the main list.
- Web research on company contact pages, estate sites and directories, in
  `build/research_*.json` (contacts) and `build/emails_*.json` (email follow-up).

Where sources give a value, research is preferred over UDIA, and UDIA over the
workbook. The `Field sources` column says which one each website, phone and email
came from, and the `Cross-check` tab lists every disagreement between them.

## Rules the data follows

- Every email was seen published somewhere. None were guessed or built from a
  pattern. "Contact form only" means the company publishes no email.
- Some emails are weaker than a general inbox: a selling agent's, a named staff
  member's, an overseas parent company's or an investor-relations inbox. The
  `Research notes` column says which.
- The list holds business contact details of named people (decision makers and
  staff emails). Treat it as personal information: use it only for business
  outreach relevant to their role, and honour any request to stop.
- The Outreach tab's message includes an opt-out line, because the Spam Act 2003
  requires every commercial electronic message to offer a way to unsubscribe.

## Rebuilding

```
cd prospecting/developer_list/build
python build_xlsx.py ../Victorian_Developer_List.xlsx
```

`build_xlsx.py` runs `merge.py` first, which reads the JSON and TSV sources beside
it. The CSV is the `rows` list that `merge.py` writes to `merged.json`.
