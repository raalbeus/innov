# VITRO Bid Qualification

INTERNAL. Web app for the VITRO Data Centers Solutions team.

Staff sign in with an email one-time code. The app qualifies an uploaded Philippine government bid package
(bidding documents, scanned annexes, bulletins) and returns:
- a Go/No-Go inter-office memo (.docx)
- a compliance and site-fit matrix (.xlsx)

It checks three gates (Single Largest Completed Contract eligibility, delivery lead time, data center
compliance) and rates every data center requirement for every VITRO site against the VITRO Specifications
Table. A rating can be Comply only when it cites a cell in the Specifications Table or a row in the Reference
Register; the app downgrades anything else to Unverified. Ratings are drafts until a reviewer signs off each row.

## Try it in a GitHub Codespace (sandbox)
A codespace runs the app in your browser on GitHub, private to you. Nothing is installed on your computer.

1. **Add three secrets.** On GitHub: this repository > Settings > Secrets and variables > Codespaces >
   New repository secret.
   - `ANTHROPIC_API_KEY`: a Claude API key from the Anthropic Console. Get IT/data approval first: uploaded
     tenders and the Specifications Table are sent to the Claude API.
   - `ALLOWED_EMAILS`: your sign-in address if it is not @vitrodc.com (comma-separated for several).
   - `ADMIN_EMAILS`: the address(es) allowed to upload the reference files, usually your own.
2. **Create the codespace.** Repository home > Code > Codespaces > Create codespace on main. Wait for
   setup to finish (a few minutes the first time).
3. **Start the app.** In the codespace terminal run `./run-codespace.sh`. A browser tab opens on port 8000.
   If it does not, open the Ports tab and click the globe icon next to port 8000.
4. **Sign in.** Enter your email. In this sandbox the code is printed in the terminal ("DEV MODE sign-in
   code") instead of emailed. Enter it on the page.
5. **Upload the reference files.** On the home page, as an admin, choose "VITRO Specifications Table"
   and upload `VITRO_Specifications_Table_*.xlsx`. Upload the Reference Register the same way when it is
   filled (file name must start with `VITRO_Reference_Register`).
6. **Qualify a bid.** Upload all PDFs of the bid package and start. A large scanned tender takes several
   minutes. Download the memo and matrix from the results page.

Keep port 8000 **Private** (the default). Codespaces stop after inactivity; the data in `data/` stays in
the codespace until you delete it. Delete the codespace when you are done with confidential files.

## Production setup (IT)
| # | Item | Detail |
|---|---|---|
| 1 | Entra ID app registration | Client-credentials flow; secret or certificate in the host's secret store. |
| 2 | Mail.Send (application) | Limited by an Exchange application access policy to the sender mailbox only (e.g. `bidtool@vitrodc.com`). |
| 3 | Sites.Selected (application) | Read access to the one SharePoint site holding the reference folder. |
| 4 | Reference folder | e.g. `Bid Qualification/Reference` with `VITRO_Specifications_Table_*.xlsx` and `VITRO_Reference_Register_*.xlsx`. |
| 5 | Claude API key | Organization key with a spend limit; data approval as above. |
| 6 | Hosting | `Dockerfile` behind HTTPS (e.g. Azure App Service). One instance; persistent volume at `/data`. |
| 7 | Retention | `/data` holds uploads, results and the audit log: restrict access, back it up, set a retention period. |

Settings are in `.env.example`. Each external service has a test mode, and the app shows a "Test mode"
banner while one is active:

| Setting | Production | Sandbox / testing |
|---|---|---|
| `MAIL_MODE` | `graph` | `console`: code printed in the server log |
| `SOURCE_MODE` | `sharepoint` | `local`: files in `LOCAL_REF_DIR`, uploaded by `ADMIN_EMAILS` |
| `AI_MODE` | `claude` | `replay`: saved outputs, for testing without an API key |
| `COOKIE_SECURE` | `true` | `false` only for plain http on localhost |

## Sign-in rules
- Allowed: @vitrodc.com addresses (`ALLOWED_DOMAINS`), plus addresses in `ALLOWED_EMAILS`.
- 6-digit code, valid 10 minutes, single use.
- 5 wrong entries lock the code; at most 3 codes per address per 15 minutes.
- Sessions last 8 hours. Users see only their own runs. Sign-ins, runs, uploads and downloads go to an audit log.

## Layout
| Path | Purpose |
|---|---|
| `app/` | Web app: routes, sign-in, mail, SharePoint, Claude calls, job pipeline, pages |
| `engine/` | Bid qualification scripts and templates (extract, read specs, gates, matrix, memo) |
| `skill/` | The same process as a Claude skill (`/bid-qualify`) for use in claude.ai |
| `tests/smoke_test.py` | End-to-end test (needs the confidential fixtures, which are not in the repository) |
| `.devcontainer/`, `run-codespace.sh` | GitHub Codespaces sandbox |
| `Dockerfile`, `run.sh` | Production |

## Known limits
- Claude calls are tested only in replay mode so far. Run one real bid in the sandbox before rollout.
- Email codes are weaker than company single sign-on with MFA; Microsoft Entra ID sign-in can replace them later.
- A server restart marks running jobs as failed; users start them again.

## Not in this repository
Bid documents, the Specifications Table, the filled Reference Register, test fixtures and run outputs.
They are confidential.
