/* VITRO bid qualification: reading the bid package with Claude from the page (claude.use("sample")).
 * Port of app/ai.py (prompts) and app/pipeline.ai_steps. Each call is memoryless: instructions, page text and
 * scanned-page images go in every call. Answers are cached for 24 h, so running again after a failure reuses
 * the parts that already finished.
 */
(function (root) {
  "use strict";
  const BQ = root.BQ;
  const CATEGORIES = ["Eligibility", "Delivery", "Colocation", "DR seats", "Office space", "Connectivity", "Facility rating",
    "Certifications", "Personnel", "Security", "Service levels", "Commercial", "Other"];
  const SCOPES = ["VITRO DC", "Bidder (general)", "Partner"];
  const SITE_RATINGS = ["Comply", "Partial", "Gap", "Clarify", "Unverified"];
  const PAGES_PER_CALL = 8, RATE_BATCH = 15, POOL = 2, MIN_TEXT_CHARS = 80;
  const CACHE = { gcTime: 24 * 3600 * 1000 };

  const TERMS = `You read Philippine government bidding documents (Philippine Bidding Documents under
RA 12009) for VITRO Data Centers. Extract the bid's core terms exactly as written.
- abc_php: the Approved Budget for the Contract in PHP as a number; null if not stated.
- bid_deadline: deadline for submission of bids as YYYY-MM-DD (use the latest bulletin if it moves it); "" if not stated.
- delivery_days: delivery or implementation period in calendar days (Section VI); null if not stated.
- slcc_window_years: years before the deadline within which the SLCC must have been completed (BDS 5.4); null if not stated.
- slcc_rule and similar_definition: quote the BDS / ITB text (similar contract definition is usually BDS 5.5).
- subcontracting (BDS 8.1) and joint_venture: "Allowed", "Not allowed" or "Not stated".
- slcc_excludes_ongoing_recurring: true only if a bulletin or the BDS says contracts with ongoing recurring
  services under the same agreement do not count as completed.
- source_pages: where you found these (document and page).
- flags: decision points for the bid lead: deadline already passed or close, subcontracting restrictions,
  location or distance rules for the facility, third-party certification demands, payment or warranty terms
  that change cost, personnel headcount rules. One sentence each with a document/clause reference.
Never estimate a number. Use "" or null when the documents do not state it.`;
  const TERMS_SHAPE = `{"bid": {"title": "", "procuring_entity": "", "reference_no": "", "abc_php": 0, "bid_deadline": "YYYY-MM-DD", "delivery_days": 0,
 "delivery_basis": "", "slcc_window_years": 0, "slcc_rule": "", "similar_definition": "", "subcontracting": "Allowed|Not allowed|Not stated",
 "joint_venture": "Allowed|Not allowed|Not stated", "slcc_excludes_ongoing_recurring": false, "source_pages": ""},
 "flags": [{"flag": "", "reference": ""}]}`;

  const REQ = `You extract requirements from the technical specifications / Terms of Reference of a
Philippine government tender, for VITRO Data Centers (a colocation data center operator).
Return every requirement on the pages given. Rules:
- doc: the document name given; page: the page number in the label; clause: as printed; section: nearest heading.
- text: verbatim where short, tightly paraphrased if long; keep every number, quantity, standard and duration.
- category: one of ${CATEGORIES.join(", ")}.
- scope: "VITRO DC" for anything the data center facility or its services deliver (co-location, racks, cage,
  power, cooling, generators, UPS, fire suppression, building management, facility rating/TIA-942, physical
  security, DR seats, office/work area at the facility, carrier and internet connectivity into the facility,
  remote hands, facility certifications, DC staff credentials, DC SLAs).
  "Bidder (general)" for company-level obligations (eligibility, project team, warranty, training, general SLAs).
  "Partner" for equipment, software, licences and integration work VITRO would source from a partner.
- Granularity: one row per obligation clause for VITRO DC and Bidder (general); one row per equipment or
  software item for Partner (summarise its key specs). Headings without an obligation are not rows.
- If text is illegible, include the row with text "[illegible]" rather than guessing.`;
  const REQ_SHAPE = `{"requirements": [{"doc": "", "page": 1, "clause": "", "section": "", "text": "", "category": "", "scope": "VITRO DC|Bidder (general)|Partner", "mandatory": true}]}`;

  const BULLETIN = `You read a bid bulletin / Supplemental Bid Bulletin issued by a Philippine procuring
entity. Return one object per numbered query/resolution item.
- clauses: the TOR / Annex clause numbers the item refers to, as printed (e.g. "4.4.2.4"); BDS/ITB items as "BDS 5.4".
- resolution: the answer, verbatim if under about 60 words, else tightly paraphrased keeping all numbers.
- effect: Amends requirement / Clarifies requirement / No change / Administrative.
- note: anything material for a data center operator (colocation, racks, cage, DR seats, office, connectivity,
  facility certification, SLCC eligibility, delivery timeline, personnel), else "".
The two-column layout interleaves question and answer text; read carefully.`;
  const BULLETIN_SHAPE = `{"items": [{"item": "", "page": 1, "clauses": [""], "query": "", "resolution": "", "effect": "Amends requirement|Clarifies requirement|No change|Administrative", "note": ""}]}`;

  const RATE = `You rate tender requirements for VITRO Data Centers against VITRO's own evidence.
The ONLY evidence allowed is the VITRO Specifications Table and the VITRO Reference Register below. Do not use
general knowledge about VITRO, its sites, products or standards. Never infer one site from another. Never
estimate distances, capacities or amounts.

For each requirement with scope "VITRO DC", rate EVERY site listed, citing SPEC ids (and register ids such as
DIST-001 or SEAT-001 where relevant):
- Comply: the site's cell clearly meets the requirement. "Optional" means the service can be provided.
- Partial: meets part of it, or the cell says "Negotiable", or the requirement has parts the spec does not cover.
- Gap: the cell explicitly fails (Not available, "No", or a value below the requirement).
- Unverified: no spec row or register row on the topic, or the site's cell is blank. evidence = [].
- Clarify: the requirement itself is ambiguous, internally inconsistent, contradicts a bulletin answer, or is
  missing a figure (e.g. a recovery time with no number). Use it for every site unless that site is a Gap,
  and write the question in clarification.
For "Bidder (general)" requirements, give one rating with register evidence (most are Unverified unless the
register shows proof); leave "sites" empty. Use the requirement's bulletin text where given: it overrides.
note: 25 words or fewer, factual, naming the spec value. rationale: one sentence. clarification: the
question to ask when rating is Clarify, else "".`;
  const RATE_SHAPE = `{"ratings": [{"id": "R-001", "sites": [{"site": "", "rating": "Comply|Partial|Gap|Clarify|Unverified", "evidence": ["SPEC-12"], "note": ""}],
 "rating": "Comply|Partial|Gap|Clarify|Unverified", "evidence": [], "rationale": "", "clarification": ""}]}`;

  const jsonAsk = (shape) => `\n\nReply with only one JSON object of this shape (no prose before or after):\n${shape}`;
  const utf8 = (s) => new TextEncoder().encode(s).length;

  // ------------------------------------------------------------ PDF reading
  async function readPdf(pdfjsLib, file, onPage) {
    const buf = await file.arrayBuffer();
    const pdf = await pdfjsLib.getDocument({ data: buf, isEvalSupported: false }).promise;
    const pages = [];
    for (let i = 1; i <= pdf.numPages; i++) {
      const page = await pdf.getPage(i);
      const tc = await page.getTextContent();
      let text = "";
      for (const it of tc.items) { text += it.str; text += it.hasEOL ? "\n" : " "; }
      text = text.replace(/[ \t]+\n/g, "\n").trim();
      let image = null;
      if (text.replace(/\s/g, "").length < MIN_TEXT_CHARS) {
        const vp = page.getViewport({ scale: 110 / 72 });
        const canvas = document.createElement("canvas");
        canvas.width = Math.ceil(vp.width); canvas.height = Math.ceil(vp.height);
        const ctx = canvas.getContext("2d");
        ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, canvas.width, canvas.height);
        await page.render({ canvasContext: ctx, viewport: vp }).promise;
        image = await new Promise((res) => canvas.toBlob(res, "image/jpeg", 0.82));
        canvas.width = canvas.height = 0;
      }
      pages.push({ n: i, text, image });
      page.cleanup();
      if (onPage) onPage(i, pdf.numPages);
    }
    await pdf.destroy();
    const first = pages.slice(0, 3).map((p) => p.text).join("\n");
    const doc = { file: file.name, pages, type: BQ.docType(file.name, first), scanned: pages.filter((p) => p.image).map((p) => p.n) };
    doc.hits = BQ.hits(pages.map((p) => p.text));
    return doc;
  }

  /** Group page numbers into calls: up to PAGES_PER_CALL pages and at most maxImages scanned pages each. */
  function groupPages(doc, nums, maxImages) {
    const out = []; let cur = [], imgs = 0;
    for (const n of nums) {
      const p = doc.pages[n - 1]; if (!p) continue;
      const isImg = !!p.image;
      if (cur.length && (cur.length >= PAGES_PER_CALL || (isImg && imgs >= maxImages))) { out.push(cur); cur = []; imgs = 0; }
      cur.push(n); if (isImg) imgs++;
    }
    if (cur.length) out.push(cur);
    return out;
  }

  function pageBlock(doc, nums) {
    let text = "", images = [], imgLabels = [];
    for (const n of nums) {
      const p = doc.pages[n - 1];
      const label = `${doc.file} page ${n}`;
      if (p.image) { text += `\n--- ${label} (scanned: see attached image ${images.length + 1}) ---\n`; images.push(p.image); imgLabels.push(label); }
      else text += `\n--- ${label} ---\n${p.text}\n`;
    }
    return { text, images, imgLabels };
  }

  // ------------------------------------------------------------ calling Claude
  const FATAL = ["not_granted", "rate_limited", "session_expired", "sampling_disabled", "not_declared", "capability_disabled",
    "capability_removed", "images_unavailable", "queue_overflow"];
  const ERR_COPY = {
    not_granted: "Claude was not allowed for this page. Reload and choose Allow when asked.",
    rate_limited: "Your Claude usage limit was reached. Wait, then run again: finished parts are reused.",
    session_expired: "Your claude.ai session expired. Sign in again and reload the page.",
    sampling_disabled: "Claude is turned off for this page or organization. Ask the page owner.",
    capability_disabled: "Claude is turned off for this page or organization. Ask the page owner.",
    images_unavailable: "This view cannot send scanned pages to Claude. Open the page in claude.ai in a browser.",
    queue_overflow: "Too many requests at once. Wait a minute and run again.",
    refused: "Claude declined to read this part.", invalid_json: "Claude's answer for this part could not be read.",
    prompt_too_large: "This part was too large to send.", upstream_error: "Claude had a temporary problem with this part.",
    empty_completion: "Claude returned an empty answer for this part.", cancelled: "Stopped.",
  };

  function makeRunner(sample, limits, signal, log) {
    const maxBytes = (limits && limits.maxPromptBytes) || 262144;
    let fatal = null;
    async function ask(label, prompt, images) {
      if (fatal) throw fatal;
      if (signal.aborted) throw { code: "cancelled" };
      if (utf8(prompt) > maxBytes - 2048) throw { code: "prompt_too_large", label };
      const opts = { modelTier: "default", cache: CACHE, signal };
      if (images && images.length) opts.images = images;
      try { return await sample.json(prompt, opts); }
      catch (e) {
        const err = { code: (e && e.code) || "upstream_error", label };
        if (FATAL.includes(err.code)) fatal = err;
        throw err;
      }
    }
    async function pool(tasks, onDone) {
      const results = new Array(tasks.length), failures = [];
      let next = 0, done = 0;
      async function worker() {
        while (next < tasks.length) {
          const i = next++;
          try { results[i] = await tasks[i](); }
          catch (e) { if (e.code === "cancelled" || fatal) { next = tasks.length; } else { failures.push(e); log(`Skipped: ${e.label} (${ERR_COPY[e.code] || e.code})`); } }
          done++; onDone(done, tasks.length);
        }
      }
      await Promise.all(Array.from({ length: Math.min(POOL, tasks.length) }, worker));
      if (signal.aborted) throw { code: "cancelled" };
      if (fatal) throw fatal;
      return { results, failures };
    }
    return { ask, pool };
  }

  // ------------------------------------------------------------ normalising answers
  const str = (v) => (v === null || v === undefined ? "" : String(v));
  const pick = (v, list, dflt) => (list.includes(v) ? v : dflt);
  function normReq(x, doc) {
    if (!x || typeof x !== "object" || !str(x.text)) return null;
    return { doc: str(x.doc) || doc, page: parseInt(x.page, 10) || 0, clause: str(x.clause), section: str(x.section), text: str(x.text),
      category: pick(x.category, CATEGORIES, "Other"), scope: pick(x.scope, SCOPES, "Bidder (general)"), mandatory: x.mandatory !== false };
  }

  // ------------------------------------------------------------ the whole read
  /** docs: from readPdf. specs: readSpecs output. regDigest: text. Returns {terms, reqs, failures}. */
  async function qualify({ sample, limits, signal, docs, specs, specsMd, regDigest, progress, log }) {
    const maxImages = Math.max(1, Math.min(6, (limits && limits.images && limits.images.maxCount) || 0));
    const R = makeRunner(sample, limits, signal, log);
    const failures = [];
    const by = (t) => docs.filter((d) => d.type === t);

    // terms
    progress("terms", 0, 1, "Reading the bid terms");
    const termPages = [];
    for (const d of by("Bidding documents (PBD)").concat(by("Other"))) {
      const want = new Set(); for (let i = 1; i <= Math.min(3, d.pages.length); i++) want.add(i);
      for (const k of ["Bid Data Sheet (BDS)", "SLCC / similar contract", "Schedule of Requirements (Sec VI)", "Deadline / bid opening", "NFCC / credit line"])
        (d.hits[k] || []).slice(0, 6).forEach((p) => want.add(p));
      termPages.push([d, [...want].sort((a, b) => a - b).slice(0, 30)]);
    }
    for (const d of by("Bid Bulletin / SBB")) {
      const want = new Set([1, 2, d.pages.length, ...(d.hits["SLCC / similar contract"] || []), ...(d.hits["Deadline / bid opening"] || [])]);
      termPages.push([d, [...want].filter((p) => p >= 1 && p <= d.pages.length).sort((a, b) => a - b).slice(0, 12)]);
    }
    let tText = "", tImgs = [];
    for (const [d, nums] of termPages) { const b = pageBlock(d, nums); tText += b.text; tImgs = tImgs.concat(b.images); }
    tImgs = tImgs.slice(0, maxImages);
    let terms;
    try {
      terms = await R.ask("bid terms", TERMS + "\n\n=== BID DOCUMENT PAGES ===" + tText + "\n\nExtract the bid terms and flags." + jsonAsk(TERMS_SHAPE), tImgs);
    } catch (e) { if (e.code === "cancelled" || FATAL.includes(e.code)) throw e; failures.push(e); terms = { bid: {}, flags: [] }; log("Skipped: bid terms"); }
    const b = Object.assign({ title: "", procuring_entity: "", reference_no: "", abc_php: null, bid_deadline: "", delivery_days: null, delivery_basis: "",
      slcc_window_years: null, slcc_rule: "", similar_definition: "", subcontracting: "Not stated", joint_venture: "Not stated", slcc_excludes_ongoing_recurring: false }, terms.bid || {});
    b.abc_php = BQ.asNum(b.abc_php); b.delivery_days = b.delivery_days === null ? null : parseInt(b.delivery_days, 10) || null;
    b.slcc_window_years = b.slcc_window_years === null ? null : parseInt(b.slcc_window_years, 10) || null;
    terms = { bid: b, flags: (terms.flags || []).filter((f) => f && f.flag).map((f) => ({ flag: str(f.flag), reference: str(f.reference) })) };
    progress("terms", 1, 1, "Read the bid terms");

    // requirements
    // TOR / annexes, plus unclassified documents (often a scanned annex whose file name does not say "Annex")
    let targets = by("TOR / Annex").concat(by("Other")).map((d) => [d, d.pages.map((p) => p.n)]);
    if (!targets.length) targets = by("Bidding documents (PBD)").map((d) => [d, [...new Set([...(d.hits["Technical Specifications (Sec VII)"] || []),
      ...(d.hits["Schedule of Requirements (Sec VI)"] || [])])].filter((p) => p > 5).sort((a, b) => a - b)]);
    const reqCalls = [];
    for (const [d, nums] of targets) for (const g of groupPages(d, nums, maxImages)) reqCalls.push([d, g]);
    const reqRes = await R.pool(reqCalls.map(([d, g]) => () => {
      const blk = pageBlock(d, g), name = BQ.shortDoc(d.file);
      return R.ask(`${name} pages ${g[0]}-${g[g.length - 1]}`, REQ + "\n\n=== PAGES ===" + blk.text +
        `\n\nDocument name: "${name}". Extract every requirement on these pages.` + jsonAsk(REQ_SHAPE), blk.images)
        .then((r) => (r && r.requirements || []).map((x) => normReq(x, name)).filter(Boolean));
    }), (i, n) => progress("requirements", i, n, `Reading technical requirements (${i}/${n})`));
    failures.push(...reqRes.failures);
    let rows = BQ.mergeRequirements([].concat(...reqRes.results.filter(Boolean)));
    const fixed = [{ doc: "Bidding Documents", page: 0, clause: "BDS 5.4/5.5; ITB 5.3", section: "Eligibility", category: "Eligibility",
      scope: "Bidder (general)", mandatory: true, text: `Single Largest Completed Contract (SLCC): ${b.slcc_rule || ""} Similar contract: ${b.similar_definition || ""}`.trim() }];
    if (b.delivery_days) fixed.push({ doc: "Bidding Documents", page: 0, clause: "Sec VI", section: "Schedule of Requirements", category: "Delivery",
      scope: "Bidder (general)", mandatory: true, text: `Delivery within ${b.delivery_days} ${b.delivery_basis || "calendar days"}.` });
    rows = fixed.concat(rows);

    // bulletins
    const bCalls = [];
    for (const d of by("Bid Bulletin / SBB")) for (const g of groupPages(d, d.pages.map((p) => p.n), maxImages)) bCalls.push([d, g]);
    const bRes = await R.pool(bCalls.map(([d, g]) => () => {
      const blk = pageBlock(d, g);
      return R.ask(`${BQ.shortDoc(d.file)} pages ${g[0]}-${g[g.length - 1]}`, BULLETIN + "\n\n=== PAGES ===" + blk.text +
        "\n\nExtract every bulletin item on these pages. An item cut off at a page boundary: include what is visible." + jsonAsk(BULLETIN_SHAPE), blk.images)
        .then((r) => (r && r.items || []).filter((x) => x && x.item !== undefined).map((x) => ({ item: str(x.item), page: parseInt(x.page, 10) || 0,
          clauses: Array.isArray(x.clauses) ? x.clauses.map(str) : [], query: str(x.query), resolution: str(x.resolution),
          effect: pick(x.effect, ["Amends requirement", "Clarifies requirement", "No change", "Administrative"], "No change"), note: str(x.note) })));
    }), (i, n) => progress("bulletins", i, n, `Reading bid bulletins (${i}/${n})`));
    failures.push(...bRes.failures);
    const items = Object.values([].concat(...bRes.results.filter(Boolean)).reduce((m, x) => ((m[x.item + "|" + x.page] = x), m), {}));
    BQ.applyBulletins(rows, items);
    rows.forEach((r, i) => (r.id = "R-" + String(i + 1).padStart(3, "0")));

    // ratings
    const sites = specs.sites.map((s) => s.name);
    const head = RATE + "\n\n=== VITRO SPECIFICATIONS TABLE ===\n" + specsMd + "\n\n=== VITRO REFERENCE REGISTER ===\n" + (regDigest || "(empty)");
    const toRate = rows.filter((r) => r.scope === "VITRO DC" || r.scope === "Bidder (general)");
    const batches = BQ.chunks(toRate, RATE_BATCH);
    const rRes = await R.pool(batches.map((batch) => () => {
      const payload = batch.map((r) => ({ id: r.id, clause: r.clause, category: r.category, scope: r.scope, requirement: r.text, bulletin: r.amended_text || "" }));
      return R.ask(`ratings ${batch[0].id}-${batch[batch.length - 1].id}`, head + "\n\nSites: " + sites.join(", ") + "\n\nRequirements:\n" +
        JSON.stringify(payload, null, 1) + jsonAsk(RATE_SHAPE)).then((r) => (r && r.ratings) || []);
    }), (i, n) => progress("ratings", i, n, `Rating each site (${i}/${n})`));
    failures.push(...rRes.failures);
    const rated = {}; for (const x of [].concat(...rRes.results.filter(Boolean))) if (x && x.id) rated[x.id] = x;
    for (const r of rows) {
      const x = rated[r.id];
      if (r.scope === "Partner") { r.rating = "Partner scope"; continue; }
      if (!x) { r.rating = "Unverified"; r.rationale = "Not rated."; continue; }
      r.clarification = str(x.clarification);
      if (r.scope === "VITRO DC") {
        r.sites = {};
        for (const s of x.sites || []) if (s && sites.includes(s.site))
          r.sites[s.site] = { rating: pick(s.rating, SITE_RATINGS, "Unverified"), evidence: (s.evidence || []).map(str), note: str(s.note) };
      } else {
        r.rating = pick(x.rating, SITE_RATINGS, "Unverified"); r.evidence = (x.evidence || []).map(str); r.rationale = str(x.rationale);
      }
    }
    return { terms, reqs: rows, failures, bulletinItems: items };
  }

  root.BQAI = { readPdf, qualify, groupPages, ERR_COPY, FATAL };
})(typeof window !== "undefined" ? window : globalThis);
