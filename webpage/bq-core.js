/* VITRO bid qualification: rules that run in the browser (port of engine/scripts and app/pipeline.py).
 * No network, no Claude calls: pure functions over parsed workbooks and JSON.
 * Works in the page (window.BQ) and in Node for tests (module.exports). Needs a SheetJS-compatible XLSX.
 */
(function (root) {
  "use strict";

  // ------------------------------------------------------------ helpers
  const clean = (v) => {
    if (v === null || v === undefined) return "";
    if (typeof v === "number" && Number.isInteger(v)) v = String(v);
    const s = String(v).replace(/　/g, " ").trim();
    return s.startsWith("=") ? "" : s;
  };
  const asDate = (v) => {
    if (v === null || v === undefined || v === "") return null;
    if (v instanceof Date && !isNaN(v)) return new Date(Date.UTC(v.getFullYear(), v.getMonth(), v.getDate()));
    const m = String(v).trim().match(/^(\d{4})-(\d{2})-(\d{2})/);
    return m ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])) : null;
  };
  const iso = (d) => (d ? d.toISOString().slice(0, 10) : null);
  const asNum = (v) => {
    if (v === null || v === undefined || v === "") return null;
    if (typeof v === "number") return v;
    const n = parseFloat(String(v).replace(/,/g, "").replace(/PHP/g, "").trim());
    return isNaN(n) ? null : n;
  };
  const counter = (arr) => arr.reduce((c, k) => ((c[k] = (c[k] || 0) + 1), c), {});
  const chunks = (seq, n) => { const out = []; for (let i = 0; i < seq.length; i += n) out.push(seq.slice(i, i + n)); return out; };
  const days = (a, b) => Math.round((a - b) / 86400000);

  // ------------------------------------------------------------ Specifications Table (read_specs.py)
  const SYMBOL = { "n": "Available", "●": "Available", "q": "Not available", "○": "Not available",
                   "i": "Optional", "-": "Not applicable" };
  const NEGATIVE = ["Not available", "Not applicable"];
  const HEADER_ROWS = { "Data Center name": "name", "Address": "address", "City": "city",
                        "Data Center ownership type": "ownership" };
  const FIRST_SITE_COL = 8; // column H

  function decode(raw) {
    const s = clean(raw);
    if (!s) return ["Blank", ""];
    const i = s.indexOf("\n");
    const first = (i < 0 ? s : s.slice(0, i)).trim();
    const rest = i < 0 ? "" : s.slice(i + 1);
    if (first in SYMBOL) return [SYMBOL[first], rest.trim().replace(/^\(+|\)+$/g, "").trim()];
    return ["Value", s];
  }

  /** wb: a workbook from XLSX.read(..., {cellDates: true}). */
  function readSpecs(XLSX, wb, fileName, sheetName) {
    const name = sheetName || wb.SheetNames[0];
    const ws = wb.Sheets[name];
    if (!ws || !ws["!ref"]) return { source: { file: fileName, sheet: name }, sites: [], rows: [] };
    const rg = XLSX.utils.decode_range(ws["!ref"]);
    const raw = (r, c) => { const x = ws[XLSX.utils.encode_cell({ r: r - 1, c: c - 1 })]; return x ? x.v : null; };
    const carry = {};
    for (const m of ws["!merges"] || []) {
      if (m.s.c === m.e.c && [0, 2, 3, 4].includes(m.s.c)) {
        const v = raw(m.s.r + 1, m.s.c + 1);
        for (let r = m.s.r + 1; r <= m.e.r + 1; r++) carry[r + ":" + (m.s.c + 1)] = v;
      }
    }
    const cell = (r, c) => clean((r + ":" + c) in carry ? carry[r + ":" + c] : raw(r, c));
    const maxRow = rg.e.r + 1, maxCol = rg.e.c + 1;
    const sites = [];
    for (let c = FIRST_SITE_COL; c <= maxCol; c++) { const n = clean(raw(1, c)); if (n) sites.push({ col: c, name: n }); }
    for (let r = 1; r <= 5; r++) {
      const key = HEADER_ROWS[clean(raw(r, 1))];
      if (key && key !== "name") for (const s of sites) s[key] = clean(raw(r, s.col));
    }
    const rows = [];
    let section = "", group = "", itemParent = "";
    for (let r = 2; r <= maxRow; r++) {
      const aVal = cell(r, 1), labelC = cell(r, 3), desc = cell(r, 4), base = cell(r, 5), example = clean(raw(r, 6));
      const vals = {}; for (const s of sites) vals[s.name] = raw(r, s.col);
      const hasVals = Object.values(vals).some((v) => clean(v));
      const hdr = clean(raw(r, 1));
      if (hdr in HEADER_ROWS) {
        if (HEADER_ROWS[hdr] !== "name") {
          const cells = {};
          for (const s of sites) { const v = clean(vals[s.name]); cells[s.name] = { status: v ? "Value" : "Blank", detail: v }; }
          rows.push({ id: "SPEC-" + r, row: r, section: "Site details", group: "", item: hdr, description: "", baseline: "", cells });
        }
        continue;
      }
      if (aVal && !labelC && !hasVals && !example) { section = aVal; group = ""; continue; }
      if (aVal) group = aVal;
      if (labelC) itemParent = labelC;
      if (!hasVals) continue;
      let item;
      if (example && !example.startsWith("<e.g.>") && !clean(raw(r, 4))) item = itemParent + ": " + example;
      else item = labelC || desc || itemParent;
      const cells = {};
      for (const s of sites) { const [status, detail] = decode(vals[s.name]); cells[s.name] = { status, detail }; }
      rows.push({ id: "SPEC-" + r, row: r, section, group, item, description: desc !== item ? desc : "", baseline: base, cells });
    }
    const m = String(fileName).match(/(\d{8})/);
    return {
      source: { file: fileName, sheet: name, file_date_in_name: m ? m[1] : null,
                legend: "n/● Available; q/○ Not available; i Optional; - Not applicable" },
      sites: sites.map(({ col, ...s }) => s),
      rows,
    };
  }

  function specsMarkdown(specs) {
    const src = specs.source;
    const lines = [`# VITRO Specifications Table: ${src.file} (sheet '${src.sheet}')`,
      `Legend: ${src.legend}. Blank = no data for that site (treat as unverified, never as available).`, "", "## Sites"];
    for (const s of specs.sites) lines.push(`- ${s.name}: ${[s.city || "", s.address || "", s.ownership || ""].join("; ").replace(/(; )+$/, "")}`);
    let cur = null;
    for (const row of specs.rows) {
      if (row.section !== cur) { cur = row.section; lines.push("", `## ${cur || "General"}`); }
      let head = `**${row.id}** ${row.group && row.group !== row.item ? row.group + " / " : ""}${row.item}`;
      if (row.baseline && row.baseline !== "-") head += `  _(baseline: ${row.baseline.slice(0, 90)})_`;
      lines.push(head);
      const parts = [];
      for (const [name, c] of Object.entries(row.cells)) {
        if (c.status === "Blank") continue;
        const v = c.status === "Value" ? c.detail : c.status + (c.detail ? ` (${c.detail})` : "");
        parts.push(`${name}: ${v.replace(/\n/g, "; ")}`);
      }
      lines.push("  " + parts.join(" | "));
    }
    return lines.join("\n") + "\n";
  }

  function summariseSpecs(specs) {
    const filled = {};
    for (const row of specs.rows) for (const [site, c] of Object.entries(row.cells)) if (c.status !== "Blank") filled[site] = (filled[site] || 0) + 1;
    const sections = counter(specs.rows.map((r) => r.section || "General"));
    return {
      sheet: specs.source.sheet, rows: specs.rows.length,
      sites: specs.sites.map((s) => ({ name: s.name, city: s.city || "", ownership: s.ownership || "",
        filled: filled[s.name] || 0, blank: specs.rows.length - (filled[s.name] || 0) })),
      sections: Object.entries(sections).map(([name, rows]) => ({ name, rows })),
    };
  }

  // ------------------------------------------------------------ Reference Register (register_schema.py)
  const REGISTER_SHEETS = ["Contracts", "DR Seats & Office", "Personnel", "Site Distances", "Lead Times"];
  const EXPIRY_COL = { "Personnel": "Earliest Expiry" };
  const HEADER_ROW = 4;

  function loadRegister(XLSX, wb) {
    const rows = {}, byId = {};
    for (const sheet of REGISTER_SHEETS) {
      rows[sheet] = [];
      const ws = wb && wb.Sheets[sheet];
      if (!ws || !ws["!ref"]) continue;
      const aoa = XLSX.utils.sheet_to_json(ws, { header: 1, raw: true, defval: null, blankrows: true });
      const headers = (aoa[HEADER_ROW - 1] || []).map((h) => (h === null ? null : String(h)));
      for (const r of aoa.slice(HEADER_ROW)) {
        if (!r || !r.some((v) => v !== null && v !== "")) continue;
        const d = {}; headers.forEach((h, j) => { if (h) d[h] = r[j] === undefined ? null : r[j]; });
        if (!d.ID) continue;
        if (!Object.entries(d).some(([k, v]) => k !== "ID" && v !== null && v !== "")) continue;
        rows[sheet].push(d);
        byId[String(d.ID).trim()] = [sheet, d];
      }
    }
    return { rows, byId };
  }

  function registerDigest(XLSX, wb) {
    if (!wb) return "";
    const lines = [];
    for (const name of wb.SheetNames) {
      if (name === "README") continue;
      const aoa = XLSX.utils.sheet_to_json(wb.Sheets[name], { header: 1, raw: true, defval: null });
      const headers = aoa[HEADER_ROW - 1] || [];
      const out = [];
      for (const r of aoa.slice(HEADER_ROW)) {
        const parts = [];
        headers.forEach((h, j) => { const v = r && r[j]; if (h && v !== null && v !== undefined && v !== "") parts.push(`${h}: ${v instanceof Date ? iso(asDate(v)) : v}`); });
        if (parts.length > 1) out.push(parts.join("; "));
      }
      lines.push(`## ${name}: ` + (out.length ? "" : "(no rows)"));
      for (const x of out) lines.push("- " + x);
    }
    return lines.join("\n");
  }

  // ------------------------------------------------------------ Gates 1 and 2 (check_gates.py)
  const STALE_DAYS = 180;
  function gate1(rows, abc, deadline, years, excludeRecurring) {
    const contracts = rows["Contracts"] || [];
    const out = { abc_php: abc, threshold_rule_a_php: Math.round(abc * 50) / 100, threshold_rule_b_single_php: Math.round(abc * 25) / 100,
      window_start: null, register_contracts: contracts.length, eligible_contracts: [], excluded: [],
      rule_a_candidates: [], rule_b_candidates: [], result: null, notes: [] };
    let start = null;
    if (deadline) { start = new Date(Date.UTC(deadline.getUTCFullYear() - years, deadline.getUTCMonth(), deadline.getUTCDate())); out.window_start = iso(start); }
    else out.notes.push("No deadline given: completion window not checked.");
    const elig = [];
    for (const c of contracts) {
      const why = [];
      if (String(c["Status"] || "").trim().toLowerCase() !== "completed") why.push(`status '${c["Status"]}'`);
      const comp = asDate(c["Completion Date"]);
      if (!comp) why.push("no completion date");
      else if (start && comp < start) why.push(`completed ${iso(comp)} before window start ${iso(start)}`);
      else if (deadline && comp > deadline) why.push(`completion ${iso(comp)} after deadline`);
      if (excludeRecurring && String(c["Recurring Component (Y/N)"] || "").toUpperCase().startsWith("Y")) why.push("has recurring component (excluded for this bid)");
      if (!c["Source Document"]) why.push("no Source Document");
      const adj = asNum(c["CPI-Adjusted Amount (PHP)"]), nom = asNum(c["Contract Amount (PHP, VAT inc.)"]);
      const amt = adj !== null ? adj : nom;
      if (amt === null) why.push("no amount");
      if (why.length) { out.excluded.push({ id: String(c.ID), reasons: why }); continue; }
      elig.push({ id: String(c.ID), client: c["Client / Procuring Entity"], title: c["Contract Title"], scope: c["Scope Description"],
        completion: iso(comp), amount_used_php: amt, amount_basis: adj !== null ? "CPI-adjusted" : "nominal (not CPI-adjusted)",
        pct_of_abc: Math.round(1000 * amt / abc) / 10, source: c["Source Document"] });
    }
    elig.sort((a, b) => b.amount_used_php - a.amount_used_php);
    out.eligible_contracts = elig;
    out.rule_a_candidates = elig.filter((e) => e.amount_used_php >= abc * 0.5).map((e) => e.id);
    for (const e of elig) {
      if (e.amount_used_php >= abc * 0.25) {
        const others = elig.filter((o) => o.id !== e.id).reduce((s, o) => s + o.amount_used_php, 0);
        if (others >= abc * 0.25) out.rule_b_candidates.push({ single: e.id, others_aggregate_php: others });
      }
    }
    if (!contracts.length) { out.result = "Unverified"; out.notes.push("Contracts register is empty. SLCC cannot be checked."); }
    else if (out.rule_a_candidates.length || out.rule_b_candidates.length) {
      out.result = "Needs review"; out.notes.push("Candidates meet the amount and date tests. Confirm each is 'similar' per the BDS definition.");
    } else { out.result = "Fail"; out.notes.push("No completed contract in the register meets the amount and date tests."); }
    if (elig.some((e) => e.amount_basis.startsWith("nominal"))) out.notes.push("Some amounts are nominal. The bid rules adjust SLCC value to current prices (PSA CPI).");
    return out;
  }

  function gate2(rows, requiredDays, ltIds) {
    const lts = {}; for (const r of rows["Lead Times"] || []) lts[String(r.ID)] = r;
    const out = { required_days: requiredDays, selected: [], missing_ids: [], vitro_days: null, margin_days: null, result: null, notes: [] };
    for (const i of ltIds || []) {
      const r = lts[i];
      if (!r) { out.missing_ids.push(i); continue; }
      out.selected.push({ id: i, category: r["Category"], days: asNum(r["Standard Lead Time (calendar days)"]), condition: r["Condition"], source: r["Source Document"] });
    }
    const ds = out.selected.filter((s) => s.days !== null && s.source).map((s) => s.days);
    if (requiredDays === null || requiredDays === undefined) { out.result = "Unverified"; out.notes.push("Required delivery period not given."); }
    else if (!ds.length) { out.result = "Unverified"; out.notes.push("No sourced lead times selected from the register. Feasibility needs the delivery team's estimate."); }
    else {
      const v = Math.max(...ds); out.vitro_days = v; out.margin_days = requiredDays - v;
      out.result = v <= requiredDays ? "Pass" : "Fail";
      out.notes.push("Assumes selected items run in parallel; reviewer to adjust for sequencing.");
    }
    return out;
  }

  // ------------------------------------------------------------ Evidence rules, site fit, verdict (build_matrix.py)
  const GATE3_EXCLUDED = ["Eligibility", "Delivery"];
  const OWN_SCOPES = ["VITRO DC", "Bidder (general)"];

  function checkEvidence(rating, evidence, byId, specs, deadline, site) {
    let checks = [], problems = [];
    if (rating !== "Comply" && rating !== "Partial") return [rating, checks, problems];
    if (!evidence.length) problems.push("no evidence cited");
    for (let e of evidence) {
      e = String(e).trim();
      if (e.startsWith("SPEC-")) {
        const row = specs[e];
        if (!row) { problems.push(`${e} not in Specifications Table`); continue; }
        if (!site) { problems.push(`${e} cited without a site`); continue; }
        const cell = row.cells[site];
        if (!cell || cell.status === "Blank") problems.push(`${e} blank for ${site}`);
        else if (rating === "Comply" && NEGATIVE.includes(cell.status)) problems.push(`${e} says '${cell.status}' for ${site}`);
        continue;
      }
      const hit = byId[e];
      if (!hit) { problems.push(`${e} not in register`); continue; }
      const [sheet, row] = hit;
      if (!row["Source Document"]) problems.push(`${e} has no Source Document`);
      const expCol = EXPIRY_COL[sheet];
      const exp = expCol ? asDate(row[expCol]) : null;
      if (exp && deadline && exp < deadline) problems.push(`${e} expired ${iso(exp)}`);
      const asof = asDate(row["As-of Date"]);
      if (!asof || (deadline && days(deadline, asof) > STALE_DAYS)) checks.push(`${e} stale (as of ${asof ? iso(asof) : "unknown"})`);
    }
    if (problems.length) { checks = [`Downgraded from ${rating}: ` + problems.join("; ")].concat(checks); rating = "Unverified"; }
    return [rating, checks, problems];
  }

  function enforce(reqs, byId, specs, sites, deadline) {
    const notes = [];
    reqs.forEach((r, i) => {
      if (!r.id) r.id = "R-" + String(i + 1).padStart(3, "0");
      if (!r.evidence) r.evidence = [];
      if (r.mandatory === undefined) r.mandatory = true;
      if (!r.rating) r.rating = r.scope === "Partner" ? "Partner scope" : "Unverified";
      if (r.scope === "VITRO DC") {
        const given = r.sites || {};
        r.sites = {};
        for (const site of sites) {
          const sr = Object.assign({}, given[site] || { rating: "Unverified", evidence: [], note: "Not rated for this site." });
          sr.evidence = sr.evidence || [];
          const [rt, ch, probs] = checkEvidence(sr.rating || "Unverified", sr.evidence, byId, specs, deadline, site);
          sr.rating = rt; sr.checks = ch;
          if (probs.length) notes.push({ id: `${r.id} @ ${site}`, problems: probs });
          r.sites[site] = sr;
        }
        r.checks = [];
      } else {
        const [rt, ch, probs] = checkEvidence(r.rating, r.evidence, byId, specs, deadline, null);
        r.rating = rt; r.checks = ch;
        if (probs.length) notes.push({ id: r.id, problems: probs });
      }
    });
    return notes;
  }

  function siteFit(reqs, sites) {
    const dc = reqs.filter((r) => r.scope === "VITRO DC" && r.mandatory !== false && !GATE3_EXCLUDED.includes(r.category));
    const out = sites.map((site) => {
      const c = counter(dc.map((r) => r.sites[site].rating));
      let fit;
      if (dc.length && (c.Unverified || 0) > dc.length / 2) fit = "Insufficient data";
      else if (c.Gap) fit = "Fail";
      else if (c.Unverified || c.Clarify || c.Partial) fit = "Needs review";
      else if (dc.length) fit = "Pass";
      else fit = "Unverified";
      const gaps = dc.filter((r) => r.sites[site].rating === "Gap").map((r) => r.id + " " + (r.clause || ""));
      return { site, fit, counts: c, gaps, n: dc.length };
    });
    out.sort((a, b) => ((a.fit === "Insufficient data") - (b.fit === "Insufficient data")) || ((a.counts.Gap || 0) - (b.counts.Gap || 0))
      || ((b.counts.Comply || 0) - (a.counts.Comply || 0)) || ((b.counts.Partial || 0) - (a.counts.Partial || 0)));
    return out;
  }

  function gate3(reqs, fits, recommended) {
    const best = fits.find((f) => f.site === recommended) || fits[0] || null;
    const gen = reqs.filter((r) => r.scope === "Bidder (general)" && r.mandatory !== false && !GATE3_EXCLUDED.includes(r.category));
    const gc = counter(gen.map((r) => r.rating));
    const genRes = gc.Gap ? "Fail" : (gc.Unverified || gc.Clarify || gc.Partial) ? "Needs review" : (gen.length ? "Pass" : "Unverified");
    const order = ["Fail", "Unverified", "Needs review", "Pass"];
    let siteRes = best ? best.fit : "Unverified";
    if (siteRes === "Insufficient data") siteRes = "Unverified";
    const res = [siteRes, genRes].sort((a, b) => order.indexOf(a) - order.indexOf(b))[0];
    return [res, best, gc, gen.length];
  }

  function verdict(results) {
    if (results.includes("Fail")) return "No-Go";
    if (results.includes("Unverified")) return "Insufficient evidence";
    if (results.every((r) => r === "Pass")) return "Go";
    return "Conditional Go";
  }

  const AREAS = [["Colocation", ["Colocation", "Facility rating", "Security", "Service levels"]], ["DR seats", ["DR seats"]],
    ["Office space", ["Office space"]], ["Connectivity", ["Connectivity"]], ["Additional requirements", ["Certifications", "Personnel", "Other"]]];

  function siteRating(r, site) {
    if (r.scope === "VITRO DC" && site && r.sites && r.sites[site]) return r.sites[site].rating || "Unverified";
    return r.rating || "Unverified";
  }
  function dcAreas(reqs, site) {
    return AREAS.map(([area, cats]) => {
      const rows = reqs.filter((r) => cats.includes(r.category) && OWN_SCOPES.includes(r.scope) && r.mandatory !== false);
      const c = counter(rows.map((r) => siteRating(r, site)));
      const result = !rows.length ? "Not required" : c.Gap ? "Gap" : (c.Clarify || c.Partial || c.Unverified) ? "Needs review" : "Comply";
      return { area, result, n: rows.length, counts: c };
    });
  }
  function clarifications(reqs) {
    const out = [];
    for (const r of reqs) {
      const ratings = new Set([r.rating, ...Object.values(r.sites || {}).map((s) => s.rating)]);
      const q = (r.clarification || "").trim();
      if (q && ratings.has("Clarify")) out.push({ id: r.id, clause: r.clause || "", doc: r.doc || "", category: r.category || "", question: q });
    }
    return out;
  }

  /** Full validation, as build_matrix.py: returns the validated summary and mutates reqs. */
  function validate({ bid, assessment, reqs, specs, register, gates }) {
    const specIdx = {}; for (const r of specs.rows) specIdx[r.id] = r;
    const sites = specs.sites.map((s) => s.name);
    const deadline = asDate(bid.bid_deadline);
    const downgraded = enforce(reqs, register.byId, specIdx, sites, deadline);
    const fits = siteFit(reqs, sites);
    const rec = (assessment && assessment.recommended_site) || (fits[0] ? fits[0].site : null);
    for (const q of reqs) {
      if (q.scope === "VITRO DC" && rec) {
        const sr = q.sites[rec];
        q.rating = sr.rating; q.checks = sr.checks || [];
        q.evidence = sr.evidence.map((e) => (String(e).startsWith("SPEC-") ? `${e} @ ${rec}` : e));
        q.rationale = `[${rec}] ${sr.note || ""}`;
      }
    }
    const g1 = (assessment.gate1 && assessment.gate1.result) || gates.gate1_slcc.result;
    const g2 = (assessment.gate2 && assessment.gate2.result) || gates.gate2_delivery.result;
    const [g3] = gate3(reqs, fits, rec);
    return { verdict: verdict([g1, g2, g3]), gates: { gate1: g1, gate2: g2, gate3: g3 }, recommended_site: rec,
      site_fit: fits, downgraded, areas: dcAreas(reqs, rec), clarifications: clarifications(reqs) };
  }

  // ------------------------------------------------------------ Bid package helpers (pipeline.py, extract_bid.py)
  function docType(name, firstText) {
    const n = (name + " " + (firstText || "").slice(0, 2000)).toLowerCase();
    if (n.includes("bulletin") || n.includes("supplemental")) return "Bid Bulletin / SBB";
    if (n.includes("clarification")) return "Bidder clarification letter";
    if (n.includes("annex") || n.slice(0, 400).includes("technical specification") || n.includes("terms of reference")) return "TOR / Annex";
    if (n.includes("invitation to bid") || n.includes("bid data sheet") || n.includes("philippine bidding documents")) return "Bidding documents (PBD)";
    return "Other";
  }
  const LOCATORS = {
    "Bid Data Sheet (BDS)": /Bid Data Sheet/i,
    "Schedule of Requirements (Sec VI)": /Schedule of Requirements/i,
    "Technical Specifications (Sec VII)": /Technical Specifications/i,
    "SLCC / similar contract": /Single Largest Completed Contract|SLCC|similar contract|similar to the Project/i,
    "Deadline / bid opening": /deadline|submission and receipt of bids|opening of bids|on or before/i,
    "NFCC / credit line": /\bNFCC\b|Net Financial Contracting Capacity|committed line of credit/i,
  };
  function hits(pages) {
    const out = {};
    for (const [k, re] of Object.entries(LOCATORS)) out[k] = pages.map((t, i) => (re.test(t || "") ? i + 1 : 0)).filter(Boolean);
    return out;
  }
  function shortDoc(name) {
    const stem = name.replace(/\.pdf$/i, "");
    const m = stem.match(/Annex[ _]*([A-Z])/i);
    if (m) return "Annex " + m[1].toUpperCase();
    return stem.replace(/^[\d_]+/, "").replace(/_/g, " ").trim().slice(0, 40) || stem.slice(0, 40);
  }
  function mergeRequirements(rows) {
    const out = [], seen = {};
    for (const r of rows) {
      const key = [r.doc, r.clause, r.scope].join("\u0001");
      if (seen[key] && !seen[key].text.includes(r.text)) { seen[key].text += ` (cont. p${r.page}) ${r.text}`; continue; }
      if (seen[key]) continue;
      seen[key] = r; out.push(r);
    }
    return out;
  }
  function applyBulletins(rows, items) {
    const clauses = new Set(rows.map((r) => String(r.clause || "").split(" ")[0]));
    const hitsBy = {};
    const add = (k, b) => (hitsBy[k] = hitsBy[k] || []).push(b);
    for (const b of items) {
      if (!["Amends requirement", "Clarifies requirement"].includes(b.effect)) continue;
      for (let c of b.clauses || []) {
        c = String(c).trim();
        if (/^(BDS|ITB)/i.test(c)) { add("__eligibility__", b); continue; }
        const dots = (c.match(/\./g) || []).length;
        if (dots < 1) continue;
        if (clauses.has(c)) add(c, b);
        else {
          const kids = [...clauses].filter((x) => x.startsWith(c + "."));
          if (dots >= 2 && kids.length <= 6) for (const k of kids) add(k, b);
        }
      }
    }
    let n = 0;
    for (const r of rows) {
      const key = r.category === "Eligibility" ? "__eligibility__" : String(r.clause || "").split(" ")[0];
      const uniq = {}; for (const b of hitsBy[key] || []) uniq[b.item] = b;
      const bs = Object.values(uniq);
      if (bs.length) {
        n++;
        r.amended_by = "Bulletin item " + bs.map((b) => b.item).join(", ");
        r.amended_text = bs.map((b) => `[${b.item}] ${b.resolution}`).join(" | ");
      }
    }
    return n;
  }

  const BQ = { clean, asDate, iso, asNum, chunks, decode, readSpecs, specsMarkdown, summariseSpecs, loadRegister, registerDigest,
    gate1, gate2, checkEvidence, enforce, siteFit, gate3, verdict, dcAreas, clarifications, validate,
    docType, hits, shortDoc, mergeRequirements, applyBulletins, AREAS, REGISTER_SHEETS };
  if (typeof module !== "undefined" && module.exports) module.exports = BQ;
  else root.BQ = BQ;
})(typeof window !== "undefined" ? window : globalThis);
