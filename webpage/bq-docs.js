/* VITRO bid qualification: memo (.docx) and matrix (.xlsx) built in the browser.
 * Port of app/pipeline.build_memo_json, engine/scripts/build_memo.py and the matrix sheets of build_matrix.py.
 * fillMemo needs JSZip and a DOMParser/XMLSerializer pair; buildMatrix needs xlsx-js-style (global XLSX).
 */
(function (root) {
  "use strict";
  const W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
  const XMLNS = "http://www.w3.org/XML/1998/namespace";
  const COBALT = "00006E", INK = "1A1A2E", INK_MUTED = "5A5A6E", SURFACE = "F5F6F8", ROW_ALT = "EEEEF7", BORDER = "D1D1D1", WHITE = "FFFFFF";
  const STATUS = { green: ["1E6B45", "E3F1E9"], amber: ["A35F00", "FBF0DC"], red: ["B3261E", "FBE8E6"] };
  const RATING_STATUS = { Comply: "green", Pass: "green", Go: "green", Partial: "amber", Clarify: "amber", Unverified: "amber",
    "Needs review": "amber", "Conditional Go": "amber", "Insufficient evidence": "amber", "Insufficient data": "amber",
    Gap: "red", Fail: "red", "No-Go": "red" };
  const fmtPHP = (n) => "PHP " + Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const countsText = (c) => Object.keys(c).sort().map((k) => `${k} ${c[k]}`).join(", ");

  // ------------------------------------------------------------ memo content (build_memo_json)
  function buildMemoJson({ val, bid, assessment, reqs, owner, spec, register, today }) {
    const rec = val.recommended_site, fits = val.site_fit, gates = val.gates;
    const best = fits.find((f) => f.site === rec) || null;
    const abc = bid.abc_php;
    const abcTxt = typeof abc === "number" ? fmtPHP(abc) : "not stated";
    const reasons = [];
    for (const [name, key] of [["eligibility (SLCC)", "gate1"], ["delivery lead time", "gate2"], ["data center compliance", "gate3"]])
      if (gates[key] === "Fail" || gates[key] === "Unverified") reasons.push(`${name} is ${gates[key].toLowerCase()}`);
    let siteLine = "";
    if (best) {
      const g = best.counts.Gap || 0;
      siteLine = ` Best-fit site: ${rec}, with ${g} gap(s) across ${best.n} VITRO data center requirements` +
        (g ? ` (${best.gaps.slice(0, 4).map((x) => x.split(" ").slice(1).join(" ")).join(", ")}).` : ".");
    }
    const summary = `Recommendation: ${val.verdict}. ${bid.procuring_entity || ""} ${bid.title || ""} (Approved Budget for the Contract, ABC, ${abcTxt}): ` +
      (reasons.length ? reasons.join("; ") : "all three gates pass with cited evidence") + "." + siteLine;
    const src = `Source: bid documents listed in the matrix; ${spec.name} (uploaded ${String(spec.uploaded || "").slice(0, 10)}); ` +
      `Reference Register ${register ? register : "(none; blank register used)"}.`;
    const gateRows = [
      ["1. Eligibility (SLCC)", gates.gate1, (assessment.gate1 || {}).basis || "", "ITB 5.3; BDS 5.4, 5.5"],
      ["2. Delivery lead time", gates.gate2, (assessment.gate2 || {}).basis || "", "Section VI"],
      ["3. Data center compliance", gates.gate3, best ? `Recommended site ${rec}: ${countsText(best.counts)}.` : "", "Technical specifications; Site Fit sheet"],
    ];
    const fitRows = fits.map((f) => [f.site, f.fit, countsText(f.counts), f.gaps.slice(0, 6).map((x) => x.split(" ").slice(1).join(" ")).join(", ") || "-"]);
    const flags = (assessment.flags || []).map((f) => [f.flag, f.reference || "", "To assign", "Before bid decision"]);
    const openRows = [];
    if (rec) {
      const order = { Gap: 0, Clarify: 1, Partial: 2 };
      reqs.filter((r) => r.scope === "VITRO DC" && r.sites[rec] && r.sites[rec].rating in order)
        .sort((a, b) => order[a.sites[rec].rating] - order[b.sites[rec].rating]).slice(0, 10)
        .forEach((r) => { const sr = r.sites[rec]; openRows.push([r.clause || "", (r.text || "").slice(0, 90), sr.rating, r.clarification || sr.note || ""]); });
    }
    const sections = [
      { heading: "Gate Results", paragraphs: ["A Go needs all three gates to pass with cited evidence."],
        table: { headers: ["Gate", "Result", "Basis", "Reference"], widths: [2.2, 1.3, 4.2, 2.3], rows: gateRows, status_col: 1, source: src } },
      { heading: "Site Fit", paragraphs: ["Each VITRO data center requirement was rated for every site against the Specifications Table. One site must meet every requirement."],
        table: { headers: ["Site", "Fit", "Ratings", "Gap clauses"], widths: [2.0, 1.3, 4.0, 2.7], rows: fitRows, status_col: 1, source: src } },
    ];
    if (flags.length) sections.push({ heading: "Flags for Decision", table: { headers: ["Flag", "Reference", "Owner", "Needed by"], widths: [4.6, 2.6, 1.4, 1.4], rows: flags,
      source: "Source: bid documents and bulletins, as referenced in each row." } });
    if (openRows.length) sections.push({ heading: `Open Items at ${rec}`, table: { headers: ["Clause", "Requirement", "Rating", "What is needed"], widths: [1.2, 3.2, 1.1, 4.0],
      rows: openRows, status_col: 2, source: src + " Full list in the matrix (Open Items, Site Fit)." } });
    if (val.clarifications.length) sections.push({ heading: "Questions for the Procuring Entity",
      paragraphs: ["Raise these at the Pre-Bid Conference or in a written clarification before the deadline in the Instructions to Bidders; check the answers in the Supplemental/Bid Bulletin."],
      table: { headers: ["Ref", "Clause", "Area", "Question"], widths: [0.9, 1.3, 1.6, 6.2], rows: val.clarifications.map((q) => [q.id, q.clause, q.category, q.question]),
        source: "Source: requirements rated Clarify in the matrix. Drafts: review before sending." } });
    sections.push({ heading: "Next Steps", paragraphs: [
      "1. Confirm the gaps and clarifications above with Facilities and the bid lead.",
      "2. Fill the Reference Register rows the gates need (contracts, lead times, site distances, personnel) and run again.",
      "3. A reviewer signs off every matrix row before any compliance statement. Section VII treats false statements in the compliance form as fraud.",
      "4. Ratings and the recommended site are drafts produced by the bid qualification tool; the bid/no-bid decision rests with the bid lead."] });
    const d = today || new Date();
    return { iom_number: "[IOM number]", date: d.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "2-digit" }),
      to: "Head, Solutions", endorsed_by: "[Name]", from: owner,
      subject: `Bid / No-Bid and Site Fit: ${bid.procuring_entity || ""} ${bid.title || ""} (${bid.reference_no || ""})`, summary, sections };
  }

  // ------------------------------------------------------------ memo docx (build_memo.py)
  function fillMemo(JSZip, templateBuf, m, DOMParserCls, XMLSerializerCls) {
    return JSZip.loadAsync(templateBuf).then(async (zip) => {
      const xml = await zip.file("word/document.xml").async("string");
      const doc = new DOMParserCls().parseFromString(xml, "application/xml");
      const kids = (el, tag) => Array.from(el.childNodes).filter((n) => n.nodeType === 1 && n.namespaceURI === W && n.localName === tag);
      const kid = (el, tag) => kids(el, tag)[0] || null;
      const mk = (tag) => doc.createElementNS(W, "w:" + tag);
      const setAttr = (el, name, v) => el.setAttributeNS(W, "w:" + name, v);
      const child = (parent, tag, first) => {
        let el = kid(parent, tag);
        if (!el) { el = mk(tag); if (first && parent.firstChild) parent.insertBefore(el, parent.firstChild); else parent.appendChild(el); }
        return el;
      };
      const text = (el) => el.textContent || "";
      function setParText(p, t) {
        const runs = kids(p, "r");
        runs.slice(1).forEach((r) => p.removeChild(r));
        let r = runs[0];
        if (!r) { r = mk("r"); p.appendChild(r); }
        kids(r, "t").forEach((x) => r.removeChild(x));
        const te = mk("t"); te.setAttributeNS(XMLNS, "xml:space", "preserve"); te.textContent = t; r.appendChild(te);
        return r;
      }
      function setCell(tc, value, status) {
        const ps = kids(tc, "p");
        ps.slice(1).forEach((p) => tc.removeChild(p));
        const r = setParText(ps[0], value === null || value === undefined ? "" : String(value));
        const key = status && RATING_STATUS[status];
        if (key) {
          const [fg, fill] = STATUS[key];
          const tcPr = child(tc, "tcPr", true);
          const shd = child(tcPr, "shd");
          setAttr(shd, "val", "clear"); setAttr(shd, "color", "auto"); setAttr(shd, "fill", fill);
          const rPr = child(r, "rPr", true);
          ["color", "b"].forEach((t) => { const o = kid(rPr, t); if (o) rPr.removeChild(o); });
          rPr.appendChild(mk("b"));
          const c = mk("color"); setAttr(c, "val", fg); rPr.appendChild(c);
        }
      }
      const leftAlign = (tc) => kids(tc, "p").forEach((p) => { const pPr = kid(p, "pPr"); const jc = pPr && kid(pPr, "jc"); if (jc) pPr.removeChild(jc); });
      const keepNext = (p) => { const pPr = child(p, "pPr", true); if (!kid(pPr, "keepNext")) pPr.insertBefore(mk("keepNext"), pPr.firstChild); };
      const rowProps = (tr, header) => {
        const trPr = child(tr, "trPr", true);
        if (!kid(trPr, "cantSplit")) trPr.appendChild(mk("cantSplit"));
        if (header && !kid(trPr, "tblHeader")) trPr.appendChild(mk("tblHeader"));
      };
      function setWidths(tbl, fr) {
        const cols = kids(kid(tbl, "tblGrid"), "gridCol");
        const total = cols.reduce((s, c) => s + parseInt(c.getAttributeNS(W, "w") || c.getAttribute("w:w"), 10), 0);
        const sum = fr.reduce((a, b) => a + b, 0);
        const ws = fr.map((f) => Math.floor(total * f / sum));
        cols.forEach((c, i) => setAttr(c, "w", String(ws[i])));
        for (const tr of kids(tbl, "tr")) kids(tr, "tc").forEach((tc, i) => {
          if (i >= ws.length) return;
          const tcW = child(child(tc, "tcPr", true), "tcW", true); setAttr(tcW, "w", String(ws[i])); setAttr(tcW, "type", "dxa");
        });
      }
      function buildTable(proto, spec) {
        const tbl = proto.cloneNode(true);
        const trs = kids(tbl, "tr");
        const head = trs[0], a = trs[1], b = trs[2] || trs[1];
        trs.slice(1).forEach((tr) => tbl.removeChild(tr));
        rowProps(head, true);
        kids(head, "tc").forEach((tc, i) => { if (i < spec.headers.length) { setCell(tc, spec.headers[i]); kids(tc, "p").forEach(keepNext); } });
        spec.rows.forEach((row, i) => {
          const tr = (i % 2 === 0 ? a : b).cloneNode(true);
          kids(tr, "tc").forEach((tc, j) => { if (j < row.length) { leftAlign(tc); setCell(tc, row[j], j === spec.status_col ? row[j] : null); } });
          rowProps(tr); tbl.appendChild(tr);
        });
        if (spec.widths) setWidths(tbl, spec.widths);
        return tbl;
      }
      const body = doc.getElementsByTagNameNS(W, "body")[0];
      const els = Array.from(body.childNodes).filter((n) => n.nodeType === 1 && n.localName !== "sectPr");
      const iomP = els[1], headerTbl = els[2];
      const protos = { summary: els[4].cloneNode(true), heading: els[5].cloneNode(true), body: els[6].cloneNode(true),
        table: els[7].cloneNode(true), source: els[8].cloneNode(true) };
      const numRuns = kids(iomP, "r").filter((r) => /O000000|BDI-/.test(text(r)));
      if (numRuns.length) {
        const r0 = numRuns[0];
        kids(r0, "t").forEach((t) => r0.removeChild(t));
        const t = mk("t"); t.textContent = m.iom_number || "[IOM number]"; r0.appendChild(t);
        numRuns.slice(1).forEach((r) => iomP.removeChild(r));
      }
      const vals = [m.date, m.to, m.endorsed_by, m.from, m.subject];
      kids(headerTbl, "tr").forEach((tr, i) => { const tcs = kids(tr, "tc"); if (i < vals.length && tcs[1]) setCell(tcs[1], vals[i] || ""); });
      els.slice(4).forEach((e) => body.removeChild(e));
      const sect = kid(body, "sectPr");
      const add = (el) => body.insertBefore(el, sect);
      const p = protos.summary.cloneNode(true); setParText(p, m.summary); add(p);
      for (const s of m.sections) {
        const h = protos.heading.cloneNode(true); setParText(h, s.heading); keepNext(h); add(h);
        for (const para of s.paragraphs || []) { const b = protos.body.cloneNode(true); setParText(b, para); if (s.table) keepNext(b); add(b); }
        if (s.table) {
          add(buildTable(protos.table, s.table));
          const src = protos.source.cloneNode(true); setParText(src, s.table.source || "Source: [named source]."); add(src);
        }
      }
      zip.file("word/document.xml", new XMLSerializerCls().serializeToString(doc));
      return zip.generateAsync({ type: "uint8array", compression: "DEFLATE" });
    });
  }

  // ------------------------------------------------------------ matrix xlsx
  const MONO = "Consolas", SANS = "Aptos", DISPLAY = "Aptos Display";
  const thin = { style: "thin", color: { rgb: BORDER } };
  const GRID = { top: thin, bottom: thin, left: thin, right: thin };
  const sHead = { font: { name: MONO, bold: true, color: { rgb: WHITE }, sz: 10 }, fill: { patternType: "solid", fgColor: { rgb: COBALT } },
    alignment: { vertical: "center", wrapText: true }, border: GRID };
  const sBody = (alt, numeric) => ({ font: { name: MONO, sz: 10, color: { rgb: INK } }, fill: { patternType: "solid", fgColor: { rgb: alt ? ROW_ALT : SURFACE } },
    alignment: { vertical: "top", wrapText: true, horizontal: numeric ? "right" : "left" }, border: GRID });
  const sStatus = (label, alt) => {
    const key = RATING_STATUS[label]; const base = sBody(alt, false);
    if (!key) return base;
    const [fg, fill] = STATUS[key];
    return Object.assign({}, base, { font: { name: MONO, sz: 10, bold: true, color: { rgb: fg } }, fill: { patternType: "solid", fgColor: { rgb: fill } } });
  };
  const sEyebrow = { font: { name: SANS, bold: true, color: { rgb: COBALT }, sz: 9 } };
  const sTitle = { font: { name: DISPLAY, bold: true, color: { rgb: INK }, sz: 16 } };
  const sSource = { font: { name: SANS, italic: true, sz: 9, color: { rgb: INK_MUTED } } };
  const sNote = (bold) => ({ font: { name: SANS, sz: 10, color: { rgb: INK }, bold: !!bold }, alignment: { vertical: "top" } });

  function Sheet(XLSX) {
    const ws = {}; let maxR = 0, maxC = 0;
    const set = (r, c, v, s) => {
      if (v === null || v === undefined) v = "";
      const t = typeof v === "number" ? "n" : "s";
      ws[XLSX.utils.encode_cell({ r: r - 1, c: c - 1 })] = { v: t === "s" ? String(v) : v, t, s };
      maxR = Math.max(maxR, r); maxC = Math.max(maxC, c);
    };
    return {
      ws, set,
      title(text, eyebrow) { set(1, 1, eyebrow.toUpperCase(), sEyebrow); set(2, 1, text, sTitle); },
      source(r, text) { set(r, 1, text, sSource); },
      note(r, text, bold, c) { set(r, c || 1, text, sNote(bold)); },
      table(r, headers, rows, opts) {
        const o = opts || {};
        headers.forEach((h, j) => set(r, j + 1, h, sHead));
        rows.forEach((row, i) => row.forEach((v, j) => set(r + 1 + i, j + 1, v,
          (o.status || []).includes(j) && v ? sStatus(v, i % 2 === 1) : sBody(i % 2 === 1, (o.numeric || []).includes(j)))));
        return r + 1 + rows.length;
      },
      finish(widths, freeze) {
        ws["!ref"] = XLSX.utils.encode_range({ s: { r: 0, c: 0 }, e: { r: Math.max(maxR, 1) - 1, c: Math.max(maxC, 1) - 1 } });
        if (widths) ws["!cols"] = widths.map((w) => ({ wch: w }));
        if (freeze) ws["!freeze"] = freeze;
        return ws;
      },
    };
  }

  function buildMatrix(XLSX, { val, bid, assessment, reqs, specs, specName, registerName }) {
    const wb = XLSX.utils.book_new();
    const sites = specs.sites.map((s) => s.name);
    const rec = val.recommended_site;
    const src = `Source: uploaded bid documents; ${specName}; Reference Register ${registerName || "(none; blank register used)"}.`;

    // Summary
    let sh = Sheet(XLSX);
    sh.title(`${bid.procuring_entity || ""}: ${bid.title || ""}`, "Bid qualification");
    sh.source(3, "INTERNAL. Draft for Solutions review. Every rating needs reviewer sign-off before use.");
    sh.note(5, "Recommendation", true); sh.set(5, 2, val.verdict, sStatus(val.verdict, false));
    sh.note(6, "Best-fit site", true); sh.note(6, rec || "-", false, 2);
    let r = sh.table(8, ["Item", "Value"], [
      ["Reference No.", bid.reference_no || ""], ["Procuring Entity", bid.procuring_entity || ""],
      ["Approved Budget for the Contract (PHP)", typeof bid.abc_php === "number" ? bid.abc_php : "Not stated"],
      ["Bid Deadline", bid.bid_deadline || ""], ["Delivery Period", `${bid.delivery_days ?? ""} ${bid.delivery_basis || ""}`.trim()],
      ["SLCC Window (years)", bid.slcc_window_years ?? ""], ["Subcontracting", bid.subcontracting || ""], ["Documents reviewed", (bid.documents || []).join("; ")]]);
    sh.source(r, src); r += 2;
    r = sh.table(r, ["Gate", "Result", "Basis"], [
      ["1. Eligibility (SLCC)", val.gates.gate1, (assessment.gate1 || {}).basis || ""],
      ["2. Delivery lead time", val.gates.gate2, (assessment.gate2 || {}).basis || ""],
      ["3. Data center compliance", val.gates.gate3, rec ? `Best-fit site ${rec}` : ""]], { status: [1] });
    sh.source(r, src); r += 2;
    r = sh.table(r, ["Site", "Fit", "Comply", "Partial", "Clarify", "Unverified", "Gap", "Gap clauses"],
      val.site_fit.map((f) => [f.site, f.fit, f.counts.Comply || 0, f.counts.Partial || 0, f.counts.Clarify || 0, f.counts.Unverified || 0, f.counts.Gap || 0,
        f.gaps.map((x) => x.split(" ").slice(1).join(" ")).join(", ")]), { status: [1], numeric: [2, 3, 4, 5, 6] });
    sh.source(r, `Source: ${specName}. Ranked by gaps, then Comply count.`); r += 2;
    if ((assessment.flags || []).length) { r = sh.table(r, ["Flag", "Reference"], assessment.flags.map((f) => [f.flag, f.reference || ""])); sh.source(r, "Source: bid documents and bulletins."); }
    XLSX.utils.book_append_sheet(wb, sh.finish([38, 16, 60, 10, 10, 12, 8, 30]), "Summary");

    // Site Fit
    sh = Sheet(XLSX);
    sh.title("Site fit: every VITRO data center requirement for every site", "Bid qualification");
    sh.source(3, "Rating, then the evidence and note. Comply needs a Specifications Table cell for that site.");
    const dc = reqs.filter((q) => q.scope === "VITRO DC");
    const fitRows = dc.map((q) => [q.id, q.clause || "", q.category || "", q.amended_by ? `${q.text} [See ${q.amended_by}]` : q.text,
      ...sites.flatMap((s) => { const sr = q.sites[s] || {}; return [sr.rating || "", [(sr.evidence || []).join(", "), sr.note || "", (sr.checks || []).join("; ")].filter(Boolean).join(" | ")]; })]);
    r = sh.table(4, ["ID", "Clause", "Category", "Requirement", ...sites.flatMap((s) => [s, s + " evidence"])], fitRows,
      { status: sites.map((_, i) => 4 + 2 * i) });
    sh.source(r, src);
    XLSX.utils.book_append_sheet(wb, sh.finish([8, 10, 16, 60, ...sites.flatMap(() => [13, 40])], { xSplit: 4, ySplit: 4 }), "Site Fit");

    // Matrix
    sh = Sheet(XLSX);
    sh.title("Compliance matrix", "Bid qualification");
    sh.source(3, `VITRO DC rows show the best-fit site (${rec || "-"}). Reviewer columns are for sign-off.`);
    r = sh.table(4, ["ID", "Doc", "Page", "Clause", "Section", "Category", "Scope", "Mandatory", "Bulletin", "As Amended / Clarified", "Requirement",
      "Rating", "Evidence", "Rationale", "Checks", "Clarification Question", "Reviewer", "Signed off (Y/N)"],
      reqs.map((q) => [q.id, q.doc || "", q.page || "", q.clause || "", q.section || "", q.category || "", q.scope || "", q.mandatory === false ? "N" : "Y",
        q.amended_by || "", q.amended_text || "", q.text || "", q.rating || "", (q.evidence || []).join(", "), q.rationale || "", (q.checks || []).join("; "),
        q.clarification || "", "", ""]), { status: [11] });
    sh.source(r, src);
    XLSX.utils.book_append_sheet(wb, sh.finish([8, 12, 6, 10, 18, 15, 15, 10, 18, 44, 60, 13, 22, 44, 30, 40, 14, 10], { xSplit: 1, ySplit: 4 }), "Matrix");

    // Open items
    sh = Sheet(XLSX);
    sh.title("Open items", "Bid qualification");
    sh.source(3, "VITRO DC and Bidder (general) requirements not yet rated Comply. Gaps first.");
    const order = { Gap: 0, Clarify: 1, Partial: 2, Unverified: 3 };
    const items = reqs.filter((q) => ["VITRO DC", "Bidder (general)"].includes(q.scope) && q.rating in order)
      .sort((a, b) => order[a.rating] - order[b.rating] || String(a.category).localeCompare(String(b.category)) || a.id.localeCompare(b.id));
    r = sh.table(4, ["ID", "Clause", "Category", "Requirement", "Rating", "What is needed"],
      items.map((q) => [q.id, q.clause || "", q.category || "", q.text || "", q.rating, q.clarification || q.rationale || ""]), { status: [4] });
    sh.source(r, src);
    XLSX.utils.book_append_sheet(wb, sh.finish([8, 10, 16, 70, 13, 60], { ySplit: 4 }), "Open Items");

    // Clarifications
    sh = Sheet(XLSX);
    sh.title("Questions for the procuring entity", "Bid qualification");
    sh.source(3, "Raise at the Pre-Bid Conference or by written clarification. Drafts: review before sending.");
    r = sh.table(4, ["ID", "Document", "Clause", "Category", "Question"], val.clarifications.map((q) => [q.id, q.doc, q.clause, q.category, q.question]));
    sh.source(r, "Source: requirements rated Clarify.");
    XLSX.utils.book_append_sheet(wb, sh.finish([8, 16, 10, 16, 90]), "Clarifications");

    return XLSX.write(wb, { type: "array", bookType: "xlsx" });
  }

  const BQDocs = { buildMemoJson, fillMemo, buildMatrix, RATING_STATUS };
  if (typeof module !== "undefined" && module.exports) module.exports = BQDocs;
  else root.BQDocs = BQDocs;
})(typeof window !== "undefined" ? window : globalThis);
