---
name: bid-qualify
description: Qualify a Philippine government bid (PhilGEPS / Philippine Bidding Documents) for VITRO Data Centers and find the best-fit VITRO site. Use when the user uploads or links bid documents, a Terms of Reference (TOR), technical specifications, annexes or bid bulletins and asks whether VITRO should bid, which site to offer, to check eligibility or Single Largest Completed Contract (SLCC), delivery lead time, or data center compliance (colocation, DR seats, office space, connectivity, ISO/TIA-942 certifications, personnel), or to build a compliance matrix or Go/No-Go memo. Also /bid-qualify.
---

# Bid qualification and site fit (Go/No-Go)

Produces two internal files for the Solutions team:
1. **Compliance matrix** (`<Entity>_<Project>_Matrix.xlsx`): Summary (gates, verdict, site ranking),
   Site Fit (every VITRO data center requirement rated for every site, evidence in cell comments),
   Matrix (every requirement with clause, page, bulletin changes and reviewer sign-off), Open Items,
   Evidence.
2. **Go/No-Go memo** (`<Entity>_<Project>_GoNoGo.docx`): the VITRO inter-office memo with the
   recommendation and the recommended site first.

Read `references/process.md` (gates, where things are in bid documents, verdict rules) and
`references/schema.md` (JSON formats, rating guide) before starting. Scripts are in `scripts/`; run
them from that folder.

## Inputs
1. **Bid package** (required): the bidding documents, every annex, every bid bulletin / Supplemental
   Bid Bulletin (SBB), and any clarification letters.
2. **VITRO Specifications Table** (required): the facility evidence for all sites.
   - **Source: SharePoint**, location: `[SharePoint site / library / path to be set by the Solutions team]`.
     Use the Microsoft 365 connector to find and download the latest version of
     `VITRO_Specifications_Table_*.xlsx` from that location. Record the file name and its
     last-modified date.
   - If the connector is not available in this session or the file cannot be found, ask the user to
     upload the file. Do not proceed on an older copy without saying which version you used.
3. **VITRO Reference Register** (`.xlsx`, recommended): holds only what the Specifications Table
   lacks: Contracts (SLCC), DR Seats & Office, Site Distances, Personnel, Lead Times. Template in
   `templates/`. Look for it next to the Specifications Table on SharePoint, else ask once. Without it
   those items are `Unverified`.
Never fill gaps from memory or general knowledge about VITRO or its sites.

## Procedure
1. **Extract the bid.** `python3 extract_bid.py <work> <all bid PDFs>`. Read `<work>/manifest.md`:
   it lists scanned pages (images in `<doc>/img/`) and the pages where key terms appear.
2. **Read the specifications.** `python3 read_specs.py <spec.xlsx> <work>/specs`. Read
   `<work>/specs/specs.md` in full: one line per spec row (`SPEC-<row>`) with every site's value.
3. **Read the core bid terms** from the text pages: ABC, deadline, SLCC rule and window,
   similar-contract definition, subcontracting and joint venture rules, delivery period.
4. **Read the technical requirements in full.** Text pages from `<doc>/text/`, scanned pages by
   viewing every image in `<doc>/img/`. Do not skip or sample. For a long scanned annex (more than
   about 15 pages), split pages across parallel subagents if available, giving each the Field rules
   and Granularity from `references/schema.md`; then merge and remove duplicates across page breaks.
5. **Apply bulletins.** Set `amended_by` and `amended_text` on each row a bulletin item amends or
   clarifies; add rows for new requirements. Match by exact clause number; apply an item that cites a
   parent clause only to the sub-clauses it discusses, never to a whole section. List each item once.
6. **Rate.**
   - `VITRO DC` rows: fill `sites` for **every site** with rating, SPEC evidence and a short note,
     following the Site rating guide in `references/schema.md`. For more than about 40 rows, split
     rows across parallel subagents, each given `specs.md` and the rating guide.
   - `Bidder (general)` rows: `rating` with register evidence.
   - `Partner` rows: `Partner scope`.
   - Ambiguous requirements: `Clarify` with a drafted question.
   - Add `assessment.flags` (subcontracting, location rules, deadline, commercial terms).
7. **Gates 1 and 2.** `python3 check_gates.py --register <reg.xlsx> --abc <ABC> --deadline <YYYY-MM-DD>
   --slcc-years <N> --delivery-days <N> [--lead-times LT-..] [--exclude-recurring] --out <work>/gates.json`.
   Without a register, pass a copy of the blank template. Judge SLCC similarity for the candidates
   it lists and put the result in `assessment.gate1`; likewise `gate2`.
8. **Build the matrix.** `python3 build_matrix.py --requirements <work>/requirements.json --gates
   <work>/gates.json --specs <work>/specs/specs.json --register <reg.xlsx> --out <Matrix.xlsx>
   --validated <work>/validated.json`. It checks every citation against the spec cell for that site,
   downgrades unsupported ratings, ranks the sites, and computes Gate 3 and the verdict. Use the
   validated results from here on, including `recommended_site` and `site_fit`.
9. **Write the memo.** Write `memo.json` (format in `references/schema.md`) and run
   `python3 build_memo.py <work>/memo.json <GoNoGo.docx>`. Structure:
   - Summary: the recommendation, the recommended site and the main reason, in two sentences.
   - Gate Results: Gate | Result | Basis | Reference (`status_col` 1).
   - Site Fit: Site | Fit | Deciding requirements | Reference (`status_col` 1). Top sites, plus one
     line on why the others drop out (the hard filters).
   - Flags for Decision: Flag | Reference | Owner | Needed by.
   - Open Items: the gaps and clarifications at the recommended site (top 10):
     Clause | Requirement | Rating | What is needed (`status_col` 2).
   - Next Steps: who confirms what, by when (by role or title).
   Every table gets a source line naming the bid documents, the Specifications Table file and date,
   and the register.
10. **Check** before handing over: confirm the workbook row counts match the JSON; render the memo
    to PDF with LibreOffice if available and view it; confirm no placeholder text remains.

## Rules
- **Evidence or nothing.** Comply needs a cited spec cell or register row that proves it. Blank cells
  are Unverified, never Comply. Never infer one site from another. Never estimate figures,
  distances or amounts; if a number cannot be sourced, leave it out and say so. Capacity figures state
  their basis (for example "Rack Capacity (Ready), Specifications Table row 15").
- **Cite the bid.** Every requirement carries document, page and clause.
- **People decide.** The verdict and site are recommendations. A reviewer signs off each row. The
  procuring entity treats false compliance statements as fraud (Section VII): say so in Next Steps.
- **Confidential.** The Specifications Table includes capacity at full build ("Ultimate"), sites not
  yet public and customer profiles. Outputs are INTERNAL. Do not put forward capacity, unannounced
  sites, REIT matters or customer names into anything meant for the procuring entity. External
  letters need the bid lead's clearance and go out as PDF.
- **Do not assess** pricing, legal terms or government positions; list them as flags.
- **House style.** VITRO design system (claude.ai/artifact/UBDmvNqfp3bg7WHjLa9EvX): the scripts apply
  it. Lead with the conclusion. No em dashes. Define acronyms on first use. Executives by title.
