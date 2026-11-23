#!/usr/bin/env python3
"""Compute the numeric parts of Gate 1 (SLCC) and Gate 2 (delivery) from the register.

Usage:
  check_gates.py --register REG.xlsx --abc 525525000 --deadline 2026-11-23 \
      --slcc-years 10 --delivery-days 270 [--lead-times LT-001,LT-004] \
      [--exclude-recurring] --out gates.json

Gate 1 (SLCC), per ITB Clause 5.3 of the Philippine Bidding Documents:
  Rule A: one completed similar contract >= 50% of ABC, or
  Rule B: one completed similar contract >= 25% of ABC AND other completed
          contracts (similar or not) aggregating >= 25% of ABC.
  Contract must be Completed, with Completion Date within --slcc-years of the
  deadline. The amount used is the CPI-Adjusted Amount when given, else the
  nominal amount (flagged, since the rules call for CPI adjustment).
  --exclude-recurring drops contracts flagged Recurring Component = Y (some
  bulletins rule that only fully completed contracts count).
  The script cannot judge similarity: it lists candidates by amount and date.
  Claude judges each candidate's scope against the BDS 'similar contract'
  definition and writes the verdict.

Gate 2 (delivery): compares required days with the longest selected
standard lead time (the selected items are assumed to run in parallel; the
reviewer adjusts if they run in sequence).
"""
import argparse
import datetime as dt
import json
import sys

from register_schema import load_register

STALE_DAYS = 180


def as_date(v):
    if v is None or v == "":
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v).strip()[:10])
    except ValueError:
        return None


def as_num(v):
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").replace("PHP", "").strip())
    except ValueError:
        return None


def gate1(rows, abc, deadline, years, exclude_recurring):
    contracts = rows.get("Contracts", [])
    out = {
        "abc_php": abc,
        "threshold_rule_a_php": round(abc * 0.50, 2),
        "threshold_rule_b_single_php": round(abc * 0.25, 2),
        "threshold_rule_b_aggregate_php": round(abc * 0.25, 2),
        "window_start": None,
        "register_contracts": len(contracts),
        "eligible_contracts": [],
        "excluded": [],
        "rule_a_candidates": [],
        "rule_b_candidates": [],
        "result": None,
        "notes": [],
    }
    if deadline:
        try:
            start = deadline.replace(year=deadline.year - years)
        except ValueError:  # 29 Feb
            start = deadline.replace(year=deadline.year - years, day=28)
        out["window_start"] = start.isoformat()
    else:
        start = None
        out["notes"].append("No deadline given: completion window not checked.")

    elig = []
    for c in contracts:
        cid = str(c.get("ID"))
        why = []
        if str(c.get("Status", "")).strip().lower() != "completed":
            why.append(f"status '{c.get('Status')}'")
        comp = as_date(c.get("Completion Date"))
        if comp is None:
            why.append("no completion date")
        elif start and comp < start:
            why.append(f"completed {comp} before window start {start}")
        elif deadline and comp > deadline:
            why.append(f"completion {comp} after deadline")
        if exclude_recurring and str(c.get("Recurring Component (Y/N)", "")).upper().startswith("Y"):
            why.append("has recurring component (excluded for this bid)")
        if not c.get("Source Document"):
            why.append("no Source Document")
        adj = as_num(c.get("CPI-Adjusted Amount (PHP)"))
        nom = as_num(c.get("Contract Amount (PHP, VAT inc.)"))
        amt = adj if adj is not None else nom
        if amt is None:
            why.append("no amount")
        if why:
            out["excluded"].append({"id": cid, "reasons": why})
            continue
        elig.append(
            {
                "id": cid,
                "client": c.get("Client / Procuring Entity"),
                "title": c.get("Contract Title"),
                "scope": c.get("Scope Description"),
                "tags": c.get("Scope Tags"),
                "completion": comp.isoformat(),
                "amount_used_php": amt,
                "amount_basis": "CPI-adjusted" if adj is not None else "nominal (not CPI-adjusted)",
                "pct_of_abc": round(100 * amt / abc, 1),
                "source": c.get("Source Document"),
            }
        )
    elig.sort(key=lambda x: -x["amount_used_php"])
    out["eligible_contracts"] = elig
    out["rule_a_candidates"] = [e["id"] for e in elig if e["amount_used_php"] >= abc * 0.50]
    for e in elig:
        if e["amount_used_php"] >= abc * 0.25:
            others = sum(o["amount_used_php"] for o in elig if o["id"] != e["id"])
            if others >= abc * 0.25:
                out["rule_b_candidates"].append({"single": e["id"], "others_aggregate_php": others})
    if not contracts:
        out["result"] = "Unverified"
        out["notes"].append("Contracts register is empty. SLCC cannot be checked.")
    elif out["rule_a_candidates"] or out["rule_b_candidates"]:
        out["result"] = "Needs review"
        out["notes"].append(
            "Candidates meet the amount and date tests. Confirm each is 'similar' per the BDS definition."
        )
    else:
        out["result"] = "Fail"
        out["notes"].append("No completed contract in the register meets the amount and date tests.")
    if any(e["amount_basis"].startswith("nominal") for e in elig):
        out["notes"].append("Some amounts are nominal. The bid rules adjust SLCC value to current prices (PSA CPI).")
    return out


def gate2(rows, required_days, lt_ids):
    lts = {str(r.get("ID")): r for r in rows.get("Lead Times", [])}
    out = {
        "required_days": required_days,
        "selected": [],
        "missing_ids": [],
        "vitro_days": None,
        "margin_days": None,
        "result": None,
        "notes": [],
    }
    for i in lt_ids:
        r = lts.get(i)
        if not r:
            out["missing_ids"].append(i)
            continue
        days = as_num(r.get("Standard Lead Time (calendar days)"))
        out["selected"].append(
            {
                "id": i,
                "category": r.get("Category"),
                "days": days,
                "condition": r.get("Condition"),
                "source": r.get("Source Document"),
            }
        )
    days = [s["days"] for s in out["selected"] if s["days"] is not None and s["source"]]
    if required_days is None:
        out["result"] = "Unverified"
        out["notes"].append("Required delivery period not given.")
    elif not days:
        out["result"] = "Unverified"
        out["notes"].append(
            "No sourced lead times selected from the register. Feasibility needs the delivery team's estimate."
        )
    else:
        v = max(days)
        out["vitro_days"] = v
        out["margin_days"] = required_days - v
        out["result"] = "Pass" if v <= required_days else "Fail"
        out["notes"].append("Assumes selected items run in parallel; reviewer to adjust for sequencing.")
    return out


def stale_rows(rows, today):
    out = []
    for sheet, rs in rows.items():
        for r in rs:
            d = as_date(r.get("As-of Date"))
            if d is None or (today - d).days > STALE_DAYS:
                out.append({"id": str(r.get("ID")), "sheet": sheet, "as_of": d.isoformat() if d else None})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--register", required=True)
    ap.add_argument("--abc", type=float, required=True)
    ap.add_argument("--deadline", help="YYYY-MM-DD bid submission deadline")
    ap.add_argument("--slcc-years", type=int, default=5)
    ap.add_argument("--delivery-days", type=int)
    ap.add_argument("--lead-times", default="", help="comma-separated LT- IDs that apply to this bid")
    ap.add_argument("--exclude-recurring", action="store_true")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    rows, _ = load_register(a.register)
    deadline = as_date(a.deadline)
    res = {
        "register": a.register,
        "register_row_counts": {k: len(v) for k, v in rows.items()},
        "gate1_slcc": gate1(rows, a.abc, deadline, a.slcc_years, a.exclude_recurring),
        "gate2_delivery": gate2(
            rows, a.delivery_days, [x.strip() for x in a.lead_times.split(",") if x.strip()]
        ),
        "stale_register_rows": stale_rows(rows, deadline or dt.date.today()),
    }
    with open(a.out, "w") as fh:
        json.dump(res, fh, indent=1, default=str)
    g1, g2 = res["gate1_slcc"], res["gate2_delivery"]
    print(f"Register rows: {res['register_row_counts']}")
    print(f"Gate 1 SLCC: {g1['result']}  (50% = PHP {g1['threshold_rule_a_php']:,.2f}; "
          f"rule A candidates {g1['rule_a_candidates']}; rule B {[c['single'] for c in g1['rule_b_candidates']]})")
    for n in g1["notes"]:
        print("   -", n)
    print(f"Gate 2 delivery: {g2['result']}  (required {g2['required_days']}, VITRO {g2['vitro_days']})")
    for n in g2["notes"]:
        print("   -", n)
    print("wrote", a.out)


if __name__ == "__main__":
    sys.exit(main())
