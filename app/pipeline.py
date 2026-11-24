"""The bid qualification job: same steps as the bid-qualify skill.

 1 reference files    Specifications Table confirmed by the user + latest Reference Register
 2 extract            per-page text, images of scanned pages (extract_bid.py)
 3 specifications     SPEC-<row> evidence per site (read_specs.py)
 4 bid terms          Claude: ABC, deadline, SLCC, delivery, subcontracting, flags
 5 requirements       Claude: every requirement in the TOR / annexes, page by page
 6 bulletins          Claude: every bulletin item; applied to requirements by clause
 7 site ratings       Claude: every VITRO DC requirement x every site, citing SPEC rows
 8 gates and matrix   check_gates.py, build_matrix.py (evidence checks, site ranking, verdict)
 9 memo               memo built from the validated results, build_memo.py
"""
import collections
import datetime as dt
import json
import logging
import re
import shutil
import subprocess
import sys
import traceback

from openpyxl import load_workbook

from . import ai, config, db, refsource, specstore

log = logging.getLogger("bidapp.pipeline")
PAGES_PER_CALL = 8
RATE_BATCH = 15


class JobError(RuntimeError):
    pass


def run_script(name, *args):
    r = subprocess.run([sys.executable, str(config.SCRIPTS_DIR / name), *map(str, args)],
                       cwd=config.SCRIPTS_DIR, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        raise JobError(f"{name} failed: {(r.stderr or r.stdout)[-1500:]}")
    return r.stdout


# ------------------------------------------------------------------ helpers
def page_list(work, doc, pages):
    out = []
    for p in pages:
        png = work / doc["doc"] / "img" / f"p{p:03d}.png"
        txt = work / doc["doc"] / "text" / f"p{p:03d}.txt"
        label = f"{doc['file']} page {p}"
        if p in doc["scanned_pages"] and png.exists():
            out.append((label, None, png))
        else:
            out.append((label, txt.read_text(errors="replace") if txt.exists() else "", None))
    return out


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def short_doc(name):
    stem = re.sub(r"\.pdf$", "", name, flags=re.I)
    m = re.search(r"Annex[ _]*([A-Z])", stem, re.I)
    if m:
        return f"Annex {m.group(1).upper()}"
    return re.sub(r"^[\d_]+", "", stem).replace("_", " ").strip()[:40] or stem[:40]


def register_digest(path):
    if not path:
        return ""
    wb = load_workbook(path, data_only=True)
    lines = []
    for ws in wb.worksheets:
        if ws.title == "README":
            continue
        headers = [c.value for c in ws[4]]
        rows = []
        for r in ws.iter_rows(min_row=5, values_only=True):
            d = {h: v for h, v in zip(headers, r) if h and v not in (None, "")}
            if len(d) > 1:
                rows.append("; ".join(f"{k}: {v}" for k, v in d.items()))
        lines.append(f"## {ws.title}: " + ("(no rows)" if not rows else ""))
        lines += [f"- {x}" for x in rows]
    return "\n".join(lines)


def apply_bulletins(rows, items):
    """Attach bulletin items to requirement rows by exact clause; parent clauses only when specific."""
    clauses = {r["clause"].split(" ")[0] for r in rows}
    hits = collections.defaultdict(list)
    for b in items:
        if b["effect"] not in ("Amends requirement", "Clarifies requirement"):
            continue
        for c in b.get("clauses", []):
            c = c.strip()
            if c.upper().startswith(("BDS", "ITB")):
                hits["__eligibility__"].append(b)
                continue
            if c.count(".") < 1:
                continue
            if c in clauses:
                hits[c].append(b)
            else:
                kids = [x for x in clauses if x.startswith(c + ".")]
                if c.count(".") >= 2 and len(kids) <= 6:
                    for k in kids:
                        hits[k].append(b)
    n = 0
    for r in rows:
        key = "__eligibility__" if r.get("category") == "Eligibility" else r["clause"].split(" ")[0]
        bs = list({b["item"]: b for b in hits.get(key, [])}.values())
        if bs:
            n += 1
            r["amended_by"] = "Bulletin item " + ", ".join(b["item"] for b in bs)
            r["amended_text"] = " | ".join(f"[{b['item']}] {b['resolution']}" for b in bs)
    return n


def merge_requirements(rows):
    out, seen = [], {}
    for r in rows:
        key = (r["doc"], r["clause"], r["scope"])
        if key in seen and r["text"] not in seen[key]["text"]:
            seen[key]["text"] += f" (cont. p{r['page']}) {r['text']}"
            continue
        if key in seen:
            continue
        seen[key] = r
        out.append(r)
    return out


# ------------------------------------------------------------------ memo
def build_memo_json(v, owner, ref):
    val = v["validation"]
    bid, assess = v["bid"], v.get("assessment", {})
    reqs = v["requirements"]
    rec = val.get("recommended_site")
    fits = val.get("site_fit", [])
    gates = val["gates"]
    best = next((f for f in fits if f["site"] == rec), None)
    abc = bid.get("abc_php")
    abc_txt = f"PHP {abc:,.2f}" if isinstance(abc, (int, float)) else "not stated"
    reasons = []
    for name, key in (("eligibility (SLCC)", "gate1"), ("delivery lead time", "gate2"), ("data center compliance", "gate3")):
        if gates[key] in ("Fail", "Unverified"):
            reasons.append(f"{name} is {gates[key].lower()}")
    site_line = ""
    if best:
        g = best["counts"].get("Gap", 0)
        site_line = (f" Best-fit site: {rec}, with {g} gap(s) across {best['n']} VITRO data center requirements"
                     + (f" ({', '.join(x.split(' ', 1)[1] for x in best['gaps'][:4])})." if g else "."))
    summary = (f"Recommendation: {val['verdict']}. {bid.get('procuring_entity', '')} {bid.get('title', '')} "
               f"(Approved Budget for the Contract, ABC, {abc_txt}): "
               + ("; ".join(reasons) if reasons else "all three gates pass with cited evidence") + "." + site_line)
    spec = ref.get("spec", {}) or {}
    src = (f"Source: bid documents listed in the matrix; {spec.get('name', 'Specifications Table')} "
           f"(uploaded {str(spec.get('modified', ''))[:10]}); Reference Register "
           f"{(ref.get('register') or {}).get('name', '(none; blank template used)')}.")

    gate_rows = [
        ["1. Eligibility (SLCC)", gates["gate1"], (assess.get("gate1") or {}).get("basis", ""), "ITB 5.3; BDS 5.4, 5.5"],
        ["2. Delivery lead time", gates["gate2"], (assess.get("gate2") or {}).get("basis", ""), "Section VI"],
        ["3. Data center compliance", gates["gate3"],
         (f"Recommended site {rec}: " + ", ".join(f"{k} {n}" for k, n in sorted(best["counts"].items())) + ".")
         if best else "", "Technical specifications; Site Fit sheet"],
    ]
    fit_rows = [[f["site"], f["fit"],
                 ", ".join(f"{k} {n}" for k, n in sorted(f["counts"].items())),
                 ", ".join(x.split(" ", 1)[1] for x in f["gaps"][:6]) or "-"] for f in fits]
    flags = [[f["flag"], f.get("reference", ""), "To assign", "Before bid decision"] for f in assess.get("flags", [])]
    open_rows = []
    if rec:
        order = {"Gap": 0, "Clarify": 1, "Partial": 2}
        cand = [(order[r["sites"][rec]["rating"]], r) for r in reqs
                if r.get("scope") == "VITRO DC" and r["sites"][rec]["rating"] in order]
        for _, r in sorted(cand, key=lambda x: x[0])[:10]:
            sr = r["sites"][rec]
            open_rows.append([r.get("clause", ""), (r.get("text") or "")[:90], sr["rating"],
                              r.get("clarification") or sr.get("note", "")])
    sections = [
        {"heading": "Gate Results",
         "paragraphs": ["A Go needs all three gates to pass with cited evidence."],
         "table": {"headers": ["Gate", "Result", "Basis", "Reference"], "widths": [2.2, 1.3, 4.2, 2.3],
                   "rows": gate_rows, "status_col": 1, "source": src}},
        {"heading": "Site Fit",
         "paragraphs": ["Each VITRO data center requirement was rated for every site against the Specifications "
                        "Table. One site must meet every requirement."],
         "table": {"headers": ["Site", "Fit", "Ratings", "Gap clauses"], "widths": [2.0, 1.3, 4.0, 2.7],
                   "rows": fit_rows, "status_col": 1, "source": src}},
    ]
    if flags:
        sections.append({"heading": "Flags for Decision",
                         "table": {"headers": ["Flag", "Reference", "Owner", "Needed by"],
                                   "widths": [4.6, 2.6, 1.4, 1.4], "rows": flags,
                                   "source": "Source: bid documents and bulletins, as referenced in each row."}})
    if open_rows:
        sections.append({"heading": f"Open Items at {rec}",
                         "table": {"headers": ["Clause", "Requirement", "Rating", "What is needed"],
                                   "widths": [1.2, 3.2, 1.1, 4.0], "rows": open_rows, "status_col": 2,
                                   "source": src + " Full list in the matrix (Open Items, Site Fit)."}})
    sections.append({"heading": "Next Steps", "paragraphs": [
        "1. Confirm the gaps and clarifications above with Facilities and the bid lead.",
        "2. Fill the Reference Register rows the gates need (contracts, lead times, site distances, personnel) and run again.",
        "3. A reviewer signs off every matrix row before any compliance statement. Section VII treats false "
        "statements in the compliance form as fraud.",
        "4. Ratings and the recommended site are drafts produced by the bid qualification tool; the bid/no-bid "
        "decision rests with the bid lead."]})
    import datetime as dt

    return {"iom_number": "[IOM number]", "date": dt.date.today().strftime("%B %d, %Y"),
            "to": "Head, Solutions", "endorsed_by": "[Name]", "from": owner,
            "subject": f"Bid / No-Bid and Site Fit: {bid.get('procuring_entity', '')} {bid.get('title', '')} "
                       f"({bid.get('reference_no', '')})",
            "summary": summary, "sections": sections}


# ------------------------------------------------------------------ job
def run(job_id, owner, upload_dir, title, spec):
    work = config.DATA_DIR / "jobs" / job_id
    out_dir = work / "output"
    for d in (work, out_dir):
        d.mkdir(parents=True, exist_ok=True)

    def step(name, pct):
        db.job_update(job_id, status="running", step=name, progress=pct)
        log.info("[%s] %s", job_id, name)

    try:
        # 1 reference files: the Specifications Table confirmed in step 2, the latest Reference Register
        step("Reading the reference files", 3)
        spec_path = specstore.copy_to(spec, work / "ref")
        st = refsource.status()
        if st.get("register"):
            reg_path = refsource.fetch(st["register"], work / "ref")
        else:
            reg_path = work / "ref" / "blank_register.xlsx"
            shutil.copy2(config.BLANK_REGISTER, reg_path)
        ref = {"location": st["location"],
               "spec": {"id": spec["id"], "name": spec["name"], "sha256": spec["sha256"], "source": spec["source"],
                        "uploaded_by": spec["uploaded_by"],
                        "modified": dt.datetime.fromtimestamp(spec["uploaded"]).isoformat(timespec="seconds")},
               "register": {k: st["register"].get(k) for k in ("name", "modified", "web_url")} if st.get("register") else None,
               "register_error": st.get("error")}
        db.job_update(job_id, reference=ref)

        # 2 extract
        step("Extracting the bid documents", 8)
        pdfs = sorted(upload_dir.glob("*.pdf"))
        if not pdfs:
            raise JobError("No PDF files were uploaded.")
        run_script("extract_bid.py", work / "extract", *pdfs)
        manifest = json.loads((work / "extract" / "manifest.json").read_text())

        # 3 specifications
        step("Reading the Specifications Table", 12)
        run_script("read_specs.py", spec_path, work / "specs")
        specs = json.loads((work / "specs" / "specs.json").read_text())
        specs_md = (work / "specs" / "specs.md").read_text()
        sites = [s["name"] for s in specs["sites"]]

        if config.AI_MODE == "replay":
            step("Replay mode: loading saved AI outputs", 40)
            terms = json.loads((config.REPLAY_DIR / "terms.json").read_text())
            reqs = json.loads((config.REPLAY_DIR / "requirements.json").read_text())
        else:
            terms, reqs = ai_steps(job_id, work, manifest, specs_md, reg_path, sites, step)

        # 8 gates and matrix
        step("Checking gates and building the matrix", 85)
        bid = terms["bid"]
        bid["documents"] = [f"{m['file']} ({m['pages']} pp{', scanned' if m['scanned_pages'] else ''})"
                            for m in manifest]
        assessment = {"flags": terms.get("flags", [])}
        n_partner = sum(1 for r in reqs if r.get("scope") == "Partner")
        if bid.get("subcontracting") == "Not allowed" and n_partner:
            assessment["flags"].insert(0, {
                "flag": f"Subcontracting is not allowed, while {n_partner} requirement rows are partner equipment, "
                        "software or integration. VITRO would supply these as prime or bid as a joint venture.",
                "reference": "BDS 8.1"})
        gates_path = work / "gates.json"
        if bid.get("abc_php"):
            args = ["--register", reg_path, "--abc", bid["abc_php"], "--out", gates_path]
            if bid.get("bid_deadline"):
                args += ["--deadline", bid["bid_deadline"]]
            if bid.get("slcc_window_years"):
                args += ["--slcc-years", bid["slcc_window_years"]]
            if bid.get("delivery_days"):
                args += ["--delivery-days", bid["delivery_days"]]
            if bid.get("slcc_excludes_ongoing_recurring"):
                args.append("--exclude-recurring")
            run_script("check_gates.py", *args)
        else:
            gates_path.write_text(json.dumps({
                "gate1_slcc": {"result": "Unverified", "threshold_rule_a_php": 0, "notes": ["ABC not found."]},
                "gate2_delivery": {"result": "Unverified", "required_days": bid.get("delivery_days"),
                                   "vitro_days": None, "notes": ["ABC not found."]}}))
        g = json.loads(gates_path.read_text())
        g1, g2 = g["gate1_slcc"], g["gate2_delivery"]
        assessment["gate1"] = {"result": g1["result"], "basis": " ".join(g1.get("notes", []))
                               + (f" Threshold 50% of ABC = PHP {g1['threshold_rule_a_php']:,.2f}."
                                  if g1.get("threshold_rule_a_php") else "")}
        assessment["gate2"] = {"result": g2["result"],
                               "basis": f"Required {g2.get('required_days')} days. " + " ".join(g2.get("notes", []))}
        req_path = work / "requirements.json"
        req_path.write_text(json.dumps({"bid": bid, "assessment": assessment, "requirements": reqs}, indent=1))
        slug = re.sub(r"[^A-Za-z0-9]+", "_", (bid.get("reference_no") or title or job_id))[:40].strip("_")
        matrix = out_dir / f"{slug}_Matrix.xlsx"
        run_script("build_matrix.py", "--requirements", req_path, "--gates", gates_path, "--specs",
                   work / "specs" / "specs.json", "--register", reg_path, "--out", matrix,
                   "--validated", work / "validated.json")
        v = json.loads((work / "validated.json").read_text())

        # 9 memo
        step("Writing the memo", 95)
        memo_json = work / "memo.json"
        memo_json.write_text(json.dumps(build_memo_json(v, owner, ref), indent=1))
        memo = out_dir / f"{slug}_GoNoGo.docx"
        run_script("build_memo.py", memo_json, memo, "--template", config.MEMO_TEMPLATE)

        val = v["validation"]
        result = {
            "verdict": val["verdict"], "gates": val["gates"], "recommended_site": val.get("recommended_site"),
            "site_fit": [{"site": f["site"], "fit": f["fit"], "counts": f["counts"],
                          "gaps": [x.split(" ", 1)[1] for x in f["gaps"]]} for f in val.get("site_fit", [])],
            "flags": assessment["flags"], "bid": {k: bid.get(k) for k in
                                                 ("title", "procuring_entity", "reference_no", "abc_php",
                                                  "bid_deadline", "delivery_days")},
            "counts": {"requirements": len(reqs), "downgraded": len(val.get("downgraded", []))},
            "files": {"matrix": matrix.name, "memo": memo.name},
            "areas": dc_areas(v.get("requirements", []), val.get("recommended_site")),
            "clarifications": clarifications(v.get("requirements", []), val.get("recommended_site")),
            "ai_mode": config.AI_MODE,
        }
        db.job_update(job_id, status="done", step="Done", progress=100, result=result,
                      title=f"{bid.get('procuring_entity', '')}: {bid.get('title', '')}".strip(": ") or title)
        db.audit(owner, "job_done", {"job": job_id, "verdict": val["verdict"], "spec": ref["spec"]["name"]})
    except Exception as e:
        log.error("[%s] failed: %s", job_id, traceback.format_exc())
        msg = str(e) if isinstance(e, (JobError, ai.AIError)) else f"Unexpected error: {e}"
        db.job_update(job_id, status="failed", error=msg)
        db.audit(owner, "job_failed", {"job": job_id, "error": msg[:500]})


# Gate 3 areas, in the order of the Solutions team's review steps.
AREAS = [("Colocation", ["Colocation", "Facility rating", "Security", "Service levels"]),
         ("DR seats", ["DR seats"]),
         ("Office space", ["Office space"]),
         ("Connectivity", ["Connectivity"]),
         ("Additional requirements", ["Certifications", "Personnel", "Other"])]


def _site_rating(r, site):
    if r.get("scope") == "VITRO DC" and site and site in (r.get("sites") or {}):
        return r["sites"][site].get("rating", "Unverified")
    return r.get("rating", "Unverified")


def dc_areas(reqs, site):
    """Gate 3 rating counts per review area, for the recommended site (or the overall rating)."""
    out = []
    for area, cats in AREAS:
        rows = [r for r in reqs if r.get("category") in cats and r.get("scope") in ("VITRO DC", "Bidder (general)")
                and r.get("mandatory", True)]
        c = collections.Counter(_site_rating(r, site) for r in rows)
        if not rows:
            res = "Not required"
        elif c["Gap"]:
            res = "Gap"
        elif c["Clarify"] or c["Partial"] or c["Unverified"]:
            res = "Needs review"
        else:
            res = "Comply"
        out.append({"area": area, "result": res, "n": len(rows), "counts": dict(c)})
    return out


def clarifications(reqs, site):
    """Items to raise at the Pre-Bid Conference or by written clarification."""
    out = []
    for r in reqs:
        ratings = {r.get("rating")} | {s.get("rating") for s in (r.get("sites") or {}).values()}
        q = (r.get("clarification") or "").strip()
        if q and "Clarify" in ratings:
            out.append({"id": r["id"], "clause": r.get("clause") or "", "doc": r.get("doc") or "",
                        "category": r.get("category") or "", "question": q})
    return out


def ai_steps(job_id, work, manifest, specs_md, reg_path, sites, step):
    ext = work / "extract"
    by_type = collections.defaultdict(list)
    for m in manifest:
        by_type[m["type"]].append(m)

    # 4 bid terms
    step("Reading the bid terms", 18)
    pages = []
    for m in by_type["Bidding documents (PBD)"] + by_type["Other"]:
        want = set(range(1, min(m["pages"], 3) + 1))
        for k in ("Bid Data Sheet (BDS)", "SLCC / similar contract", "Schedule of Requirements (Sec VI)",
                  "Deadline / bid opening", "NFCC / credit line"):
            want |= set(m["hits"].get(k, [])[:6])
        pages += page_list(ext, m, sorted(want)[:30])
    for m in by_type["Bid Bulletin / SBB"]:
        want = {1, 2, m["pages"]} | set(m["hits"].get("SLCC / similar contract", [])) | \
            set(m["hits"].get("Deadline / bid opening", []))
        pages += page_list(ext, m, sorted(p for p in want if 1 <= p <= m["pages"])[:12])
    terms = ai.call_json("terms", ai.TERMS_SYSTEM, ai.pdf_page_blocks(pages) +
                         [{"type": "text", "text": "Extract the bid terms and flags."}], ai.TERMS_SCHEMA)

    # 5 requirements
    tor = by_type["TOR / Annex"]
    targets = [(m, list(range(1, m["pages"] + 1))) for m in tor]
    if not targets:  # technical specs inside the bidding documents
        for m in by_type["Bidding documents (PBD)"]:
            ps = sorted(set(m["hits"].get("Technical Specifications (Sec VII)", []))
                        | set(m["hits"].get("Schedule of Requirements (Sec VI)", [])))
            targets.append((m, [p for p in ps if p > 5]))
    calls = [(m, c) for m, ps in targets for c in chunks(ps, PAGES_PER_CALL)]
    rows = []
    for i, (m, c) in enumerate(calls, 1):
        step(f"Reading technical requirements ({i}/{len(calls)})", 20 + int(30 * i / max(1, len(calls))))
        doc = short_doc(m["file"])
        res = ai.call_json(f"requirements {i}", ai.REQ_SYSTEM,
                           ai.pdf_page_blocks(page_list(ext, m, c)) +
                           [{"type": "text", "text": f'Document name: "{doc}". Extract every requirement on these pages.'}],
                           ai.REQ_SCHEMA)
        rows += res["requirements"]
    rows = merge_requirements(rows)
    b = terms["bid"]
    fixed = [{"doc": "Bidding Documents", "page": 0, "clause": "BDS 5.4/5.5; ITB 5.3", "section": "Eligibility",
              "category": "Eligibility", "scope": "Bidder (general)", "mandatory": True,
              "text": f"Single Largest Completed Contract (SLCC): {b.get('slcc_rule', '')} "
                      f"Similar contract: {b.get('similar_definition', '')}".strip()}]
    if b.get("delivery_days"):
        fixed.append({"doc": "Bidding Documents", "page": 0, "clause": "Sec VI", "section": "Schedule of Requirements",
                      "category": "Delivery", "scope": "Bidder (general)", "mandatory": True,
                      "text": f"Delivery within {b['delivery_days']} {b.get('delivery_basis', 'calendar days')}."})
    rows = fixed + rows

    # 6 bulletins
    items = []
    bl = [(m, c) for m in by_type["Bid Bulletin / SBB"] for c in chunks(list(range(1, m["pages"] + 1)), PAGES_PER_CALL)]
    for i, (m, c) in enumerate(bl, 1):
        step(f"Reading bid bulletins ({i}/{len(bl)})", 50 + int(10 * i / max(1, len(bl))))
        res = ai.call_json(f"bulletin {i}", ai.BULLETIN_SYSTEM,
                           ai.pdf_page_blocks(page_list(ext, m, c)) +
                           [{"type": "text", "text": "Extract every bulletin item on these pages. An item cut off at "
                                                     "a page boundary: include what is visible."}],
                           ai.BULLETIN_SCHEMA)
        items += res["items"]
    items = list({(x["item"], x["page"]): x for x in items}.values())
    (work / "bulletin_items.json").write_text(json.dumps(items, indent=1))
    apply_bulletins(rows, items)
    for i, r in enumerate(rows, 1):
        r["id"] = f"R-{i:03d}"

    # 7 site ratings
    system = ai.rating_system(specs_md, register_digest(reg_path))
    to_rate = [r for r in rows if r["scope"] in ("VITRO DC", "Bidder (general)")]
    batches = list(chunks(to_rate, RATE_BATCH))
    rated = {}
    for i, batch in enumerate(batches, 1):
        step(f"Rating sites ({i}/{len(batches)})", 60 + int(24 * i / max(1, len(batches))))
        payload = [{"id": r["id"], "clause": r["clause"], "category": r["category"], "scope": r["scope"],
                    "requirement": r["text"], "bulletin": r.get("amended_text", "")} for r in batch]
        res = ai.call_json(f"rating {i}", system, [{"type": "text", "text":
                           "Sites: " + ", ".join(sites) + "\n\nRequirements:\n" + json.dumps(payload, indent=1)}],
                           ai.RATING_SCHEMA, cache_system=True)
        for x in res["ratings"]:
            rated[x["id"]] = x
    for r in rows:
        x = rated.get(r["id"])
        if r["scope"] == "Partner":
            r["rating"] = "Partner scope"
            continue
        if not x:
            r["rating"], r["rationale"] = "Unverified", "Not rated."
            continue
        r["clarification"] = x.get("clarification", "")
        if r["scope"] == "VITRO DC":
            r["sites"] = {s["site"]: {"rating": s["rating"], "evidence": s["evidence"], "note": s["note"]}
                          for s in x["sites"] if s["site"] in sites}
        else:
            r["rating"], r["evidence"], r["rationale"] = x["rating"], x["evidence"], x["rationale"]
    return terms, rows
