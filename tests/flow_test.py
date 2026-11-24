"""End-to-end test of the three-step flow with SAMPLE fixtures (no confidential data needed).

Run:  python3 tests/flow_test.py [/path/to/bid/pdfs]
Without a PDF folder, a one-page sample PDF is generated. AI runs in replay mode on synthetic outputs.
Checks: sign-in rules (domain, allow-list, codes), step 2 (upload, checks, review, confirm, reuse),
step 3 locked until a table is confirmed, the full run, results page and downloads, access control.
"""
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp(prefix="bq-flow-"))
fx = tmp / "fixtures"
subprocess.run([sys.executable, str(ROOT / "tests" / "make_sample_fixtures.py"), str(fx)], check=True,
               capture_output=True)
SPEC = fx / "SAMPLE_Specifications_Table.xlsx"
ref = tmp / "reference"
ref.mkdir()
os.environ.update({
    "SESSION_SECRET": secrets.token_urlsafe(48), "COOKIE_SECURE": "false",
    "MAIL_MODE": "console", "SOURCE_MODE": "local", "AI_MODE": "replay",
    "DATA_DIR": str(tmp / "data"), "LOCAL_REF_DIR": str(ref), "REPLAY_DIR": str(fx / "replay"),
    "ALLOWED_DOMAINS": "vitrodc.com", "ALLOWED_EMAILS": "listed.person@example.org",
    "ADMIN_EMAILS": "listed.person@example.org",
})
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app import main, mailer  # noqa: E402

sent = {}
mailer.send_code = lambda email, code: sent.__setitem__(email, code)
ok_count = 0


def check(cond, msg):
    global ok_count
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    ok_count += 1
    print(f"  ok  {msg}")


def csrf_of(html):
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    return m.group(1) if m else ""


def sign_in(client, email):
    r = client.get("/login")
    r = client.post("/login", data={"email": email, "csrf": csrf_of(r.text)}, follow_redirects=False)
    assert r.status_code == 303, r.text[:300]
    r = client.get("/verify")
    r = client.post("/verify", data={"code": sent[email], "csrf": csrf_of(r.text)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/home", r.text[:300]


def sample_pdf(path):
    """A one-page PDF (the app only checks the %PDF header and extracts text)."""
    body = b"BT /F1 12 Tf 72 720 Td (SAMPLE bid document for sandbox testing) Tj ET"
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    path.write_bytes(out)


pdf_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else None
if not pdf_dir:
    pdf_dir = tmp / "pdfs"
    pdf_dir.mkdir()
    sample_pdf(pdf_dir / "SAMPLE_TOR.pdf")

c = TestClient(main.app)

print("Step 1: sign-in")
r = c.get("/home", follow_redirects=False)
check(r.status_code == 303 and r.headers["location"] == "/login", "signed-out user is sent to /login")
check(c.get("/spec", follow_redirects=False).headers.get("location") == "/login", "step 2 needs sign-in")
check(c.get("/bid", follow_redirects=False).headers.get("location") == "/login", "step 3 needs sign-in")
r = c.get("/login")
r = c.post("/login", data={"email": "someone@gmail.com", "csrf": csrf_of(r.text)})
check("company email" in r.text and "someone@gmail.com" not in sent, "address outside the domain is refused")
r = c.get("/login")
r = c.post("/login", data={"email": "x@vitrodc.com.evil.io", "csrf": csrf_of(r.text)})
check("x@vitrodc.com.evil.io" not in sent, "look-alike domain is refused")
r = c.get("/login")
r = c.post("/login", data={"email": "A.User@VitroDC.com", "csrf": csrf_of(r.text)}, follow_redirects=False)
check(r.status_code == 303 and "a.user@vitrodc.com" in sent, "company address gets a code")
r = c.get("/verify")
wrong = "000000" if sent["a.user@vitrodc.com"] != "000000" else "111111"
r = c.post("/verify", data={"code": wrong, "csrf": csrf_of(r.text)})
check("Incorrect code" in r.text, "wrong code refused")
r = c.post("/verify", data={"code": sent["a.user@vitrodc.com"], "csrf": csrf_of(r.text)}, follow_redirects=False)
check(r.status_code == 303 and r.headers["location"] == "/home", "correct code signs in")
c_list = TestClient(main.app)
sign_in(c_list, "listed.person@example.org")
check(True, "allow-listed address outside the domain signs in")

print("Step 3 is locked until step 2 is done")
r = c.get("/home")
check("Continue to step 2" in r.text and "(locked)" in r.text, "home points to step 2; step 3 shown locked")
r = c.get("/bid", follow_redirects=False)
check(r.status_code == 303 and r.headers["location"] == "/spec", "step 3 redirects to step 2")
r = c.get("/spec")
check("Confirm a Specifications Table before" in r.text, "user is told why")
pdf_files = [("files", (p.name, p.read_bytes(), "application/pdf")) for p in sorted(pdf_dir.glob("*.pdf"))]
r = c.post("/jobs", data={"csrf": csrf_of(r.text)}, files=pdf_files)
check(r.status_code == 409, "starting a run without a confirmed table is refused")

print("Step 2: Specifications Table")
r = c.get("/spec")
tok = csrf_of(r.text)
check("No table has been uploaded yet" in r.text, "no tables yet")
r = c.post("/spec", data={"csrf": tok}, files={"file": ("notes.txt", b"hello", "text/plain")})
check("Excel .xlsx" in r.text, "non-xlsx refused")
from openpyxl import Workbook  # noqa: E402
blank = tmp / "Blank.xlsx"
Workbook().save(blank)
r = c.post("/spec", data={"csrf": tok}, files={"file": ("Blank.xlsx", blank.read_bytes(), "application/octet-stream")})
check("No data center sites" in r.text, "workbook without site columns refused")
r = c.post("/spec", data={"csrf": "forged"}, files={"file": (SPEC.name, SPEC.read_bytes(), "application/octet-stream")})
check(r.status_code == 400, "forged CSRF token refused")
r = c.post("/spec", data={"csrf": tok}, files={"file": (SPEC.name, SPEC.read_bytes(), "application/octet-stream")},
           follow_redirects=False)
check(r.status_code == 303 and r.headers["location"].startswith("/spec/"), "valid table accepted")
review = r.headers["location"]
spec_id = review.rsplit("/", 1)[1]
r = c.get(review)
check("SAMPLE Site A" in r.text and "Use this table and continue" in r.text and ">13<" in r.text,
      "review shows sites and 13 rows before confirming")
check(c.get("/bid", follow_redirects=False).status_code == 303, "uploading alone does not unlock step 3")
r2 = c.post("/spec", data={"csrf": tok}, files={"file": (SPEC.name, SPEC.read_bytes(), "application/octet-stream")},
            follow_redirects=False)
check(r2.headers["location"] == review, "identical file is reused, not stored twice")
check(c.get(review + "/file").content[:2] == b"PK", "stored table can be downloaded")
r = c.post(review + "/confirm", data={"csrf": csrf_of(c.get(review).text)}, follow_redirects=False)
check(r.status_code == 303 and r.headers["location"] == "/bid", "confirm leads to step 3")

print("Another user reuses the latest table")
r = c_list.get("/spec")
check(SPEC.name in r.text and "latest" in r.text, "recent table listed for another user")
check(c_list.get("/bid", follow_redirects=False).status_code == 303, "their step 3 stays locked until they confirm")
c_list.post(review + "/confirm", data={"csrf": csrf_of(c_list.get(review).text)})
check(c_list.get("/bid").status_code == 200, "after confirming, step 3 opens")
check("Replace the Reference Register" in c_list.get("/bid").text, "admin sees the Reference Register upload")
check("Replace the Reference Register" not in c.get("/bid").text, "non-admin does not")

print("Step 3: bid documents")
r = c.get("/bid")
check(SPEC.name in r.text and f'value="{spec_id}"' in r.text, "step 3 shows the confirmed table")
r = c.post("/jobs", data={"csrf": csrf_of(r.text), "spec_id": "20200101-000000-abcdef"}, files=pdf_files)
check(r.status_code == 409, "stale table id from another tab refused")
r = c.post("/jobs", data={"csrf": csrf_of(c.get("/bid").text)}, files=[("files", ("x.pdf", b"nope", "application/pdf"))])
check(r.status_code == 400, "non-PDF content refused")
r = c.post("/jobs", data={"title": "Sandbox", "csrf": csrf_of(c.get("/bid").text), "spec_id": spec_id},
           files=pdf_files, follow_redirects=False)
check(r.status_code == 303 and r.headers["location"].startswith("/jobs/"), "run started")
job_url = r.headers["location"]
t0 = time.time()
while time.time() - t0 < 900:
    s = c.get(job_url + "/status").json()
    if s["status"] in ("done", "failed"):
        break
    time.sleep(1)
check(s["status"] == "done", f"run finished (status {s['status']}, error {s.get('error')})")
r = c.get(job_url)
check(SPEC.name in r.text, "results cite the confirmed table")
check("1. Eligibility (SLCC)" in r.text and "2. Delivery lead time" in r.text and "3. Data center compliance" in r.text,
      "three gates shown in order")
for area in ("Colocation", "DR seats", "Office space", "Connectivity", "Additional requirements"):
    check(f"<td>{area}</td>" in r.text, f"gate 3 area: {area}")
check("separate building entrances" in r.text, "clarification questions listed")
links = re.findall(r'href="(/jobs/[^"]+/files/[^"]+)"', r.text)
check(len(links) == 2, "two download links")
for link in links:
    d = c.get(link)
    check(d.status_code == 200 and d.content[:2] == b"PK", f"{link.rsplit('/', 1)[1]} is a valid Office file")
r = c.get("/home")
check(SPEC.name in r.text, "history shows the table used")

print("Access control")
check(c_list.get(job_url).status_code == 404 and c_list.get(links[0]).status_code == 404,
      "another user cannot see the run or its files")
check(c.get(job_url + "/files/..%2Fapp.db").status_code == 404, "path outside the run refused")
check(c.get("/spec/../app.db").status_code == 404, "bad table id refused")
from app import db  # noqa: E402
with db.conn() as cx:
    actions = {row[0] for row in cx.execute("SELECT action FROM audit")}
check({"spec_uploaded", "spec_confirmed", "spec_rejected", "job_started", "job_done"} <= actions,
      "audit log records table uploads, confirmations and runs")

print(f"\nAll {ok_count} checks passed. Data in {tmp}")
