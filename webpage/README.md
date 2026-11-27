# Bid qualification web page (claude.ai)

INTERNAL. The bid qualification tool as a claude.ai page: no server, no Microsoft 365, no extra cost.
Consultants open the link while signed in to claude.ai; the page lets in the page owner, @vitrodc.com
addresses and any address in `ALLOWED_EMAILS` (top of the script in `index.html`).

Flow: sign in (claude.ai) -> Specifications Table (upload or reuse the latest, review, confirm; optional
Reference Register) -> bid PDFs -> Claude reads the documents with the consultant's own claude.ai usage ->
gates, site fit, clarifications -> memo (.docx, official template) and matrix (.xlsx) downloads. Each
consultant's runs are kept privately in their history.

| File | Purpose |
|---|---|
| `index.html` | The page: views, access check, storage, run control, results |
| `bq-core.js` | Rules ported from `engine/scripts` (read_specs, gates, evidence checks, site fit, verdict) |
| `bq-docs.js` | Memo and matrix builders (port of build_memo.py and the matrix sheets) |
| `bq-ai.js` | PDF reading (pdf.js) and the Claude steps (prompts from `app/ai.py`) |
| `memo-template.b64.txt` | `engine/templates/VITRO_Memo_Template.docx` as base64 (artifacts do not serve .docx) |

Publish with capabilities `user` (scopes profile, email), `db`, `sample` (images), `downloads`.
Rebuild the template file after changing the .docx: `base64 -w0 engine/templates/VITRO_Memo_Template.docx > webpage/memo-template.b64.txt`.
