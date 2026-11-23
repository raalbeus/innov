# Bid qualification process

Based on the Solutions team's evaluation steps (Solutions Consultant email, 20 November 2026) and the
Philippine Bidding Documents (PBD) under Republic Act No. 12009 (New Government Procurement Act).

## Where things are in a PBD package

| What | Where |
|---|---|
| Approved Budget for the Contract (ABC), delivery period, bid deadline | Section I Invitation to Bid; BDS 12.4 |
| SLCC rule (50%, or 25% + 25%) | ITB Clause 5.3 |
| SLCC completion window | BDS 5.4 (often 5 or 10 years before the deadline) |
| Definition of "similar contract" | BDS 5.5 |
| Subcontracting allowed or not | BDS 8.1 |
| Joint venture, foreign bidders | BDS 5.2, ITB 5 |
| Net Financial Contracting Capacity (NFCC) / credit line | ITB 5.5 |
| Delivery schedule | Section VI Schedule of Requirements |
| Technical requirements | Section VII, usually "See Annex A" (often a scanned TOR) |
| Eligibility items repeated in the TOR | TOR "Eligible Bidders" or "Qualifications" section |
| Changes after issue | Supplemental / Bid Bulletins: these override the original text |

## Gate 1: Eligibility (SLCC)
1. Read ITB 5.3, BDS 5.4 and 5.5, and any TOR eligibility section. Record the ABC, the window and the
   similar-contract definition verbatim in `bid`.
2. Check every bulletin for SLCC rulings (for example, BI BCF Bid Bulletin No. 1, item 18: only fully
   completed contracts count; recurring colocation under the same agreement does not). Use
   `--exclude-recurring` when a ruling like this applies.
3. Run `check_gates.py`. For each candidate it returns, judge similarity: compare the contract's Scope
   Description with the BDS 5.5 definition. Name the contract ID and say why it is or is not similar.
4. Result: `Pass` only when a candidate is both above the amount and similar, with a sourced register
   row. `Fail` when no contract qualifies. `Unverified` when the register is empty. `Needs review` when
   similarity is arguable.

## Gate 2: Delivery lead time
1. Read the delivery period in Section VI and any milestone schedule in the TOR (for example
   "Delivery and Implementation"). Check bulletins: they may fix milestone durations.
2. Decide which register Lead Times apply. Guideline from the Solutions team: a straightforward
   solution with no customization can fit in 30 calendar days; customization or added hardware
   needs longer.
3. Run `check_gates.py --delivery-days N --lead-times LT-...`. `Unverified` when no sourced lead
   time applies. Note any milestone (not only the total) that looks tight.

## Gate 3: Data center compliance (per site)
Read Section VII and every annex in full. Scanned pages are images: read every one.
Rate every VITRO DC requirement for each site in the VITRO Specifications Table (`specs.md`), citing
SPEC rows. One site must meet every requirement, so Gate 3 is judged on the best-fit site: the one
with the fewest gaps, then the most Comply ratings. A site with more than half its requirements
unverified (mostly blank cells) is marked "Insufficient data" and never recommended. Hard filters such as a minimum distance from the client's
site, a required third-party facility certification, or a required certificate (PCI DSS, ISO 50001)
usually decide the shortlist; name them in the memo. Check these areas in particular:
- **Colocation**: racks, power per rack, cage, location constraints (distance from the client's
  main site, hazard zones), ownership or lease term, power and cooling redundancy, generator autonomy,
  fire suppression, Building Management System (BMS), remote hands.
- **DR seats**: count, area, fit-out, equipment, activation time.
- **Office space**: dedicated or shared, size, fit-out.
- **Connectivity**: Dedicated Internet Access (DIA), Multiprotocol Label Switching (MPLS), bandwidth,
  public IPs, carrier neutrality, Meet-Me-Room, cross-connects, SLAs.
- **Facility rating**: TIA-942 rating and level, Uptime tier, whether third-party certification is
  required (check bulletins), seismic and structural requirements.
- **Certifications**: ISO standards, PCI DSS, others; whose certificate (bidder, facility, manufacturer).
- **Personnel**: counts, certifications, dedicated vs shared.
- **Service levels**: availability %, response and resolution times, penalties.

For each requirement and site, rate it against the spec cell (and register rows for DR seats, distances
and personnel). Comply only with evidence that proves it. Map spec rows to requirement areas:
power, UPS, generator and cooling (General Facilities); racks, kVA per rack, cage (Rack & Cage, Power
Supply); access control and CCTV (Security Device, Monitoring System); remote hands (Basic
Troubleshooting, Troubleshooting); SLAs (Service Level Agreement); office rental (Other Optional
Services); certifications and TIA-942 / Uptime (Certification, Tier Level); carriers, IX and
Meet-Me-Room (Connectivity, In-house Cabling).
Look for internal inconsistencies (for example an SLA figure missing, or an availability target above
what the required tier delivers) and rate those `Clarify` with a drafted question.

## Flags to always check (put in `assessment.flags`)
- Subcontracting not allowed (BDS 8.1) while Partner-scope work is large: VITRO would need to supply
  partner goods itself or bid as a joint venture. Needs a decision from Legal/Contracts and the bid lead.
- Joint venture allowed or not.
- Location constraints that exclude some or all VITRO sites.
- Bid deadline already passed or too close to prepare.
- Pricing, legal terms or government positions in the TOR: flag for the bid lead; do not assess.
- Bid security, performance security and warranty terms that change cost materially: list, do not price.

## Verdict
- `No-Go`: any gate fails (no qualifying SLCC, delivery infeasible, or a mandatory VITRO DC gap with
  no workaround).
- `Insufficient evidence`: no failures, but at least one gate is `Unverified` (for example the
  register has no contracts, so SLCC cannot be checked). Say what evidence is missing.
- `Conditional Go`: no failures, every gate checked, but items are Unverified, Partial or need clarification. List exactly
  what must be confirmed and by whom.
- `Go`: all three gates pass with sourced evidence.
The verdict is a recommendation for the Solutions team. The bid/no-bid decision stays with people.

## Clarification route
Unclear items go to the Pre-Bid Conference or a written clarification within the deadline in ITB 9
(usually 10 calendar days before bid submission). Responses come back in a Supplemental/Bid Bulletin.
If the clarification deadline has passed, say so in the memo.
