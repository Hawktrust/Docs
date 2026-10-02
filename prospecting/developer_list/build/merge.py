"""Merge every developer source into one de-duplicated list."""
import csv, json, os, re
from collections import OrderedDict

S = os.path.dirname(os.path.abspath(__file__))
def load(f, default):
    p = os.path.join(S, f)
    return json.load(open(p)) if os.path.exists(p) else default

USER_LIST = """ABN Group|Accord Property Group|AHB Group|APD Projects|AVID Property Group|Abiwood|Balcon Group|Bevan Property Group|Bisinella Developments|Birchgrove Property|Brown Property Group|Cedar Woods|Central Equity|Costa Asset Management|Dennis Family Corporation|Development Edge|Development Victoria|Exford Waters|Frasers Property Australia|Goldfields|GURNER|Gull & Company|ID_Land|Intrapac Property|Jinding|Lendlease|MAB Corporation|Mirvac|Monno|Moremac Property Group|Morgan & Griffin|Newland Developers|Nexus Developments|Oreana|Peet|Ramsey Property Group|Risland|Riverlee|Satterley|SIG Group|SOHO Living|Stockland|Sunrise Ventures|Tripleton|Villawood Properties|Wel.Co|Wolfdene|YourLand|3L Alliance""".split("|")

# Explicit aliases: anything on the left is the same company as the right.
ALIAS = {
    "ahb australia": "ahb", "mirrastone": "ahb", "ahb now mirrastone": "ahb",
    "gull and company": "gull", "gull and co": "gull",
    "costa asset management": "costa", "costa property group costa asset management": "costa",
    "exford waters developer wegg": "exford waters", "wegg": "exford waters",
    "central equity land": "central equity",
    "goldfields": "goldfields",
    "newland developers": "newland", "newland": "newland",
    "oreana": "oreana", "peet": "peet", "risland": "risland",
    "wolfdene": "wolfdene", "wolfdene management": "wolfdene",
    "yourland": "yourland", "monno": "monno",
    "satterley": "satterley", "cedar woods": "cedar woods",
    "bauenort management": "bauenort", "begley": "begley",
    "antipodean land": "antipodean land", "sjd marketing t as sjd homes": "sjd homes",
    "creation homes vic": "creation homes", "buildcap development management": "buildcap", "l bisinella": "bisinella",
    "ingenia communities victoria": "ingenia communities", "perri projects": "perri", "perri": "perri",
    "north quarter development entity": "north quarter moe", "north quarter estate developer": "urban land projects",
    "montana estate estate developer": "marlton", "arbor estates": "birchgrove",
    "north quarter newborough moe developer entity not public": "solovey",
    "homes victoria community housing victoria chvl": "homes victoria", "ooranya estate developer": "corcoris", "arc living arc": "arc living",
    "id land": "id land", "intrapac": "intrapac",
}
STOP = r"\b(pty|ltd|limited|group|corporation|corp|properties|property|developments|developers|development|australia|holdings|the|management)\b"

def key(name):
    n = name.lower().replace("&", " and ").replace("_", " ")
    n = re.sub(r"\(.*?\)", lambda m: " " + m.group(0)[1:-1] + " ", n)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    if n in ALIAS: return ALIAS[n]
    k = re.sub(r"\s+", " ", re.sub(STOP, " ", n)).strip() or n
    # Keep government / multi-word names that would collapse to nothing meaningful
    if n.startswith("development victoria"): return "development victoria"
    if n.startswith("development edge"): return "development edge"
    return ALIAS.get(k, k)

recs = OrderedDict()
def rec(name):
    k = key(name)
    if k not in recs:
        recs[k] = dict(name=name, aliases=set(), sources=set(), website={}, phone={}, email={},
                       address={}, contact_page="", category=set(), projects=[], priority="",
                       dm=[], notes=[], udia_specialties="")
    r = recs[k]
    if name != r["name"]: r["aliases"].add(name)
    return r

BAD_EMAILS = {"enquiries@centuria.com.au", "makeareferral@boltonclarke.com.au", "test"}
def put(r, field, src, val):
    val = (val or "").strip() if isinstance(val, str) else ("" if val is None else str(val))
    if field == "email" and val.lower() in BAD_EMAILS: return
    if val and val.lower() not in ("contact form", "contact form only", "test"):
        r[field].setdefault(src, val)

# 1. User's own list
for n in USER_LIST:
    rec(n)["sources"].add("Your list")

# 2. Pasted regional table
for row in csv.DictReader(open(os.path.join(S, "regional.tsv")), delimiter="\t"):
    d = row["developer"]
    if d.startswith("Private landowners"):
        continue  # replaced by the Moe research below
    r = rec({"North Quarter": "URBAN Land Projects", "Montana Estate": "Marlton Group",
             "Ooranya": "The Corcoris Group Developments Pty Ltd"}.get(d, d))
    r["sources"].add("Regional table")
    estate = {"North Quarter": "The North Quarter — ", "Montana Estate": "Montana Estate — ", "Ooranya": "Ooranya Estate — "}.get(d, "")
    r["projects"].append(f'{row["region"]}: {estate}{row["project"]}')
    if row["priority"] and not r["priority"]: r["priority"] = row["priority"]

# 3. Workbook
wb = load("workbook.json", {})
for d in wb.get("Developer Universe", []):
    r = rec(d["Developer"]); r["sources"].add("Workbook")
    put(r, "website", "Workbook", d["Website"]); put(r, "phone", "Workbook", d["Phone"])
    if "@" in str(d["Email / Contact Route"] or ""): put(r, "email", "Workbook", d["Email / Contact Route"])
    put(r, "address", "Workbook", d["Office / HQ"])
    if d["Asset Classes"]: r["category"].add(d["Asset Classes"])
    if d["Example Named Projects"]: r["projects"].append(f'{d["Verified Footprint"]}: {d["Example Named Projects"]}')
    if d["Priority"] and not r["priority"]: r["priority"] = f'Tier {d["Priority"]}'
for d in wb.get("Decision Makers", []):
    if not d.get("Developer"): continue
    r = rec(d["Developer"]); r["sources"].add("Workbook")
    em = d["Published Business Email"] if "@" in str(d["Published Business Email"] or "") else ""
    r["dm"].append((d["Primary Contact"] or "", d["Role"] or "", em, d["Public Phone"] or "", d["Profile / LinkedIn URL"] or ""))
for d in wb.get("Regional Projects", []):
    ents = [e.strip() for e in str(d["Developer / Delivery Entity"]).split(";")]
    for e in ents:
        if e.lower().startswith(("multiple", "developer entity not")): continue
        r = rec("Solovey" if e == "North Quarter development entity" else e)
        r["sources"].add("Workbook")
        r["projects"].append(f'{d["Focus Market"]} – {d["Suburb / Corridor"]}: {d["Project"]} ({d["Stage"]})')

# 4. UDIA directory (developers only, plus anything with a developer specialty)
udia_all = []
for f in ("udia_p01_12.json", "udia_p13_24.json", "udia_p25_34.json"):
    udia_all += load(f, [])
udia_all = [m for m in udia_all if m["name"].strip().lower() != "test"]
for m in udia_all:
    if m["category"] != "Developer" and "Developer" not in (m["specialties"] or ""):
        continue
    r = rec(m["name"]); r["sources"].add("UDIA directory")
    put(r, "website", "UDIA", m["website"]); put(r, "phone", "UDIA", m["phone"])
    put(r, "email", "UDIA", m["email"]); put(r, "address", "UDIA", m["location"])
    r["category"].add("UDIA: " + m["category"]); r["udia_specialties"] = m["specialties"]

# 5. Fresh web research
for f in ("research_A.json", "research_B.json", "research_C.json", "research_moe.json"):
    for d in load(f, []):
        r = rec(d["name"]); r["sources"].add("Web research")
        put(r, "website", "Research", d.get("website")); put(r, "phone", "Research", d.get("phone"))
        put(r, "email", "Research", d.get("email")); put(r, "address", "Research", d.get("address"))
        r["contact_page"] = r["contact_page"] or d.get("contact_page", "")
        if d.get("estate"): r["projects"].append(f'Moe: {d["estate"]}')
        if "moe" in f: r["sources"].add("Moe private developers")
        if d.get("notes"): r["notes"].append(d["notes"])

# 6. Email-enrichment pass
for f in ("emails_1.json", "emails_2.json", "emails_3.json"):
    for d in load(f, []):
        r = recs.get(key(d["name"]))
        if not r: continue
        r["sources"].add("Web research")
        put(r, "email", "Research", d.get("email")); put(r, "phone", "Research", d.get("phone"))
        if d.get("email_source_url") and not r["contact_page"]: r["contact_page"] = d["email_source_url"]
        if d.get("notes"): r["notes"].append(d["notes"])

ORDER = ("Research", "UDIA", "Workbook")
def best(r, field):
    for s in ORDER:
        if s in r[field]: return r[field][s], s
    return "", ""

def norm_phone(p): return re.sub(r"\D", "", p)
def norm_site(u): return re.sub(r"^https?://(www\.)?|/.*$", "", u.lower())

rows, checks = [], []
for k, r in recs.items():
    listing = {k: v for k, v in r["website"].items() if "openlot.com.au" in v}
    for k in listing: r["website"].pop(k)
    if listing: r["notes"].append("No company website found in sources; estate listing: " + next(iter(listing.values())))
    web, ws = best(r, "website"); ph, ps = best(r, "phone"); em, es = best(r, "email"); ad, _ = best(r, "address")
    flags = []
    phones = {s: v for s, v in r["phone"].items()}
    if len({norm_phone(v)[-8:] for v in phones.values()}) > 1:
        flags.append("Phone differs: " + "; ".join(f"{s} {v}" for s, v in phones.items()))
    sites = {s: v for s, v in r["website"].items()}
    if len({norm_site(v) for v in sites.values()}) > 1:
        flags.append("Website differs: " + "; ".join(f"{s} {v}" for s, v in sites.items()))
    emails = {s: v for s, v in r["email"].items()}
    if len({v.lower() for v in emails.values()}) > 1:
        flags.append("Other emails: " + "; ".join(f"{s} {v}" for s, v in emails.items() if v != em))
    if "satterly.com.au" in em: flags.append("UDIA email domain spelled 'satterly' — website is satterley.com.au; confirm before use")
    if "gmail.com" in em: flags.append("Email is a personal-looking gmail as published in UDIA directory")
    dm = [x for x in r["dm"] if x[0]]
    dm_txt = "; ".join(f"{n} ({ro})" for n, ro, *_ in dm)
    dm_email = "; ".join(f"{e}" for n, ro, e, *_ in dm if e)
    row = OrderedDict([
        ("Developer", r["name"]),
        ("Also listed as", "; ".join(sorted(r["aliases"]))),
        ("Website", web), ("Phone", ph),
        ("Email", em or ("Contact form only" if web else "")),
        ("Office / HQ", ad),
        ("Contact page", r["contact_page"]),
        ("Decision maker(s)", dm_txt), ("Decision-maker email", dm_email),
        ("Regional projects / footprint", " | ".join(dict.fromkeys(r["projects"]))),
        ("Priority", r["priority"]),
        ("Type", "; ".join(sorted(r["category"]))),
        ("UDIA specialties", r["udia_specialties"]),
        ("In your list", "Yes" if "Your list" in r["sources"] else ""),
        ("In regional table", "Yes" if "Regional table" in r["sources"] else ""),
        ("In your workbook", "Yes" if "Workbook" in r["sources"] else ""),
        ("UDIA member", "Yes" if "UDIA directory" in r["sources"] else ""),
        ("Moe private developer", "Yes" if "Moe private developers" in r["sources"] else ""),
        ("Field sources", f"web:{ws or '-'} phone:{ps or '-'} email:{es or '-'}"),
        ("Cross-check flags", " || ".join(flags)),
        ("Research notes", " ".join(r["notes"])),
    ])
    rows.append(row)
    if flags: checks.append({"Developer": r["name"], "Flags": " || ".join(flags)})

rows.sort(key=lambda x: re.sub(r"[^a-z0-9]", "", x["Developer"].lower()))
json.dump({"rows": rows, "checks": checks, "udia_all": udia_all}, open(os.path.join(S, "merged.json"), "w"), indent=1)
if __name__ == "__main__":
    print(len(rows), "developers;", sum(1 for x in rows if x["Phone"]), "phones;",
          sum(1 for x in rows if "@" in x["Email"]), "emails;", sum(1 for x in rows if x["Website"]), "websites;",
          len(checks), "flagged")
    for x in rows:
        if x["Also listed as"]: print("  MERGED:", x["Developer"], "<=", x["Also listed as"])
