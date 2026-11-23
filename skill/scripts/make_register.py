#!/usr/bin/env python3
"""Create a blank VITRO Reference Register workbook.

Usage: make_register.py OUT.xlsx
"""
import sys

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.worksheet.datavalidation import DataValidation

import vitro_style as vs
from register_schema import HEADER_ROW, SHEETS

README = [
    ("What this is", True),
    ("Evidence the VITRO Specifications Table does not hold: contracts (for SLCC), DR seats, site distances, personnel and lead times.", False),
    ("Facility evidence (ratings, certifications, power, cooling, security, connectivity) comes from the Specifications Table, not from here.", False),
    ("A requirement with no matching row is reported as 'Unverified', never as compliant.", False),
    ("", False),
    ("How to fill it", True),
    ("1. One row per item. Keep the ID prefix of the sheet (C-, SEAT-, DIST-, PER-, LT-) and never reuse an ID.", False),
    ("2. Source Document is required. Use the file name or DMS link of the contract, certificate or approved guideline.", False),
    ("3. As-of Date is required. Rows older than 6 months are flagged as stale in the matrix.", False),
    ("4. Quantities and distances need their basis (e.g. seats, dedicated; straight-line km by map tool).", False),
    ("5. Dates as YYYY-MM-DD. Amounts as plain numbers in PHP, VAT inclusive.", False),
    ("6. Personnel: record role, certification and headcount. Avoid names unless a bid requires them.", False),
    ("", False),
    ("Handling", True),
    ("INTERNAL and confidential. Contract values and client names here are not for external use.", False),
    ("Keep it with the Specifications Table (SharePoint) or upload it with each bid package when running /bid-qualify.", False),
]


def build(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "README"
    vs.sheet_base(ws)
    r = vs.title(ws, "VITRO Reference Register", eyebrow="Bid qualification")
    r += 1
    for text, bold in README:
        vs.note(ws, r, text, bold=bold, size=11 if bold else 10)
        r += 1
    r += 1
    vs.note(ws, r, "Sheets", bold=True, size=11)
    r += 1
    for name, (prefix, purpose, _) in SHEETS.items():
        vs.note(ws, r, f"{name} ({prefix}-): {purpose}")
        r += 1
    ws.column_dimensions["A"].width = 120

    for name, (prefix, purpose, cols) in SHEETS.items():
        ws = wb.create_sheet(name)
        vs.sheet_base(ws)
        vs.title(ws, name, eyebrow="Reference register")
        vs.source_line(ws, 3, purpose)
        for i, (col, width, help_text) in enumerate(cols, start=1):
            cell = ws.cell(row=HEADER_ROW, column=i, value=col)
            if help_text:
                cell.comment = Comment(help_text, "bid-qualify")
            ws.column_dimensions[cell.column_letter].width = width
        vs.header_row(ws, HEADER_ROW, len(cols), height=44)
        # 50 pre-formatted blank rows
        for rr in range(HEADER_ROW + 1, HEADER_ROW + 51):
            for i, (col, _, _) in enumerate(cols, start=1):
                numeric = any(k in col for k in ("Amount", "Quantity", "racks", "Headcount", "Lead Time"))
                c = ws.cell(row=rr, column=i)
                vs.body_cell(c, alt=(rr - HEADER_ROW) % 2 == 0, numeric=numeric)
                if "Amount" in col:
                    c.number_format = "#,##0.00"
        ws.freeze_panes = ws.cell(row=HEADER_ROW + 1, column=3)
        ws.cell(row=HEADER_ROW + 1, column=1, value=f"{prefix}-001")
        # dropdowns
        for i, (col, _, _) in enumerate(cols, start=1):
            letter = ws.cell(row=HEADER_ROW, column=i).column_letter
            rng = f"{letter}{HEADER_ROW + 1}:{letter}{HEADER_ROW + 500}"
            if "(Y/N)" in col:
                v = DataValidation(type="list", formula1='"Y,N"', allow_blank=True)
                ws.add_data_validation(v)
                v.add(rng)
            if col == "Status":
                v = DataValidation(
                    type="list", formula1='"Completed,Ongoing,Awarded-not-started"', allow_blank=True
                )
                ws.add_data_validation(v)
                v.add(rng)
    wb.save(path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    build(sys.argv[1])
    print("wrote", sys.argv[1])
