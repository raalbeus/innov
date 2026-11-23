"""Schema of the VITRO Reference Register workbook.

Facility evidence (power, cooling, ratings, certifications, security, racks,
connectivity, SLAs, office rental) comes from the VITRO Specifications Table,
read by read_specs.py. This register holds only what that table lacks.

One sheet per evidence type. Every row has an ID (used as the evidence
reference in the compliance matrix), a Source Document and an As-of Date.
A row without a Source Document cannot support a Comply rating.
"""

# sheet name -> (ID prefix, purpose, [(column, width, help text)])
SHEETS = {
    "Contracts": (
        "C",
        "Completed and ongoing contracts, for the Single Largest Completed Contract (SLCC) check.",
        [
            ("ID", 9, "C-001, C-002 ..."),
            ("Client / Procuring Entity", 26, "Agency or company name"),
            ("Contract Title", 34, "As written on the contract"),
            ("Scope Description", 48, "What was delivered. Used to judge whether it is 'similar' to the bid."),
            ("Scope Tags", 26, "Semicolon list, e.g. colocation; DR seats; connectivity; managed services; cloud; BCF"),
            ("Government Client (Y/N)", 12, "Y or N"),
            ("Contract Amount (PHP, VAT inc.)", 18, "Number, no text"),
            ("CPI-Adjusted Amount (PHP)", 18, "Optional. Amount adjusted to current prices per PSA CPI, as the bid rules require. Leave blank if not computed."),
            ("Start Date", 12, "YYYY-MM-DD"),
            ("Completion Date", 12, "YYYY-MM-DD. Date of final acceptance."),
            ("Status", 14, "Completed / Ongoing / Awarded-not-started"),
            ("Completion Proof", 28, "e.g. Certificate of Final Acceptance, Official Receipt no."),
            ("Recurring Component (Y/N)", 12, "Y if part of the value is recurring service still running. Some bids exclude this (e.g. BI BCF Bid Bulletin 1, item 18)."),
            ("Source Document", 30, "File name / DMS link of the contract or acceptance"),
            ("As-of Date", 12, "YYYY-MM-DD this row was last checked"),
            ("Owner", 16, "Who maintains this row"),
        ],
    ),
    "DR Seats & Office": (
        "SEAT",
        "Disaster Recovery (DR) seats, work-area recovery and office space.",
        [
            ("ID", 9, "SEAT-001 ..."),
            ("Site", 18, "Site ID or name"),
            ("Type", 18, "DR seat / Dedicated office / Shared office / Command center"),
            ("Quantity Available", 12, "Number"),
            ("Quantity Basis", 26, "Required. e.g. 'seats, dedicated, as of date'"),
            ("Amenities", 34, "PCs, phones, network, pantry, parking"),
            ("Activation Time", 14, "e.g. 2 hours"),
            ("Source Document", 30, ""),
            ("As-of Date", 12, ""),
            ("Owner", 16, ""),
        ],
    ),
    "Personnel": (
        "PER",
        "Certified personnel, recorded by role and count. Keep personal data out unless needed (Data Privacy Act of 2012).",
        [
            ("ID", 9, "PER-001 ..."),
            ("Role", 24, "e.g. Project Manager, Network Engineer"),
            ("Certification", 26, "e.g. PMP, CCNP, CISSP, CDCP, DPO training"),
            ("Issuer", 18, ""),
            ("Headcount Holding It", 12, "Number"),
            ("Earliest Expiry", 12, ""),
            ("Dedicated to Projects (Y/N)", 12, "Can be assigned exclusively to one project"),
            ("Source Document", 30, "HR certificate file"),
            ("As-of Date", 12, ""),
            ("Owner", 16, ""),
        ],
    ),
    "Site Distances": (
        "DIST",
        "Measured distances from VITRO sites to client reference locations (e.g. a minimum-distance rule for a DR site).",
        [
            ("ID", 9, "DIST-001 ..."),
            ("Site", 18, "Site name exactly as in the VITRO Specifications Table, e.g. VITRO Clark"),
            ("Reference Location", 30, "e.g. Bureau of Immigration Main Office, Magallanes Drive, Intramuros, Manila"),
            ("Distance (km)", 12, "Number"),
            ("Measurement Basis", 26, "Required. e.g. 'straight-line, map tool X' or 'road distance'"),
            ("Source Document", 30, "Screenshot or measurement record"),
            ("As-of Date", 12, ""),
            ("Owner", 16, ""),
        ],
    ),
    "Lead Times": (
        "LT",
        "Standard delivery lead times, for the delivery feasibility check.",
        [
            ("ID", 9, "LT-001 ..."),
            ("Category", 24, "e.g. Standard colocation, Cage build, Hardware procurement, DR seat fit-out, Cross-connect"),
            ("Description", 40, "What the lead time covers"),
            ("Standard Lead Time (calendar days)", 14, "Number"),
            ("Condition", 30, "e.g. 'no customization', 'imported hardware'"),
            ("Source Document", 30, "e.g. Delivery team guideline"),
            ("As-of Date", 12, ""),
            ("Owner", 16, ""),
        ],
    ),
}

# Prefix -> sheet, for evidence lookup
PREFIX_SHEET = {v[0]: k for k, v in SHEETS.items()}

# Columns holding an expiry date, per sheet
EXPIRY_COL = {
    "Personnel": "Earliest Expiry",
}

HEADER_ROW = 4  # row of column headers on each sheet; data starts on HEADER_ROW + 1


def load_register(path):
    """Return {sheet: [row dict]} and {ID: (sheet, row dict)} from a register workbook."""
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True)
    rows, by_id = {}, {}
    for sheet in SHEETS:
        if sheet not in wb.sheetnames:
            rows[sheet] = []
            continue
        ws = wb[sheet]
        headers = [c.value for c in ws[HEADER_ROW]]
        out = []
        for r in ws.iter_rows(min_row=HEADER_ROW + 1, values_only=True):
            if not any(v not in (None, "") for v in r):
                continue
            d = {h: v for h, v in zip(headers, r) if h}
            if not d.get("ID"):
                continue
            # An ID with nothing else (e.g. the template's pre-filled C-001) is not a row
            if not any(v not in (None, "") for k, v in d.items() if k != "ID"):
                continue
            out.append(d)
            by_id[str(d["ID"]).strip()] = (sheet, d)
        rows[sheet] = out
    return rows, by_id
