"""Claude calls. Every step returns JSON validated against a schema (structured outputs).

Model and effort come from config (default claude-opus-5-5, effort high). Requests
stream (inputs can be large), use adaptive thinking, and enable the server-side
refusal fallback (`fallbacks: "default"`), so a policy decline is retried on a
fallback model inside the same call.
"""
import base64
import json
import logging
import time

from . import config

log = logging.getLogger("bidapp.ai")
_client = None

CATEGORIES = ["Eligibility", "Delivery", "Colocation", "DR seats", "Office space", "Connectivity",
              "Facility rating", "Certifications", "Personnel", "Security", "Service levels", "Commercial", "Other"]
SCOPES = ["VITRO DC", "Bidder (general)", "Partner"]
SITE_RATINGS = ["Comply", "Partial", "Gap", "Clarify", "Unverified"]


def _obj(props, required=None):
    return {"type": "object", "properties": props, "required": required or list(props),
            "additionalProperties": False}


S = {"type": "string"}
INT = {"type": "integer"}
NUM_OR_NULL = {"anyOf": [{"type": "number"}, {"type": "null"}]}
INT_OR_NULL = {"anyOf": [{"type": "integer"}, {"type": "null"}]}

TERMS_SCHEMA = _obj({
    "bid": _obj({
        "title": S, "procuring_entity": S, "reference_no": S,
        "abc_php": NUM_OR_NULL, "bid_deadline": S, "delivery_days": INT_OR_NULL, "delivery_basis": S,
        "slcc_window_years": INT_OR_NULL, "slcc_rule": S, "similar_definition": S,
        "subcontracting": {"type": "string", "enum": ["Allowed", "Not allowed", "Not stated"]},
        "joint_venture": {"type": "string", "enum": ["Allowed", "Not allowed", "Not stated"]},
        "slcc_excludes_ongoing_recurring": {"type": "boolean"},
        "source_pages": S,
    }),
    "flags": {"type": "array", "items": _obj({"flag": S, "reference": S})},
})

REQ_SCHEMA = _obj({"requirements": {"type": "array", "items": _obj({
    "doc": S, "page": INT, "clause": S, "section": S, "text": S,
    "category": {"type": "string", "enum": CATEGORIES},
    "scope": {"type": "string", "enum": SCOPES},
    "mandatory": {"type": "boolean"},
})}})

BULLETIN_SCHEMA = _obj({"items": {"type": "array", "items": _obj({
    "item": S, "page": INT, "clauses": {"type": "array", "items": S}, "query": S, "resolution": S,
    "effect": {"type": "string", "enum": ["Amends requirement", "Clarifies requirement", "No change", "Administrative"]},
    "note": S,
})}})

RATING_SCHEMA = _obj({"ratings": {"type": "array", "items": _obj({
    "id": S,
    "sites": {"type": "array", "items": _obj({
        "site": S, "rating": {"type": "string", "enum": SITE_RATINGS},
        "evidence": {"type": "array", "items": S}, "note": S})},
    "rating": {"type": "string", "enum": SITE_RATINGS},
    "evidence": {"type": "array", "items": S},
    "rationale": S,
    "clarification": S,
})}})


class AIError(RuntimeError):
    pass


def client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(max_retries=4)
    return _client


def pdf_page_blocks(pages):
    """pages: [(label, text or None, png_path or None)] -> content blocks."""
    blocks = []
    for label, text, png in pages:
        if png:
            data = base64.standard_b64encode(png.read_bytes()).decode()
            blocks.append({"type": "text", "text": f"--- {label} (scanned image) ---"})
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}})
        else:
            blocks.append({"type": "text", "text": f"--- {label} ---\n{text}"})
    return blocks


def call_json(step, system, content, schema, max_tokens=64000, cache_system=False):
    """Run one structured-output request and return the parsed JSON object."""
    import anthropic

    sys_blocks = [{"type": "text", "text": system}]
    if cache_system:
        sys_blocks[0]["cache_control"] = {"type": "ephemeral"}
    t0 = time.time()
    try:
        with client().beta.messages.stream(
            model=config.CLAUDE_MODEL,
            max_tokens=max_tokens,
            system=sys_blocks,
            messages=[{"role": "user", "content": content}],
            thinking={"type": "adaptive"},
            output_config={"effort": config.CLAUDE_EFFORT,
                           "format": {"type": "json_schema", "schema": schema}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            msg = stream.get_final_message()
    except anthropic.RateLimitError as e:
        raise AIError(f"{step}: Claude API rate limit reached; try again later. ({e.message})") from e
    except anthropic.AuthenticationError as e:
        raise AIError(f"{step}: Claude API key rejected. Check ANTHROPIC_API_KEY.") from e
    except anthropic.BadRequestError as e:
        raise AIError(f"{step}: request rejected by the Claude API: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise AIError(f"{step}: Claude API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise AIError(f"{step}: cannot reach the Claude API: {e}") from e

    u = msg.usage
    log.info("%s: %.0fs, in %s (cache read %s), out %s, stop %s, request %s", step, time.time() - t0,
             u.input_tokens, getattr(u, "cache_read_input_tokens", None), u.output_tokens, msg.stop_reason,
             getattr(msg, "_request_id", None))
    if msg.stop_reason == "refusal":
        cat = getattr(getattr(msg, "stop_details", None), "category", None)
        raise AIError(f"{step}: Claude declined this request (category: {cat}).")
    if msg.stop_reason == "max_tokens":
        raise AIError(f"{step}: response was cut off at max_tokens; split the input into smaller parts.")
    text = next((b.text for b in msg.content if b.type == "text"), None)
    if text is None:
        raise AIError(f"{step}: no JSON returned.")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise AIError(f"{step}: invalid JSON returned: {e}") from e


# ---------------------------------------------------------------- prompts
TERMS_SYSTEM = """You read Philippine government bidding documents (Philippine Bidding Documents under
RA 12009) for VITRO Data Centers. Extract the bid's core terms exactly as written.
- abc_php: the Approved Budget for the Contract in PHP as a number; null if not stated.
- bid_deadline: deadline for submission of bids as YYYY-MM-DD (use the latest bulletin if it moves it); "" if not stated.
- delivery_days: delivery or implementation period in calendar days (Section VI); null if not stated.
- slcc_window_years: years before the deadline within which the SLCC must have been completed (BDS 5.4); null if not stated.
- slcc_rule and similar_definition: quote the BDS / ITB text (similar contract definition is usually BDS 5.5).
- subcontracting (BDS 8.1) and joint_venture: as stated.
- slcc_excludes_ongoing_recurring: true only if a bulletin or the BDS says contracts with ongoing recurring
  services under the same agreement do not count as completed.
- source_pages: where you found these (document and page).
- flags: decision points for the bid lead: deadline already passed or close, subcontracting restrictions,
  location or distance rules for the facility, third-party certification demands, payment or warranty terms
  that change cost, personnel headcount rules. One sentence each with a document/clause reference.
Never estimate a number. Use "" or null when the documents do not state it."""

REQ_SYSTEM = """You extract requirements from the technical specifications / Terms of Reference of a
Philippine government tender, for VITRO Data Centers (a colocation data center operator).
Return every requirement on the pages given. Rules:
- doc: the document name given; page: the page number in the label; clause: as printed; section: nearest heading.
- text: verbatim where short, tightly paraphrased if long; keep every number, quantity, standard and duration.
- scope: "VITRO DC" for anything the data center facility or its services deliver (co-location, racks, cage,
  power, cooling, generators, UPS, fire suppression, building management, facility rating/TIA-942, physical
  security, DR seats, office/work area at the facility, carrier and internet connectivity into the facility,
  remote hands, facility certifications, DC staff credentials, DC SLAs).
  "Bidder (general)" for company-level obligations (eligibility, project team, warranty, training, general SLAs).
  "Partner" for equipment, software, licences and integration work VITRO would source from a partner.
- Granularity: one row per obligation clause for VITRO DC and Bidder (general); one row per equipment or
  software item for Partner (summarise its key specs). Headings without an obligation are not rows.
- If text is illegible, include the row with text "[illegible]" rather than guessing."""

BULLETIN_SYSTEM = """You read a bid bulletin / Supplemental Bid Bulletin issued by a Philippine procuring
entity. Return one object per numbered query/resolution item.
- clauses: the TOR / Annex clause numbers the item refers to, as printed (e.g. "4.4.2.4"); BDS/ITB items as "BDS 5.4".
- resolution: the answer, verbatim if under about 60 words, else tightly paraphrased keeping all numbers.
- effect: Amends requirement / Clarifies requirement / No change / Administrative.
- note: anything material for a data center operator (colocation, racks, cage, DR seats, office, connectivity,
  facility certification, SLCC eligibility, delivery timeline, personnel), else "".
The two-column layout interleaves question and answer text; read carefully."""

RATE_SYSTEM_HEAD = """You rate tender requirements for VITRO Data Centers against VITRO's own evidence.
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
question to ask when rating is Clarify, else "".

"""


def rating_system(specs_md, register_md):
    return RATE_SYSTEM_HEAD + "=== VITRO SPECIFICATIONS TABLE ===\n" + specs_md + \
        "\n\n=== VITRO REFERENCE REGISTER ===\n" + (register_md or "(empty)")
