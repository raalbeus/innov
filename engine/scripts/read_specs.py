#!/usr/bin/env python3
"""Read the VITRO Specifications Table into structured evidence.

Usage: read_specs.py SPEC.xlsx OUT_DIR [--sheet "VITRO DC Specs"]

Writes:
  OUT_DIR/specs.json  {"source": {...}, "sites": [...], "rows": [...]}
  OUT_DIR/specs.md    one line per spec row and site, for Claude to read

Each spec row gets the ID SPEC-<Excel row number>, e.g. SPEC-187. Cite it as
evidence together with the site, e.g. SPEC-187 @ VITRO Clark.

Symbol legend (confirmed by the Solutions team, 23 Nov 2026):
  n or ●   Available      q or ○   Not available
  i        Optional / on request      -   Not applicable
A symbol can be followed by detail on the next line, e.g. "n\n(99.99% SLA)".
"""
import argparse
import datetime as dt
import json
import os
import re

from openpyxl import load_workbook

SYMBOL = {"n": "Available", "●": "Available", "q": "Not available", "○": "Not available",
          "i": "Optional", "-": "Not applicable"}
NEGATIVE = {"Not available", "Not applicable"}
HEADER_ROWS = {"Data Center name": "name", "Address": "address", "City": "city",
               "Data Center ownership type": "ownership"}
FIRST_SITE_COL = 8  # column H


def clean(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).replace("　", " ").strip()
    return "" if s.startswith("=") else s  # drop numbering formulas


def decode(raw):
    """Return (status, detail) for a site cell."""
    s = clean(raw)
    if not s:
        return "Blank", ""
    first, _, rest = s.partition("\n")
    first = first.strip()
    if first in SYMBOL:
        return SYMBOL[first], rest.strip().strip("()").strip()
    return "Value", s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("out")
    ap.add_argument("--sheet")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    wb = load_workbook(a.spec, data_only=True)
    ws = wb[a.sheet] if a.sheet else wb.worksheets[0]

    # vertical merges in A (sub-group) and C (item) carry their value down
    carry = {}
    for rng in ws.merged_cells.ranges:
        if rng.min_col in (1, 3, 4, 5) and rng.max_col == rng.min_col:
            v = ws.cell(rng.min_row, rng.min_col).value
            for r in range(rng.min_row, rng.max_row + 1):
                carry[(r, rng.min_col)] = v

    def cell(r, c):
        return clean(carry.get((r, c), ws.cell(r, c).value))

    # sites
    last_col = ws.max_column
    sites = []
    for c in range(FIRST_SITE_COL, last_col + 1):
        name = clean(ws.cell(1, c).value)
        if name:
            sites.append({"col": c, "name": name})
    for r in range(1, 6):
        key = HEADER_ROWS.get(clean(ws.cell(r, 1).value))
        if key and key != "name":
            for s in sites:
                s[key] = clean(ws.cell(r, s["col"]).value)

    rows, section, group, item_parent = [], "", "", ""
    for r in range(2, ws.max_row + 1):
        a_val = cell(r, 1)
        label_c, desc, base, example = cell(r, 3), cell(r, 4), cell(r, 5), clean(ws.cell(r, 6).value)
        vals = {s["name"]: ws.cell(r, s["col"]).value for s in sites}
        has_vals = any(clean(v) for v in vals.values())
        hdr = clean(ws.cell(r, 1).value)
        if hdr in HEADER_ROWS:
            if HEADER_ROWS[hdr] != "name":  # address, city, ownership are citable facts too
                rows.append({"id": f"SPEC-{r}", "row": r, "section": "Site details", "group": "",
                             "item": hdr, "description": "", "baseline": "",
                             "cells": {s["name"]: {"status": "Value" if clean(vals[s["name"]]) else "Blank",
                                                   "detail": clean(vals[s["name"]])} for s in sites}})
            continue
        # section header: text in A, nothing in C and no site values
        if a_val and not label_c and not has_vals and not example:
            section, group = a_val, ""
            continue
        if a_val:
            group = a_val
        if label_c:
            item_parent = label_c
        if not has_vals:
            continue
        # ISP-style rows: item name sits in the example column F
        if example and not example.startswith("<e.g.>") and not clean(ws.cell(r, 4).value):
            item = f"{item_parent}: {example}"
        else:
            item = label_c or desc or item_parent
        cells = {}
        for s in sites:
            status, detail = decode(vals[s["name"]])
            cells[s["name"]] = {"status": status, "detail": detail}
        rows.append({
            "id": f"SPEC-{r}",
            "row": r,
            "section": section,
            "group": group,
            "item": item,
            "description": desc if desc != item else "",
            "baseline": base,
            "cells": cells,
        })

    mtime = dt.datetime.fromtimestamp(os.path.getmtime(a.spec)).date().isoformat()
    m = re.search(r"(\d{8})", os.path.basename(a.spec))
    source = {"file": os.path.basename(a.spec), "sheet": ws.title, "file_date_in_name": m.group(1) if m else None,
              "read_on": dt.date.today().isoformat(), "file_modified": mtime,
              "legend": "n/● Available; q/○ Not available; i Optional; - Not applicable"}
    out = {"source": source, "sites": [{k: v for k, v in s.items() if k != "col"} for s in sites], "rows": rows}
    with open(os.path.join(a.out, "specs.json"), "w") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)

    lines = [f"# VITRO Specifications Table: {source['file']} (sheet '{ws.title}')",
             f"Legend: {source['legend']}. Blank = no data for that site (treat as unverified, never as available).",
             "", "## Sites"]
    for s in out["sites"]:
        lines.append(f"- {s['name']}: {s.get('city', '')}; {s.get('address', '')}; {s.get('ownership', '')}".rstrip("; "))
    cur = None
    for row in rows:
        if row["section"] != cur:
            cur = row["section"]
            lines += ["", f"## {cur or 'General'}"]
        head = f"**{row['id']}** {row['group'] + ' / ' if row['group'] and row['group'] != row['item'] else ''}{row['item']}"
        if row["baseline"] and row["baseline"] not in ("-", ""):
            head += f"  _(baseline: {row['baseline'][:90]})_"
        lines.append(head)
        parts = []
        for name, c in row["cells"].items():
            if c["status"] == "Blank":
                continue
            v = c["detail"] if c["status"] == "Value" else c["status"] + (f" ({c['detail']})" if c["detail"] else "")
            parts.append(f"{name}: {v.replace(chr(10), '; ')}")
        lines.append("  " + " | ".join(parts))
    with open(os.path.join(a.out, "specs.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"{len(out['sites'])} sites, {len(rows)} spec rows -> {a.out}/specs.json, specs.md")


if __name__ == "__main__":
    main()
