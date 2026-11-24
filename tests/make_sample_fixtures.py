#!/usr/bin/env python3
"""Write SAMPLE (synthetic) fixtures for sandbox testing, with no confidential data.

Usage: python3 tests/make_sample_fixtures.py OUT_DIR

Writes:
  OUT_DIR/SAMPLE_Specifications_Table.xlsx  same layout as the VITRO table: site names in row 1 from
                                             column H, sections in column A, items in column C
  OUT_DIR/replay/terms.json                  saved "AI" output for AI_MODE=replay
  OUT_DIR/replay/requirements.json
Every site, figure and requirement here is invented. Do not read anything in them as VITRO data.
"""
import json
import sys
from pathlib import Path

from openpyxl import Workbook

SITES = [("SAMPLE Site A", "Sample City 1", "Owned"), ("SAMPLE Site B", "Sample City 2", "Leased"),
         ("SAMPLE Site C", "Sample City 3", "Owned")]

# (section or None, group, item, description, baseline, [site A, site B, site C])
ROWS = [
    ("General Facilities", None, None, None, None, None),
    (None, "Power", "UPS redundancy", "UPS configuration", "N+1", ["n\n(2N)", "n\n(N+1)", "q"]),
    (None, "Power", "Generator autonomy", "Fuel on site", "24 hours", ["n\n(48 hours)", "n\n(24 hours)", ""]),
    (None, "Cooling", "Precision cooling", "CRAC/CRAH redundancy", "N+1", ["n", "n", "q"]),
    ("Rack & Cage", None, None, None, None, None),
    (None, "Rack", "Dedicated cage", "Lockable cage", "-", ["n", "i", ""]),
    (None, "Rack", "Power per rack", "Maximum kVA per rack", "-", ["n\n(10 kVA)", "n\n(5 kVA)", ""]),
    ("Connectivity", None, None, None, None, None),
    (None, "Carriers", "Carrier neutral", "Multiple carriers in the Meet-Me-Room", "-", ["n", "n", "q"]),
    (None, "Carriers", "Dedicated Internet Access", "DIA available", "-", ["n", "n", "n"]),
    ("Other Optional Services", None, None, None, None, None),
    (None, "Office", "Office rental", "Dedicated office space", "-", ["n", "q", ""]),
    (None, "DR", "DR seats", "Disaster recovery seats", "-", ["n", "i", ""]),
    ("Certification", None, None, None, None, None),
    (None, "ISO", "ISO/IEC 27001", "Information security certificate", "-", ["n", "n", ""]),
    (None, "Tier", "TIA-942 rating", "Facility rating", "-", ["n\n(Rated 3)", "q", ""]),
]


def spec_table(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "VITRO DC Specs"
    ws.cell(1, 1, "Data Center name")
    ws.cell(2, 1, "City")
    ws.cell(3, 1, "Data Center ownership type")
    for i, (name, city, own) in enumerate(SITES):
        ws.cell(1, 8 + i, name)
        ws.cell(2, 8 + i, city)
        ws.cell(3, 8 + i, own)
    r = 4
    rowmap = {}
    for section, group, item, desc, base, vals in ROWS:
        r += 1
        if section:
            ws.cell(r, 1, section)
            continue
        ws.cell(r, 1, group)
        ws.cell(r, 3, item)
        ws.cell(r, 4, desc)
        ws.cell(r, 5, base)
        for i, v in enumerate(vals):
            if v:
                ws.cell(r, 8 + i, v)
        rowmap[item] = f"SPEC-{r}"
    ws.cell(r + 2, 1, "SAMPLE DATA FOR SANDBOX TESTING. NOT VITRO SPECIFICATIONS.")
    wb.save(path)
    return rowmap


def req(rid, clause, category, text, scope="VITRO DC", sites=None, rating="Unverified", clarification="", evidence=None):
    return {"id": rid, "doc": "SAMPLE TOR", "page": 1, "clause": clause, "section": "Technical Specifications",
            "text": text, "category": category, "scope": scope, "mandatory": True, "amended_by": "",
            "amended_text": "", "rating": rating, "evidence": evidence or [], "rationale": "Sample rating.",
            "clarification": clarification, "sites": sites or {}}


def site(rating, *evidence, note=""):
    return {"rating": rating, "evidence": list(evidence), "note": note}


def replay(out, m):
    a, b, c = (s[0] for s in SITES)
    reqs = [
        req("R-001", "7.1", "Colocation", "UPS in N+1 or better.",
            sites={a: site("Comply", m["UPS redundancy"]), b: site("Comply", m["UPS redundancy"]),
                   c: site("Gap", m["UPS redundancy"])}),
        req("R-002", "7.2", "Colocation", "Generator fuel for at least 24 hours.",
            sites={a: site("Comply", m["Generator autonomy"]), b: site("Comply", m["Generator autonomy"]),
                   c: site("Unverified")}),
        req("R-003", "7.3", "Colocation", "Lockable cage with 8 kVA per rack.",
            sites={a: site("Comply", m["Dedicated cage"], m["Power per rack"]),
                   b: site("Partial", m["Power per rack"]), c: site("Unverified")}),
        req("R-004", "7.4", "Facility rating", "Third-party facility rating certificate.",
            clarification="Does the TIA-942 requirement accept a design certification, or only a constructed "
                          "facility certification?",
            sites={a: site("Clarify", m["TIA-942 rating"]), b: site("Gap", m["TIA-942 rating"]),
                   c: site("Unverified")}),
        req("R-005", "7.5", "DR seats", "Twenty DR seats with workstations.",
            sites={a: site("Partial", m["DR seats"]), b: site("Partial", m["DR seats"]), c: site("Unverified")}),
        req("R-006", "7.6", "Office space", "Dedicated office for the client's staff.",
            sites={a: site("Comply", m["Office rental"]), b: site("Gap", m["Office rental"]), c: site("Unverified")}),
        req("R-007", "7.7", "Connectivity", "Two carriers and Dedicated Internet Access.",
            clarification="Must both carriers enter the facility through separate building entrances?",
            sites={a: site("Clarify", m["Carrier neutral"]), b: site("Comply", m["Carrier neutral"]),
                   c: site("Gap", m["Carrier neutral"])}),
        req("R-008", "7.8", "Certifications", "ISO/IEC 27001 certificate for the facility.",
            sites={a: site("Comply", m["ISO/IEC 27001"]), b: site("Comply", m["ISO/IEC 27001"]),
                   c: site("Unverified")}),
        req("R-009", "7.9", "Personnel", "Two certified data center professionals.", scope="Bidder (general)",
            rating="Unverified"),
    ]
    terms = {
        "bid": {"title": "SAMPLE Business Continuity Facility", "procuring_entity": "SAMPLE Agency",
                "reference_no": "SAMPLE-0001", "abc_php": 1000000.0, "bid_deadline": "2026-12-15",
                "delivery_days": 90, "delivery_basis": "calendar days from Notice to Proceed",
                "slcc_window_years": 10, "slcc_rule": "50% of ABC", "similar_definition": "Sample definition.",
                "subcontracting": "Allowed"},
        "flags": [{"flag": "SAMPLE flag: sandbox data, not a real bid.", "reference": "-"}],
    }
    (out / "replay").mkdir(parents=True, exist_ok=True)
    (out / "replay" / "terms.json").write_text(json.dumps(terms, indent=1))
    (out / "replay" / "requirements.json").write_text(json.dumps(reqs, indent=1))


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "sample_fixtures")
    out.mkdir(parents=True, exist_ok=True)
    m = spec_table(out / "SAMPLE_Specifications_Table.xlsx")
    replay(out, m)
    print(f"Sample fixtures written to {out}")


if __name__ == "__main__":
    main()
