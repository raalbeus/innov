# VITRO Bid Qualification

INTERNAL. Web app for the VITRO Data Centers Solutions team.

The app works in three steps:
1. **Sign in** with a company address (@vitrodc.com) or an address on the allow-list, using an email one-time code.
2. **Specifications Table.** Upload the current VITRO Specifications Table (.xlsx), or reuse a recent one. The
   app checks the file, shows its sites and rows, and the user confirms it. Step 3 stays locked until then.
3. **Bid documents.** Upload the Philippine government bid package (bidding documents, scanned annexes,
   bulletins). The run is rated against the table confirmed in step 2, and the table is recorded with the run.

It returns:
- a Go/No-Go inter-office memo (.docx)
- a compliance and site-fit matrix (.xlsx)

It checks three gates (Single Largest Completed Contract eligibility, delivery lead time, data center
compliance) and rates every data center requirement for every VITRO site against the VITRO Specifications
Table. A rating can be Comply only when it cites a cell in the Specifications Table or a row in the Reference
Register; the app downgrades anything else to Unverified. Ratings are drafts until a reviewer signs off each row.

## Try it in a GitHub Codespace (sandbox)
A codespace runs the app in your browser on GitHub, private to you. Nothing is installed on your computer.

1. **Create the codespace.** Repository home > Code > Codespaces > Create codespace on main. The first start
   installs the requirements and **starts the app by itself** (a few minutes).
2. **Open the app.** A browser tab opens on port 8000. If it does not, open the Ports tab and click the globe
   icon next to "Bid Qualification". Keep the port **Private** (the default).
3. **Sign-in is skipped in the sandbox** (`SKIP_LOGIN=true`): the app opens on the home page as
   `tester@vitrodc.com`. To test sign-in, start with `SKIP_LOGIN=false ./start-codespace-app.sh`, enter any
   @vitrodc.com address, and run `./signin-code.sh` in the terminal to see the code (the sandbox does not send email).
4. **Step 2.** Without an API key the app runs on SAMPLE data: click "Use the reference folder table", check the
   summary and continue. With your real table, upload it instead.
5. **Step 3.** Upload the bid PDFs and start. Download the memo and matrix from the results page.

If the app page shows "502", the app is not running: in the terminal run `./start-codespace-app.sh`
(it prints the reason if it cannot start; the log is `data/app.log`).

**Real Claude runs.** Add `ANTHROPIC_API_KEY` under Settings > Secrets and variables > Codespaces, then
restart the codespace. Get IT/data approval first: uploaded tenders and the Specifications Table are sent to
the Claude API. Other optional secrets: `ALLOWED_EMAILS` (sign-in addresses outside @vitrodc.com) and
`ADMIN_EMAILS` (who may upload the Reference Register).

Codespaces stop after inactivity; the app starts again when you reopen the codespace. Data in `data/` stays
in the codespace until you delete it. Delete the codespace when you are done with confidential files.

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
| `SKIP_LOGIN` | unset | `true`: no sign-in, everyone works as `TEST_USER`. Refused unless `MAIL_MODE=console` |

## Testing without confidential data
`python3 tests/flow_test.py` runs sign-in, step 2, step 3 and a full run in replay mode on invented data
(sites "SAMPLE Site A/B/C"). To click through the app yourself, write the sample files and start in replay mode:
```bash
python3 tests/make_sample_fixtures.py data/sample
AI_MODE=replay REPLAY_DIR=data/sample/replay MAIL_MODE=console COOKIE_SECURE=false SOURCE_MODE=local \
SESSION_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))') python3 -m uvicorn app.main:app --port 8000
```
Upload `data/sample/SAMPLE_Specifications_Table.xlsx` in step 2. In a codespace, `AI_MODE=replay ./run-codespace.sh`
does the same in one command (no API key needed). Replay results are fixed test outputs: they
do not read the uploaded PDFs.

## Sign-in rules
- Allowed: @vitrodc.com addresses (`ALLOWED_DOMAINS`), plus addresses in `ALLOWED_EMAILS`.
- 6-digit code, valid 10 minutes, single use.
- 5 wrong entries lock the code; at most 3 codes per address per 15 minutes.
- Sessions last 8 hours. Users see only their own runs. Sign-ins, table uploads and confirmations, runs and
  downloads go to an audit log.
- Any signed-in user can upload a Specifications Table; every user confirms a table for their own session.

## Layout
| Path | Purpose |
|---|---|
| `app/` | Web app: routes, sign-in, mail, SharePoint, Claude calls, job pipeline, pages |
| `engine/` | Bid qualification scripts and templates (extract, read specs, gates, matrix, memo) |
| `skill/` | The same process as a Claude skill (`/bid-qualify`) for use in claude.ai |
| `tests/flow_test.py` | End-to-end test of the three-step flow on SAMPLE data: `python3 tests/flow_test.py [pdf_dir]` |
| `tests/make_sample_fixtures.py` | Writes a synthetic Specifications Table and replay outputs for sandbox testing |
| `tests/skip_login_test.py` | Checks the sandbox `SKIP_LOGIN` switch and that it is refused outside sandbox mode |
| `tests/smoke_test.py` | End-to-end test on the confidential fixtures, which are not in the repository |
| `.devcontainer/`, `run-codespace.sh` | GitHub Codespaces sandbox |
| `Dockerfile`, `run.sh` | Production |

## Known limits
- Claude calls are tested only in replay mode so far. Run one real bid in the sandbox before rollout.
- Email codes are weaker than company single sign-on with MFA; Microsoft Entra ID sign-in can replace them later.
- A server restart marks running jobs as failed; users start them again.

## Not in this repository
Bid documents, the Specifications Table, the filled Reference Register, test fixtures and run outputs.
They are confidential.
