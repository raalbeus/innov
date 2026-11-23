# bid-qualify: setup and maintenance

INTERNAL. For the VITRO Solutions team.

## What it does
Upload a Philippine government bid package to Claude and run `/bid-qualify` (or ask "should we bid on
this?"). Claude reads every document, including scanned annexes, applies bid bulletin amendments,
checks three gates (SLCC eligibility, delivery lead time, data center compliance), rates every data
center requirement for every VITRO site against the VITRO Specifications Table, and returns:
- `<Entity>_<Project>_Matrix.xlsx`: site ranking, a site-by-requirement grid, and every requirement
  with clause, page, scope, bulletin changes, draft rating, evidence and reviewer sign-off columns.
- `<Entity>_<Project>_GoNoGo.docx`: the inter-office memo with the recommendation first.

Ratings are drafts. A reviewer signs off each row before any compliance statement is made.

## Install (claude.ai)
1. Zip the `bid-qualify` folder (the zip must contain the folder, with `SKILL.md` inside it).
2. In claude.ai: Settings > Capabilities > Skills > Upload skill, and select the zip.
   An organization admin can add it for the whole team instead.
3. Code execution must be on (Settings > Capabilities), because the skill runs Python scripts.
4. Connect the **Microsoft 365** connector (claude.ai > Customize > Connectors) so Claude can read the
   Specifications Table and register from SharePoint.
5. Set the SharePoint location of the Specifications Table in `SKILL.md` (Inputs, item 2), then zip and
   upload again.

## The VITRO Specifications Table
The facility evidence for every site (power, cooling, ratings, certifications, security, racks,
connectivity, SLAs, office rental). Keep the current version on SharePoint; the skill reads the latest
file each run and cites its file name and date. Symbol legend: n or ● available, q not available,
i optional, - not applicable. A blank cell counts as unverified, so fill cells for every site.

## The VITRO Reference Register
`templates/VITRO_Reference_Register.xlsx` holds what the Specifications Table lacks: Contracts (SLCC),
DR Seats & Office, Site Distances, Personnel and Lead Times. Without it, SLCC, delivery, distance and
personnel checks come back `Unverified` and the recommendation is "Insufficient evidence".
- Fill one row per contract, DR seat block, measured site distance, certified role and standard lead
  time. Each row needs a Source Document and an As-of Date. Site names must match the Specifications
  Table exactly (e.g. "VITRO Clark").
- Keep the filled copy next to the Specifications Table on SharePoint, not inside the skill: it holds
  contract values and client names.
- Rows older than 180 days are marked stale; expired certificates are rejected automatically.
- Suggested owners: Contracts (Contracts), Facilities (DR Seats & Office, Site Distances), HR
  (Personnel), Delivery (Lead Times).

## Files
| Path | Purpose |
|---|---|
| `SKILL.md` | Instructions Claude follows |
| `references/process.md` | The three gates, where things are in the bid documents, verdict rules |
| `references/schema.md` | JSON formats between steps |
| `scripts/extract_bid.py` | Per-page text and images of scanned pages; locates key sections |
| `scripts/read_specs.py` | Reads the Specifications Table into SPEC-<row> evidence per site |
| `scripts/check_gates.py` | SLCC thresholds and window; delivery vs lead times |
| `scripts/build_matrix.py` | Checks every citation against the spec cell per site, ranks sites, computes the verdict, writes the Excel matrix |
| `scripts/build_memo.py` | Fills the inter-office memo template |
| `scripts/make_register.py` | Regenerates the blank register |
| `templates/VITRO_Memo_Template.docx` | Copy of the memo template from the vitro-templates skill |

The memo template is a copy. When the vitro-templates skill updates it, replace this copy.

## Not in version 1
- Drafting the written clarification letter to the Bids and Awards Committee.
- Comparing a new bulletin against an earlier matrix and re-rating only the changed rows.
