#!/usr/bin/env python3
"""Validate ratings against the register and build the compliance matrix workbook.

Usage:
  build_matrix.py --requirements requirements.json --gates gates.json \
      --specs specs.json [--register REG.xlsx] [--sites "VITRO Clark,VITRO Makati 2"] \
      --out Matrix.xlsx [--validated out.json]

Enforces the evidence rules in references/schema.md:
  - SPEC-<row> evidence must exist in the Specifications Table and the cell for
    that site must hold data; Comply cannot rest on a cell marked Not available.
  - Register evidence (C-, SEAT-, DIST-, PER-, LT-) must exist, have a Source
    Document and not be expired.
VITRO DC requirements are rated per site (field "sites"). Gate 3 is judged per
site, because one site must meet every requirement; the best-fit site is the
one with no gaps and the most Comply ratings. Writes:
  Summary          bid facts, gate results, verdict, site fit, flags, counts
  Site Fit         VITRO DC requirements x sites, evidence in cell comments
  Matrix           every requirement (VITRO DC rows show the recommended site)
  Open Items       VITRO DC and Bidder (general) rows that are not Comply
  Evidence         register rows cited, with source and as-of date
The validated JSON (ratings after enforcement, counts, verdict) feeds the memo.
"""
import argparse
import collections
import datetime as dt
import json

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment
from openpyxl.worksheet.datavalidation import DataValidation

import vitro_style as vs
from check_gates import STALE_DAYS, as_date
from register_schema import EXPIRY_COL, load_register

RATINGS = ["Comply", "Partial", "Gap", "Clarify", "Unverified", "Partner scope", "N/A"]
OWN_SCOPES = ("VITRO DC", "Bidder (general)")
NEGATIVE = ("Not available", "Not applicable")
GATE3_EXCLUDED = ("Eligibility", "Delivery")


def check_evidence(rating, evidence, by_id, specs, deadline, site=None):
    """Return (rating, checks, problems) after applying the evidence rules."""
    checks, problems = [], []
    if rating not in ("Comply", "Partial"):
        return rating, checks, problems
    if not evidence:
        problems.append("no evidence cited")
    for e in evidence:
        e = str(e).strip()
        if e.startswith("SPEC-"):
            row = specs.get(e)
            if row is None:
                problems.append(f"{e} not in Specifications Table")
                continue
            if site is None:
                problems.append(f"{e} cited without a site")
                continue
            cell = row["cells"].get(site)
            if cell is None or cell["status"] == "Blank":
                problems.append(f"{e} blank for {site}")
            elif rating == "Comply" and cell["status"] in NEGATIVE:
                problems.append(f"{e} says '{cell['status']}' for {site}")
            continue
        hit = by_id.get(e)
        if not hit:
            problems.append(f"{e} not in register")
            continue
        sheet, row = hit
        if not row.get("Source Document"):
            problems.append(f"{e} has no Source Document")
        exp_col = EXPIRY_COL.get(sheet)
        exp = as_date(row.get(exp_col)) if exp_col else None
        if exp and deadline and exp < deadline:
            problems.append(f"{e} expired {exp}")
        asof = as_date(row.get("As-of Date"))
        if asof is None or (deadline and (deadline - asof).days > STALE_DAYS):
            checks.append(f"{e} stale (as of {asof or 'unknown'})")
    if problems:
        checks = [f"Downgraded from {rating}: " + "; ".join(problems)] + checks
        rating = "Unverified"
    return rating, checks, problems


def enforce(reqs, by_id, specs, sites, deadline):
    notes = []
    for i, r in enumerate(reqs, start=1):
        r.setdefault("id", f"R-{i:03d}")
        r.setdefault("evidence", [])
        r.setdefault("mandatory", True)
        if not r.get("rating"):
            r["rating"] = "Partner scope" if r.get("scope") == "Partner" else "Unverified"
        if r.get("scope") == "VITRO DC":
            given = r.get("sites") or {}
            r["sites"] = {}
            for site in sites:
                sr = dict(given.get(site) or {"rating": "Unverified", "evidence": [],
                                                "note": "Not rated for this site."})
                sr.setdefault("evidence", [])
                sr["rating"], sr["checks"], probs = check_evidence(
                    sr.get("rating", "Unverified"), sr["evidence"], by_id, specs, deadline, site)
                if probs:
                    notes.append((f"{r['id']} @ {site}", probs))
                r["sites"][site] = sr
            r["checks"] = []
        else:
            r["rating"], r["checks"], probs = check_evidence(r["rating"], r["evidence"], by_id, specs, deadline)
            if probs:
                notes.append((r["id"], probs))
    return notes


def site_fit(reqs, sites):
    """Per-site counts over mandatory VITRO DC requirements; returns ranked list."""
    dc = [r for r in reqs if r.get("scope") == "VITRO DC" and r.get("mandatory", True)
          and r.get("category") not in GATE3_EXCLUDED]
    out = []
    for site in sites:
        c = collections.Counter(r["sites"][site]["rating"] for r in dc)
        if dc and c["Unverified"] > len(dc) / 2:
            fit = "Insufficient data"  # most cells blank: cannot rank on missing evidence
        elif c["Gap"]:
            fit = "Fail"
        elif c["Unverified"] or c["Clarify"] or c["Partial"]:
            fit = "Needs review"
        elif dc:
            fit = "Pass"
        else:
            fit = "Unverified"
        gaps = [r["id"] + " " + (r.get("clause") or "") for r in dc if r["sites"][site]["rating"] == "Gap"]
        out.append({"site": site, "fit": fit, "counts": dict(c), "gaps": gaps, "n": len(dc)})
    out.sort(key=lambda x: (x["fit"] == "Insufficient data", x["counts"].get("Gap", 0),
                            -x["counts"].get("Comply", 0), -x["counts"].get("Partial", 0)))
    return out


def gate3(reqs, fits, recommended):
    """Gate 3 = recommended (or best) site's fit, combined with Bidder (general) rows."""
    best = next((f for f in fits if f["site"] == recommended), fits[0] if fits else None)
    gen = [r for r in reqs if r.get("scope") == "Bidder (general)" and r.get("mandatory", True)
           and r.get("category") not in GATE3_EXCLUDED]
    gc = collections.Counter(r["rating"] for r in gen)
    gen_res = "Fail" if gc["Gap"] else ("Needs review" if (gc["Unverified"] or gc["Clarify"] or gc["Partial"])
                                         else ("Pass" if gen else "Unverified"))
    order = ["Fail", "Unverified", "Needs review", "Pass"]
    site_res = best["fit"] if best else "Unverified"
    if site_res == "Insufficient data":
        site_res = "Unverified"
    res = min([site_res, gen_res], key=order.index)
    return res, best, dict(gc), len(gen)


def req_label(q):
    """Requirement text, with a pointer to any bulletin that amends or clarifies it."""
    t = q.get("text") or ""
    if q.get("amended_by"):
        t += f" [See {q['amended_by']}]"
    return t


def verdict(results):
    if "Fail" in results:
        return "No-Go"
    if "Unverified" in results:
        return "Insufficient evidence"
    if all(r == "Pass" for r in results):
        return "Go"
    return "Conditional Go"


def write_table(ws, row, headers, rows, widths=None, status_cols=(), numeric_cols=()):
    for j, h in enumerate(headers, start=1):
        ws.cell(row=row, column=j, value=h)
    vs.header_row(ws, row, len(headers))
    for i, data in enumerate(rows):
        rr = row + 1 + i
        for j, v in enumerate(data, start=1):
            c = ws.cell(row=rr, column=j, value=v)
            vs.body_cell(c, alt=i % 2 == 1, numeric=(j - 1) in numeric_cols)
            if (j - 1) in status_cols and v:
                vs.status_cell(c, v)
    if widths:
        for j, w in enumerate(widths, start=1):
            ws.column_dimensions[ws.cell(row=row, column=j).column_letter].width = w
    return row + 1 + len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--requirements", required=True)
    ap.add_argument("--gates", required=True)
    ap.add_argument("--register")
    ap.add_argument("--specs", required=True, help="specs.json from read_specs.py")
    ap.add_argument("--sites", help="comma-separated subset of sites to assess (default: all)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--validated")
    a = ap.parse_args()

    data = json.load(open(a.requirements))
    gates = json.load(open(a.gates))
    bid, reqs = data.get("bid", {}), data["requirements"]
    assess = data.get("assessment", {})
    by_id = load_register(a.register)[1] if a.register else {}
    spec_data = json.load(open(a.specs))
    specs = {r["id"]: r for r in spec_data["rows"]}
    site_info = {x["name"]: x for x in spec_data["sites"]}
    sites = [x.strip() for x in a.sites.split(",")] if a.sites else list(site_info)
    unknown = [x for x in sites if x not in site_info]
    if unknown:
        raise SystemExit(f"Unknown site(s): {unknown}. Sites in the table: {list(site_info)}")
    deadline = as_date(bid.get("bid_deadline"))
    downgrades = enforce(reqs, by_id, specs, sites, deadline)

    fits = site_fit(reqs, sites)
    rec = assess.get("recommended_site") or (fits[0]["site"] if fits else None)
    for q in reqs:  # VITRO DC rows carry the recommended site's rating into the main matrix
        if q.get("scope") == "VITRO DC" and rec:
            sr = q["sites"][rec]
            q["rating"], q["checks"] = sr["rating"], sr.get("checks", [])
            q["evidence"] = [f"{e} @ {rec}" if str(e).startswith("SPEC-") else e for e in sr["evidence"]]
            q["rationale"] = f"[{rec}] {sr.get('note', '')}"

    g1 = assess.get("gate1", {}).get("result") or gates["gate1_slcc"]["result"]
    g2 = assess.get("gate2", {}).get("result") or gates["gate2_delivery"]["result"]
    g3, best, gen_counts, gen_n = gate3(reqs, fits, rec)
    g3 = assess.get("gate3", {}).get("result") or g3
    overall = assess.get("verdict") or verdict([g1, g2, g3])

    wb = Workbook()
    # ---------------- Summary
    ws = wb.active
    ws.title = "Summary"
    vs.sheet_base(ws)
    r = vs.title(ws, f"{bid.get('procuring_entity', '')}: {bid.get('title', '')}", eyebrow="Bid qualification")
    vs.source_line(ws, r, "INTERNAL. Draft for Solutions review. Every rating needs reviewer sign-off before use.")
    r += 2
    vc = vs.note(ws, r, "Recommendation", bold=True, size=11)
    c = ws.cell(row=r, column=2, value=overall)
    vs.body_cell(c)
    vs.status_cell(c, overall)
    r += 2
    facts = [
        ("Reference No.", bid.get("reference_no")),
        ("Procuring Entity", bid.get("procuring_entity")),
        ("Approved Budget for the Contract (PHP)", bid.get("abc_php")),
        ("Bid Deadline", bid.get("bid_deadline")),
        ("Delivery Period", f"{bid.get('delivery_days')} {bid.get('delivery_basis', '')}".strip()),
        ("SLCC Window (years)", bid.get("slcc_window_years")),
        ("SLCC Rule", bid.get("slcc_rule")),
        ("Similar Contract (BDS)", bid.get("similar_definition")),
    ]
    start = r
    r = write_table(ws, r, ["Item", "Value"], [[k, v] for k, v in facts], widths=[38, 64, 16, 40])
    abc_cell = ws.cell(row=start + 3, column=2)
    abc_cell.number_format = "#,##0.00"
    abc_cell.alignment = Alignment(horizontal="left", vertical="top")
    for i, (_, v) in enumerate(facts):
        ws.row_dimensions[start + 1 + i].height = 15 * max(1, -(-len(str(v or "")) // 58))
    vs.source_line(ws, r, "Source: bidding documents and bulletins listed on the Evidence sheet.")
    r += 2

    G = gates
    g1d = G["gate1_slcc"]
    g2d = G["gate2_delivery"]
    gate_rows = [
        ["1. Eligibility (SLCC)", g1,
         assess.get("gate1", {}).get("basis")
         or f"50% of ABC = PHP {g1d['threshold_rule_a_php']:,.2f}. " + " ".join(g1d["notes"]),
         assess.get("gate1", {}).get("reference", "ITB 5.3; BDS 5.4, 5.5")],
        ["2. Delivery lead time", g2,
         assess.get("gate2", {}).get("basis")
         or f"Required {g2d['required_days']} days; VITRO {g2d['vitro_days']}. " + " ".join(g2d["notes"]),
         assess.get("gate2", {}).get("reference", "Section VI")],
        ["3. Data center compliance", g3,
         assess.get("gate3", {}).get("basis")
         or (f"Recommended site {rec}: {best['n']} VITRO DC requirements, "
             + ", ".join(f"{k} {v}" for k, v in sorted(best["counts"].items()))
             + f". {gen_n} Bidder (general): "
             + ", ".join(f"{k} {v}" for k, v in sorted(gen_counts.items())) + "."),
         assess.get("gate3", {}).get("reference", "Section VII; Annex A")],
    ]
    vs.note(ws, r, "Gate results", bold=True, size=11)
    gate_rows = [[g, basis, res, ref] for g, res, basis, ref in gate_rows]  # Basis in the wide column
    r = write_table(ws, r + 1, ["Gate", "Basis", "Result", "Reference"], gate_rows, status_cols=(2,))
    for i, row in enumerate(gate_rows):
        ws.row_dimensions[r - 3 + i].height = 15 * max(2, -(-len(row[1]) // 58))
    vs.source_line(ws, r, "Source: check_gates.py on the VITRO Reference Register; Matrix sheet.")
    r += 2

    vs.note(ws, r, "Site fit (VITRO DC requirements, per site)", bold=True, size=11)
    fit_rows = []
    for f in fits:
        c = f["counts"]
        counts = (f"Comply {c.get('Comply', 0)} | Partial {c.get('Partial', 0)} | Clarify {c.get('Clarify', 0)} | "
                  f"Unverified {c.get('Unverified', 0)} | Gap {c.get('Gap', 0)}")
        fit_rows.append([f["site"] + (" (recommended)" if f["site"] == rec else ""), counts, f["fit"],
                         ", ".join(g.split(" ", 1)[1] for g in f["gaps"])])
    r = write_table(ws, r + 1, ["Site", "Ratings across VITRO DC requirements", "Fit", "Gap clauses"],
                    fit_rows, status_cols=(2,))
    vs.source_line(ws, r, f"Source: {spec_data['source']['file']} (sheet '{spec_data['source']['sheet']}'); "
                          "Site Fit sheet. Ranked by gaps, then Comply count.")
    r += 2

    flags = assess.get("flags", [])
    if flags:
        vs.note(ws, r, "Flags for the bid/no-bid decision", bold=True, size=11)
        r = write_table(ws, r + 1, ["Reference", "Flag"], [[f.get("reference", ""), f["flag"]] for f in flags])
        for i, f in enumerate(flags):
            ws.row_dimensions[r - len(flags) + i].height = 15 * max(1, -(-len(f["flag"]) // 58))
        r += 1

    vs.note(ws, r, "Ratings by scope", bold=True, size=11)
    scopes = ["VITRO DC", "Bidder (general)", "Partner"]
    cnt = collections.Counter((q.get("scope"), q["rating"]) for q in reqs)
    rows = [[rt] + [cnt[(s, rt)] for s in scopes] + [sum(cnt[(s, rt)] for s in scopes)] for rt in RATINGS]
    rows.append(["Total"] + [sum(cnt[(s, rt)] for rt in RATINGS) for s in scopes] + [len(reqs)])
    hdr = ["Rating"] + scopes + ["Total"]
    start = r + 1
    r = write_table(ws, start, hdr, rows, status_cols=(0,), numeric_cols=(1, 2, 3, 4))
    for j in range(1, 6):
        vs.body_cell(ws.cell(row=r - 1, column=j), alt=len(rows) % 2 == 0, numeric=j > 1, bold=True)
    vs.source_line(ws, r, "Source: Matrix sheet. Counts after evidence validation.")

    # ---------------- Site Fit
    ws = wb.create_sheet("Site Fit")
    vs.sheet_base(ws)
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.print_title_rows = "4:4"
    vs.title(ws, "Site fit", eyebrow="Bid qualification")
    vs.source_line(ws, 3, f"VITRO DC requirements rated per site against {spec_data['source']['file']}. "
                          "Hover a rating for its evidence and note. Gate 3 needs one site to meet every row.")
    ordered = [f["site"] for f in fits]
    hdr = ["ID", "Clause", "Category", "Requirement"] + ordered
    dc_rows = [q for q in reqs if q.get("scope") == "VITRO DC"]
    grid = [[q["id"], q.get("clause"), q.get("category"), req_label(q)]
            + [q["sites"][st]["rating"] for st in ordered] for q in dc_rows]
    write_table(ws, 4, hdr, grid, widths=[8, 11, 14, 56] + [13] * len(ordered), status_cols=range(4, 4 + len(ordered)))
    for i, q in enumerate(dc_rows):
        for j, st in enumerate(ordered):
            sr = q["sites"][st]
            text = "; ".join(sr.get("evidence", [])) or "No evidence"
            text += "\n" + (sr.get("note") or "")
            if sr.get("checks"):
                text += "\n" + "; ".join(sr["checks"])
            c = ws.cell(row=5 + i, column=5 + j)
            c.comment = Comment(text[:900], "bid-qualify", width=320, height=140)
        ws.row_dimensions[5 + i].height = 15 * max(1, -(-len(grid[i][3] or "") // 60))
    for j in range(len(ordered)):
        ws.cell(row=4, column=5 + j).alignment = Alignment(wrap_text=True, vertical="center")
    ws.freeze_panes = "E5"
    ws.auto_filter.ref = f"A4:{ws.cell(row=4, column=len(hdr)).column_letter}{4 + max(1, len(dc_rows))}"

    # ---------------- Matrix
    ws = wb.create_sheet("Matrix")
    vs.sheet_base(ws)
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.print_title_rows = "4:4"
    vs.title(ws, "Compliance matrix", eyebrow="Bid qualification")
    vs.source_line(ws, 3, f"Ratings are drafts. VITRO DC rows show the recommended site ({rec}); see Site Fit for all sites. "
                          "Comply requires cited evidence. Reviewer signs off each row.")
    cols = [("ID", 8), ("Doc", 11), ("Page", 6), ("Clause", 10), ("Section", 22), ("Requirement", 60),
            ("Category", 15), ("Scope", 15), ("Mandatory", 10), ("Bulletin", 18), ("As Amended / Clarified", 44),
            ("Rating", 13), ("Evidence", 14), ("Rationale", 44), ("Checks", 30), ("Clarification Question", 40),
            ("Reviewer", 14), ("Sign-off (Y/N)", 10), ("Reviewer Notes", 30)]
    hr = 4
    for j, (h, w) in enumerate(cols, start=1):
        ws.cell(row=hr, column=j, value=h)
        ws.column_dimensions[ws.cell(row=hr, column=j).column_letter].width = w
    vs.header_row(ws, hr, len(cols))
    for i, q in enumerate(reqs):
        vals = [q["id"], q.get("doc"), q.get("page"), q.get("clause"), q.get("section"), q.get("text"),
                q.get("category"), q.get("scope"), "Y" if q.get("mandatory", True) else "N",
                q.get("amended_by"), q.get("amended_text"), q["rating"], ", ".join(q.get("evidence", [])),
                q.get("rationale"), "; ".join(q.get("checks", [])), q.get("clarification"), "", "", ""]
        for j, v in enumerate(vals, start=1):
            c = ws.cell(row=hr + 1 + i, column=j, value=v)
            vs.body_cell(c, alt=i % 2 == 1, numeric=j == 3)
            if j == 12:
                vs.status_cell(c, v)
    last = hr + len(reqs)
    ws.auto_filter.ref = f"A{hr}:{ws.cell(row=hr, column=len(cols)).column_letter}{max(last, hr + 1)}"
    ws.freeze_panes = ws.cell(row=hr + 1, column=7)
    dv = DataValidation(type="list", formula1='"' + ",".join(RATINGS) + '"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"L{hr + 1}:L{last + 200}")
    dv2 = DataValidation(type="list", formula1='"Y,N"', allow_blank=True)
    ws.add_data_validation(dv2)
    dv2.add(f"R{hr + 1}:R{last + 200}")

    # ---------------- Open items
    ws = wb.create_sheet("Open Items")
    vs.sheet_base(ws)
    vs.title(ws, "Open items", eyebrow="Bid qualification")
    vs.source_line(ws, 3, "VITRO DC and Bidder (general) requirements not yet rated Comply. Gaps first.")
    order = {"Gap": 0, "Clarify": 1, "Partial": 2, "Unverified": 3}
    items = sorted([q for q in reqs if q.get("scope") in OWN_SCOPES and q["rating"] in order],
                   key=lambda q: (order[q["rating"]], q.get("category") or "", q["id"]))
    write_table(ws, 4, ["ID", "Clause", "Category", "Requirement", "Rating", "What is needed"],
                [[q["id"], q.get("clause"), q.get("category"), req_label(q), q["rating"],
                  q.get("clarification") or q.get("rationale")] for q in items],
                widths=[8, 10, 16, 70, 13, 60], status_cols=(4,))
    ws.freeze_panes = "A5"

    # ---------------- Evidence
    ws = wb.create_sheet("Evidence")
    vs.sheet_base(ws)
    vs.title(ws, "Evidence and sources", eyebrow="Bid qualification")
    cited = sorted({str(e).split(" @ ")[0] for q in reqs for e in q.get("evidence", [])}
                   | {e for q in reqs for sr in (q.get("sites") or {}).values() for e in sr.get("evidence", [])})
    erows = []
    for e in cited:
        if e.startswith("SPEC-"):
            row = specs.get(e)
            erows.append([e, "Specifications Table", (row["group"] + " / " if row and row["group"] else "")
                          + (row["item"] if row else "NOT FOUND"), spec_data["source"]["file"],
                          spec_data["source"].get("file_date_in_name") or spec_data["source"].get("file_modified")])
            continue
        hit = by_id.get(e)
        if hit:
            sheet, row = hit
            label = row.get("Contract Title") or row.get("Standard") or row.get("Site Name") or row.get("Service") \
                or row.get("Certification") or row.get("Type") or row.get("Category")
            erows.append([e, sheet, label, row.get("Source Document"), str(as_date(row.get("As-of Date")) or "")])
        else:
            erows.append([e, "NOT FOUND", "", "", ""])
    r = write_table(ws, 4, ["ID", "Evidence Source", "Item", "Source Document", "As-of Date"],
                    erows or [["(none cited)", "", "", "", ""]], widths=[12, 18, 44, 50, 14])
    r += 1
    vs.note(ws, r, "Documents reviewed", bold=True, size=11)
    write_table(ws, r + 1, ["Document"], [[d] for d in bid.get("documents", [])])
    vs.source_line(ws, 3, f"Specifications Table: {spec_data['source']['file']} (read {spec_data['source']['read_on']}). "
                          f"Register: {a.register or 'none supplied'}")

    wb.save(a.out)

    summary = {
        "verdict": overall,
        "gates": {"gate1": g1, "gate2": g2, "gate3": g3},
        "recommended_site": rec,
        "site_fit": fits,
        "bidder_general_counts": gen_counts,
        "rating_counts_by_scope": {f"{s}|{rt}": n for (s, rt), n in cnt.items()},
        "downgraded": [{"id": i, "problems": p} for i, p in downgrades],
        "open_items": [q["id"] for q in items],
    }
    if a.validated:
        data["validation"] = summary
        json.dump(data, open(a.validated, "w"), indent=1, default=str)
    print(json.dumps(summary, indent=1))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
