# Data formats

## requirements.json (input to `build_matrix.py`)

```json
{
  "bid": {
    "title": "Business Continuity Facility",
    "procuring_entity": "Bureau of Immigration",
    "reference_no": "BI-CB-2026-090",
    "abc_php": 525525000.00,
    "bid_deadline": "2026-11-25",
    "delivery_days": 270,
    "delivery_basis": "calendar days from receipt of Notice to Proceed (Sec VI)",
    "slcc_window_years": 10,
    "slcc_rule": "50% of ABC, or 25% similar + 25% aggregate (ITB 5.3, BDS)",
    "similar_definition": "verbatim text of what counts as a similar contract",
    "documents": ["file names reviewed, including every bulletin"]
  },
  "requirements": [
    {
      "id": "R-001",
      "doc": "Annex A",
      "page": 17,
      "clause": "5.4",
      "section": "Eligible Bidders",
      "text": "Requirement text, verbatim or tightly paraphrased",
      "category": "Facility rating",
      "scope": "VITRO DC",
      "mandatory": true,
      "amended_by": "Bid Bulletin No. 1, item 11",
      "amended_text": "Text as amended or clarified by the bulletin",
      "rating": "Unverified",
      "evidence": [],
      "rationale": "Why this rating",
      "clarification": "Question to raise if rating is Clarify",
      "sites": {
        "VITRO Clark": {"rating": "Comply", "evidence": ["SPEC-187"], "note": "Rated 3 Facility Certified"},
        "VITRO Sta Rosa": {"rating": "Partial", "evidence": ["SPEC-187"], "note": "Rated 3 Design Certified only"},
        "VITRO Davao": {"rating": "Gap", "evidence": ["SPEC-187"], "note": "No TIA-942 rating"}
      }
    }
  ],
  "assessment": {
    "recommended_site": "VITRO Clark",
    "gate1": {"result": "...", "basis": "...", "reference": "..."},
    "gate2": {"result": "...", "basis": "...", "reference": "..."},
    "flags": [{"flag": "...", "reference": "..."}]
  }
}
```

### Evidence IDs
| Prefix | Source |
|---|---|
| `SPEC-<row>` | VITRO Specifications Table row (Excel row number), read by `read_specs.py`. Valid only inside a site rating: the cell for that site is checked. |
| `C-` `SEAT-` `DIST-` `PER-` `LT-` | VITRO Reference Register rows (contracts, DR seats and office, site distances, personnel, lead times). |

### Field rules

| Field | Values |
|---|---|
| `category` | Eligibility, Delivery, Colocation, DR seats, Office space, Connectivity, Facility rating, Certifications, Personnel, Security, Service levels, Commercial, Other |
| `scope` | `VITRO DC`: VITRO's facility or services deliver it (colocation, racks, power, cooling, cage, DR seats, office, carrier connectivity, facility certifications, physical security, DC staff). `Bidder (general)`: applies to the bidder as a company whoever delivers (eligibility, ISO of the bidder, project team, warranty, SLAs, training). `Partner`: equipment, software and integration work VITRO would source from a partner (servers, storage, firewalls, SD-WAN boxes, licences, replication). |
| `rating` | `Comply`, `Partial`, `Gap`, `Clarify`, `Unverified`, `Partner scope`, `N/A` |
| `evidence` | Evidence IDs (see above). Required for `Comply` and `Partial`. |
| `sites` | VITRO DC rows only: one entry per site, each with `rating`, `evidence`, `note` (25 words max). Sites not given default to Unverified. Ignored for other scopes. |
| `assessment.recommended_site` | Optional. Defaults to the best-fit site (fewest gaps, then most Comply). |

### Granularity
- `VITRO DC` and `Bidder (general)` scope: one row per lowest-numbered clause that states an obligation.
- `Partner` scope: one row per equipment or software item (for example 4.3.2 Perimeter Firewall), with the key specifications summarised in `text`.
- Headings with no obligation are not rows.

### Site rating guide
- `Comply`: the site's spec cell clearly meets the requirement. "Optional" (i) means the service can be provided.
- `Partial`: meets part of it, or the cell says "Negotiable"; say what is missing.
- `Gap`: the cell explicitly fails (Not available, "No", or a value below the requirement).
- `Unverified`: no spec row on the topic, or the site's cell is blank.
- Never infer one site from another. Never estimate distances: use Site Distances rows.

### Rating rules (enforced by `build_matrix.py`)
- `Comply` or `Partial` with no evidence, an unknown ID, or a register row with no Source Document is downgraded to `Unverified`.
- A `SPEC-` citation whose cell is blank for that site is downgraded to `Unverified`. `Comply` citing a cell marked Not available is downgraded.
- Evidence past its Valid Until / Earliest Expiry date (checked against the bid deadline) is downgraded to `Unverified` and noted.
- Evidence with an As-of Date older than 180 days is kept but marked stale.
- `Partner` scope rows default to `Partner scope` unless rated otherwise.

## gates.json (output of `check_gates.py`, input to `build_matrix.py` and the memo)
Produced by the script; Claude adds `similar` judgments and verdicts. See the script docstring.

## memo.json (input to `build_memo.py`)

```json
{
  "iom_number": "O000000 / BDI-2026-0000",
  "date": "November 23, 2026",
  "to": "Head, Solutions",
  "endorsed_by": "[Name]",
  "from": "Solutions",
  "subject": "Bid / No-Bid: BI Business Continuity Facility (BI-CB-2026-090)",
  "summary": "One or two sentences: verdict first, then the reason.",
  "sections": [
    {
      "heading": "Gate Results",
      "paragraphs": ["..."],
      "table": {
        "headers": ["Gate", "Result", "Basis", "Reference"],
        "rows": [["1. Eligibility (SLCC)", "Unverified", "...", "ITB 5.3; BDS"]],
        "status_col": 1,
        "source": "Source: ..."
      }
    }
  ]
}
```
Tables in the memo have exactly four columns. `status_col` (0-based) gets the status accent.
Optional `widths`: four relative column widths, e.g. `[2.2, 1.3, 4.2, 2.3]` (give the longest text the most).
Optional `after`: paragraphs placed after the table's source line.

## specs.json (output of `read_specs.py`)
`source` (file, sheet, date in file name, read date, legend), `sites` (name, city, address, ownership),
`rows` (id `SPEC-<row>`, section, group, item, description, baseline, `cells` {site: {status, detail}}).
Status is Available, Not available, Optional, Not applicable, Value (free text in detail) or Blank.
