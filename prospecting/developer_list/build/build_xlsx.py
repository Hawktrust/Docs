import json, os, re, subprocess, sys
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

S = os.path.dirname(os.path.abspath(__file__))
subprocess.run([sys.executable, os.path.join(S, "merge.py")], check=True, stdout=subprocess.DEVNULL)
M = json.load(open(os.path.join(S, "merged.json")))
rows, checks, udia = M["rows"], M["checks"], M["udia_all"]
OUT = sys.argv[1]

DISPLAY = {"AHB Group": "AHB Group (now Mirrastone)", "Costa Asset Management": "Costa Property Group / Costa Asset Management",
           "Exford Waters": "Exford Waters (Wegg Pty Ltd)", "URBAN Land Projects": "Urban Land Projects",
           "XWISE Group": "XWISE Group"}
MSG_NAME = {"AHB Group": "Mirrastone", "Costa Asset Management": "Costa Property Group", "Exford Waters": "the Exford Waters team",
            "The Corcoris Group Developments Pty Ltd": "The Corcoris Group", "URBAN Land Projects": "Urban Land Projects",
            "Star Investment Group Australia (Star Marketing)": "Star Investment Group", "Gull & Company": "Gull & Co",
            "Wel.Co": "Wel.Co", "GURNER": "GURNER", "ID_Land": "ID_Land"}
SKIP = {  # left out of the Outreach tab, with the reason
    "Sunrise Ventures": "No public contact details",
    "The Range (Trafalgar) Pty Ltd": "Landowner entity, no contacts", "Trafalgar Property Developments Pty Ltd": "Landowner entity, no contacts",
    "Narracan Meadows developer (entity not identified)": "Developer not identified; only agent contact",
    "Hunter Park Country Estate developer (entity not identified)": "Developer not identified; only agent contact",
    "Cambrooke Property Pty Ltd": "Only selling-agent contact",
    "LOGOS": "Site now redirects to ESR Australia — contact ESR instead",
    "Mount Atkinson Holdings": "Domain no longer belongs to the company",
    "Eight Property Investments": "In liquidation (ASIC notice)", "Montego Homes": "Collapsed in 2024",
    "AVJennings": "Website now redirects to AVID Property Group — contact AVID instead",
}
MARKETS = ["Geelong", "Bendigo", "Ballarat", "Shepparton", "Kilmore", "Beveridge", "Moe", "Wollert", "Tarneit", "Truganina",
           "Werribee", "Melton", "Wyndham", "Mickleham", "Craigieburn", "Kalkallo", "Donnybrook", "Lara", "Armstrong Creek",
           "Drysdale", "Clyde", "Officer", "Pakenham", "Cranbourne", "Newborough", "Kilmore", "Wallan", "Sunbury"]

COUNCILS = [  # councils whose area holds one of the listed sites: name, email, phone, contact page, email source, suburbs
    ("City of Whittlesea", "info@whittlesea.vic.gov.au", "03 9217 2170",
     "https://www.whittlesea.vic.gov.au/About-us/Contact-us", "council annual report 2022-23 and official Facebook page", "Wollert"),
    ("Mitchell Shire Council", "mitchell@mitchellshire.vic.gov.au", "03 5734 6200",
     "https://www.mitchellshire.vic.gov.au/contact", "council contact page", "Beveridge"),
    ("Wyndham City Council", "mail@wyndham.vic.gov.au", "1300 023 411",
     "https://www.wyndham.vic.gov.au/contact-us", "council contact page", "Tarneit and Truganina"),
    ("Melton City Council", "csu@melton.vic.gov.au", "03 9747 7200",
     "https://www.melton.vic.gov.au/Council/Customer-Service/Contact-Us", "business.gov.au and vic.gov.au council listings",
     "Deanside, Bonnie Brook and Fraser Rise"),
    ("City of Greater Geelong", "contactus@geelongcity.vic.gov.au", "03 5272 5272",
     "https://www.geelongcity.vic.gov.au/contact", "council customer service charter and business.gov.au", "Geelong"),
]
REGIONAL_COUNCILS = [  # regional councils without a listed site: name, email, phone, contact page, email source, region
    ("City of Greater Bendigo", "requests@bendigo.vic.gov.au", "1300 002 642",
     "https://www.bendigo.vic.gov.au/contact-us", "council contact page", "Greater Bendigo"),
    ("City of Ballarat", "info@ballarat.vic.gov.au", "03 5320 5500",
     "https://www.ballarat.vic.gov.au/about-us/contact-us", "council contact page (phone from council eServices page)", "Ballarat"),
    ("Greater Shepparton City Council", "council@shepparton.vic.gov.au", "03 5832 9700",
     "https://greatershepparton.com.au/", "business.gov.au and OVIC agency listings", "Greater Shepparton"),
    ("Latrobe City Council", "latrobe@latrobe.vic.gov.au", "1300 367 700",
     "https://www.latrobe.vic.gov.au/Contact_Us", "council contact page and vic.gov.au listing", "Latrobe (Moe and Newborough)"),
]
REGIONAL_COUNCIL_BODY = """Hi Property and Strategic Acquisitions Team,

My name is Inder Sandhu with Crown Real Estate Agents. I specialise in development land across Melbourne's western and northern growth corridors and regional Victoria, including {region}.

I currently have development sites available across Wollert, Beveridge, Tarneit, Geelong, Deanside, Bonnie Brook, Fraser Rise and Truganina:

* Shovel-ready residential and industrial.
* Permit-approved townhouse sites, including one for 44 townhouses.
* Childcare and townhouse sites, both raw and approved.
* About 50 acres of investigation-area land.

Given Council's role in planning for growth in {region}, I'd welcome the chance to understand Council's strategic land priorities, so I can bring you suitable sites as they come up.
Could you please forward this to the appropriate contact in Council's property or strategic acquisitions team?

If you'd rather not hear from me about sites, just let me know and I won't contact you again.

{signature}"""
COUNCIL_BODY = """Hi Property and Strategic Acquisitions Team,

My name is Inder Sandhu with Crown Real Estate Agents. I specialise in development land across Melbourne's western and northern growth corridors and regional Victoria.

I have development sites available in {suburbs}, within {council}'s area, as well as in {others}:

* Shovel-ready residential and industrial.
* Permit-approved townhouse sites, including one for 44 townhouses.
* Childcare and townhouse sites, both raw and approved.
* About 50 acres of investigation-area land.

Given Council's role in planning for growth in {suburbs}, some of these sites may suit Council's strategic land or community infrastructure needs.
Could you please forward this to the appropriate contact in Council's property or strategic acquisitions team so I can share further details?

If you'd rather not hear from me about sites, just let me know and I won't contact you again.

{signature}"""

SITES = ["Wollert", "Beveridge", "Tarneit", "Geelong", "Deanside", "Bonnie Brook", "Fraser Rise", "Truganina"]
def others(suburbs):
    rest = [x for x in SITES if x not in suburbs]
    return ", ".join(rest[:-1]) + " and " + rest[-1]

ROLE = {
    "Homes Victoria": "delivering new homes across Melbourne's growth areas and regional Victoria",
    "Community Housing Victoria Ltd": "delivering community and affordable housing across Victoria",
    "Housing Choices Australia Limited (Victoria)": "delivering community and affordable housing across Victoria",
    "HousingFirst Ltd": "delivering community and affordable housing across Melbourne",
    "Launch Housing": "delivering housing for people experiencing homelessness across Melbourne",
    "Bolton Clarke": "delivering retirement living and aged care communities across Victoria",
}
MSG_NAME.update({"Community Housing Victoria Ltd": "Community Housing Limited", "Housing Choices Australia Limited (Victoria)": "Housing Choices Australia",
                 "HousingFirst Ltd": "HousingFirst"})

def msg_name(dev):
    if dev in MSG_NAME: return MSG_NAME[dev]
    return re.sub(r"\s+(Pty\.? Ltd\.?|Limited|Ltd)$", "", dev).strip()

def area(projects):
    found = []
    for m in MARKETS:
        if re.search(r"\b" + m + r"\b", projects) and m not in found: found.append(m)
    if not found: return ""
    return found[0] if len(found) == 1 else ", ".join(found[:-1][:3]) + " and " + found[min(len(found) - 1, 3)]

BODY = """Hi Acquisition Team,

My name is Inder Sandhu with Crown Real Estate Agents. I specialise in development land across Melbourne's western and northern growth corridors and regional Victoria.

I have development sites available across Wollert, Beveridge, Tarneit, Geelong, Deanside, Bonnie Brook, Fraser Rise and Truganina:

* Shovel-ready residential and industrial.
* Permit-approved townhouse sites, including one for 44 townhouses.
* Childcare and townhouse sites, both raw and approved.
* About 50 acres of investigation-area land.

Given {who} active presence {where}, I believe these sites would be a strong fit for your acquisitions pipeline.
Could you please direct me to the appropriate contact in your acquisitions department so I can share further details?

If you'd rather not hear from me about sites, just let me know and I won't contact you again.

{signature}"""

SIGNATURE = """Kind Regards,
Inder Sandhu
Principal /OIEC
CROWN REAL ESTATE AGENTS
Phone no: 0484 926 324
Inder@crownrea.com.au
www.crownrea.com.au

Disclaimer : This email and any attachments are confidential and intended solely for the intended recipient(s). If you are not the intended recipient, please notify the sender immediately, delete this email, and refrain from disclosing, copying, or using any part of this communication.

The information in this email is for general informational purposes only and should not be considered legal, financial, or professional advice. Crown Real Estate Agencts makes no guarantees regarding its accuracy or completeness. Any views expressed are those of the author and do not necessarily reflect the views of Crown Real Estate Agents.

Crown Real Estate Agents complies with all relevant Victorian and Australian laws, including the Estate Agents Act 1980 (Vic) and the Australian Consumer Law. We are committed to fair trading, privacy, and anti-discrimination practices, as required by the Equal Opportunity Act 2010 (Vic) and the Privacy Act 1988 (Cth).

While precautions are taken to prevent viruses, Crown Real Estate Agents accepts no liability for damage caused by email transmission.

No binding agreements may be concluded via email without written confirmation by an authorized representative of Crown Real Estate Agents."""

FONT = "Arial"
HDR_FILL = PatternFill("solid", fgColor="1F3864")
HDR_FONT = Font(name=FONT, bold=True, color="FFFFFF")
BODY_FONT = Font(name=FONT, size=10)
FLAG_FILL = PatternFill("solid", fgColor="FFF2CC")

def sheet(wb, title, headers, data, widths, wrap_cols=()):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for c in ws[1]:
        c.fill, c.font = HDR_FILL, HDR_FONT
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for row in data: ws.append(row)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for r in ws.iter_rows(min_row=2):
        for c in r:
            c.font = BODY_FONT
            c.alignment = Alignment(wrap_text=c.column in wrap_cols, vertical="top")
            if isinstance(c.value, str) and c.value.startswith("http"):
                c.hyperlink = c.value
                c.font = Font(name=FONT, size=10, color="0563C1", underline="single")
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions
    ws.row_dimensions[1].height = 32
    return ws

wb = Workbook(); wb.remove(wb.active)

# 1. Main list
cols = list(rows[0].keys())
data = []
for i, r in enumerate(rows, 1):
    v = [r[c] for c in cols]
    v[0] = DISPLAY.get(r["Developer"], r["Developer"])
    data.append([i] + v)
widths = [5, 30, 26, 32, 15, 34, 26, 30, 30, 28, 48, 11, 28, 26, 8, 8, 8, 8, 8, 26, 50, 60]
ws = sheet(wb, "Developer List", ["#"] + cols, data, widths, wrap_cols=(3, 11, 13, 21, 22))
fc = cols.index("Cross-check flags") + 2
for row in ws.iter_rows(min_row=2):
    if row[fc - 1].value: row[fc - 1].fill = FLAG_FILL

# 2. Outreach
out, skipped = [], []
for r in rows:
    dev = r["Developer"]
    if dev in SKIP: skipped.append([DISPLAY.get(dev, dev), SKIP[dev]]); continue
    a = area(r["Regional projects / footprint"])
    where = f"in {a}" if a else "across Melbourne's growth corridors and regional Victoria"
    if dev in ROLE:  # government and not-for-profit bodies: speak to their role, not a listed project
        where = "in " + ROLE[dev]
    # use the contact page unless it is a third-party listing, Facebook page or non-contact page
    third = ("facebook.com", "crunchbase.com", "trustpilot.com", "acnc.gov.au", "openlot.com.au", "health.qld.gov.au",
             "2020ar.goodman.com", "complaints-management")
    form = r["Contact page"] if not any(t in r["Contact page"] for t in third) else ""
    form = form or r["Website"] or r["Contact page"] or "No website — use email / phone"
    out.append([DISPLAY.get(dev, dev), form, r["Website"], r["Email"] if "@" in r["Email"] else "", r["Phone"],
                "Inder Sandhu", "inder@crownrea.com.au", "0484926324", "Crown Real Estate Agents",
                "Development sites – Wollert, Beveridge, Tarneit, Geelong & more",
                BODY.format(signature=SIGNATURE, who=(lambda n: n + ("'" if n.endswith('s') else "'s"))(msg_name(dev)), where=where), "Not sent", "", ""])
    if dev in ROLE:
        out[-1][10] = out[-1][10].replace("active presence in ", "role in ")
for name, em, ph, page, source, suburbs in COUNCILS:
    out.append([name, page, re.sub(r"(https://[^/]+).*", r"\1", page), em, ph,
                "Inder Sandhu", "inder@crownrea.com.au", "0484926324", "Crown Real Estate Agents",
                f"Development sites in {suburbs.replace(' and ', ' & ')}",
                COUNCIL_BODY.format(signature=SIGNATURE, suburbs=suburbs, council=("the " if name.startswith("City of") else "") + name, others=others(suburbs)), "Not sent", "",
                f"Local council – sites in {suburbs}. General inbox; email source: {source}"])
for name, em, ph, page, source, region in REGIONAL_COUNCILS:
    out.append([name, page, re.sub(r"(https://[^/]+).*", r"\1", page), em, ph,
                "Inder Sandhu", "inder@crownrea.com.au", "0484926324", "Crown Real Estate Agents",
                "Development land – Crown Real Estate Agents",
                REGIONAL_COUNCIL_BODY.format(signature=SIGNATURE, region=region), "Not sent", "",
                f"Regional council – no listed site in its area yet. General inbox; email source: {source}"])
oh = ["Developer / council", "Contact form / contact page", "Website", "Published email", "Phone", "Your name", "Your email",
      "Your mobile", "Company", "Subject", "Message (personalised)", "Status", "Date sent", "Response / notes"]
ws = sheet(wb, "Outreach", oh, out, [30, 40, 30, 32, 15, 13, 24, 12, 22, 34, 80, 11, 11, 30], wrap_cols=(11,))
for row in ws.iter_rows(min_row=2):
    ws.row_dimensions[row[0].row].height = 409
ws.cell(row=len(out) + 3, column=1, value="Left out of outreach (and why):").font = Font(name=FONT, bold=True)
for j, (n, why) in enumerate(skipped):
    ws.cell(row=len(out) + 4 + j, column=1, value=n).font = BODY_FONT
    ws.cell(row=len(out) + 4 + j, column=2, value=why).font = BODY_FONT

# 3. Cross-check
sheet(wb, "Cross-check", ["Developer", "Differences between sources (your workbook vs UDIA vs fresh research)"],
      [[DISPLAY.get(c["Developer"], c["Developer"]), c["Flags"]] for c in checks], [34, 120], wrap_cols=(2,))

# 4. UDIA – every member
sheet(wb, "UDIA All Members", ["Page", "Name", "Category", "Location", "Phone", "Email", "Specialties", "Website"],
      [[m["page"], m["name"], m["category"], m["location"], m["phone"], m["email"], m["specialties"], m["website"]] for m in udia],
      [6, 36, 24, 22, 15, 32, 50, 36], wrap_cols=(7,))

# 5. Sources
notes = [
    ["Your developer list (49 names)", "Pasted in chat."],
    ["Regional table (Geelong, Bendigo, Ballarat, Shepparton, Kilmore, Beveridge, Moe)", "Pasted in chat. 'Private landowners/developers – Moe' researched separately (column 'Moe private developer')."],
    ["Your workbook 16872595-Developer_List_.xlsx", "Developer Universe, Regional Projects and Decision Makers tabs cross-checked; every developer included."],
    ["UDIA Victoria members directory", "All 34 pages (https://udiavic.com.au/members-directory/) scraped 2 Oct 2026. Every member is on the 'UDIA All Members' tab; members with category Developer or a Developer specialty are in the main list."],
    ["Fresh web research, 2 Oct 2026", "Company contact pages, estate sites, directories. Field sources column shows which source each website/phone/email came from (Research > UDIA > Workbook)."],
    ["Email rule", "Only emails actually published somewhere are listed. None were guessed. 'Contact form only' means the company publishes no email."],
    ["Two different 'North Quarter' estates", "The North Quarter, North Shepparton = Urban Land Projects (thenorthquarter.com.au). North Quarter, Newborough/Moe = Solovey (north-quarter.com.au)."],
    ["Lendlease", "Sold its Victorian communities (Atherstone, Aurora, Averley, Harpley) to Stockland and Supalai in Nov 2024."],
    ["Star Investment Group (Lake Narracan)", "Investor concerns about this scheme are reported online — check before engaging."],
    ["Outreach tab", "Message is personalised per developer (name + area). Added an opt-out line, as the Spam Act requires a way to opt out of commercial messages. Fill Status / Date sent as you go."],
]
sheet(wb, "Sources & Notes", ["Item", "Detail"], notes, [55, 120], wrap_cols=(1, 2))

wb.save(OUT)
print("saved", OUT, len(rows), "developers;", len(out), "outreach rows;", len(skipped), "skipped;", len(checks), "flags")
