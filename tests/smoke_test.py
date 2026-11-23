"""End-to-end test in local modes: console OTP, local reference folder, replay AI.

Run:  python3 tests/smoke_test.py /path/to/bid/pdfs
Checks sign-in rules, upload, the full pipeline, results and downloads, and access control.
"""
import os
import re
import secrets
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
if not (FIX / "reference").exists():
    raise SystemExit("Test fixtures are not in this checkout: they hold confidential bid data and stay out of "
                     "the repository. Put the fixtures folder at tests/fixtures to run this test.")
tmp = Path(tempfile.mkdtemp(prefix="bq-test-"))
ref = tmp / "reference"
ref.mkdir()
import shutil  # noqa: E402
SPEC = next((FIX / "reference").glob("*.xlsx"))
shutil.copy2(SPEC, ref / SPEC.name)
os.environ.update({
    "SESSION_SECRET": secrets.token_urlsafe(48), "COOKIE_SECURE": "false",
    "MAIL_MODE": "console", "SOURCE_MODE": "local", "AI_MODE": "replay",
    "DATA_DIR": str(tmp), "LOCAL_REF_DIR": str(ref), "REPLAY_DIR": str(FIX / "replay"),
    "ALLOWED_DOMAINS": "vitrodc.com", "ALLOWED_EMAILS": "listed.person@gmail.com",
    "ADMIN_EMAILS": "listed.person@gmail.com",
})
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app import main, mailer  # noqa: E402

sent = {}
mailer.send_code = lambda email, code: sent.__setitem__(email, code)  # capture instead of logging

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


pdf_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else None
c = TestClient(main.app)

print("Sign-in rules")
r = c.get("/home", follow_redirects=False)
check(r.status_code == 303 and r.headers["location"] == "/login", "signed-out user is sent to /login")
r = c.get("/login")
check("Content-Security-Policy" in r.headers and r.headers.get("X-Frame-Options") == "DENY", "security headers set")
r = c.post("/login", data={"email": "someone@gmail.com", "csrf": csrf_of(r.text)})
check("company email" in r.text and "someone@gmail.com" not in sent, "non-company domain rejected, no code sent")
r = c.post("/login", data={"email": "a.user@vitrodc.com", "csrf": "forged"})
check(r.status_code == 400 and "a.user@vitrodc.com" not in sent, "missing/forged CSRF token rejected")
r = c.get("/login")
r = c.post("/login", data={"email": "A.User@VitroDC.com ", "csrf": csrf_of(r.text)}, follow_redirects=False)
check(r.status_code == 303 and re.fullmatch(r"\d{6}", sent.get("a.user@vitrodc.com", "")), "code issued to normalized address")
r = c.get("/verify")
tok = csrf_of(r.text)
wrong = "000000" if sent["a.user@vitrodc.com"] != "000000" else "111111"
r = c.post("/verify", data={"code": wrong, "csrf": tok})
check("Incorrect code" in r.text, "wrong code refused with attempts left")
r = c.post("/verify", data={"code": sent["a.user@vitrodc.com"], "csrf": tok}, follow_redirects=False)
check(r.status_code == 303 and r.headers["location"] == "/home", "correct code signs in")
r = c.get("/home")
check("Connected" in r.text and "VITRO_Specifications_Table_02192026_4.xlsx" in r.text, "home shows reference folder and spec file")
check("Test mode" in r.text, "test-mode banner shown")

# code reuse and lockout on a second client
c2 = TestClient(main.app)
r = c2.get("/login")
c2.post("/login", data={"email": "b.user@vitrodc.com", "csrf": csrf_of(r.text)})
r = c2.get("/verify")
tok2 = csrf_of(r.text)
bad = "000000" if sent["b.user@vitrodc.com"] != "000000" else "111111"
for _ in range(5):
    r = c2.post("/verify", data={"code": bad, "csrf": tok2})
r = c2.post("/verify", data={"code": sent["b.user@vitrodc.com"], "csrf": tok2})
check("Request a new code" in r.text, "code locked after 5 wrong attempts")
for _ in range(4):
    r = c2.get("/login")
    r = c2.post("/login", data={"email": "c.user@vitrodc.com", "csrf": csrf_of(r.text)})
check("Too many codes" in r.text, "4th code request within 15 minutes is refused")

print("Allow-list and admin upload")
c3 = TestClient(main.app)
sign_in(c3, "listed.person@gmail.com")
check(True, "allow-listed personal address signs in")
r = c3.get("/home")
check("Replace a reference file" in r.text, "admin sees the reference upload form")
tok3 = csrf_of(r.text)
bad = c3.post("/reference", data={"kind": "spec", "csrf": tok3}, files={"file": ("notes.txt", b"hello", "text/plain")})
check(bad.status_code == 400, "non-xlsx reference upload refused")
bad = c3.post("/reference", data={"kind": "spec", "csrf": tok3}, files={"file": ("Other_Name.xlsx", SPEC.read_bytes(), "application/octet-stream")})
check(bad.status_code == 400, "reference file with the wrong name refused")
new_name = SPEC.name.replace(".xlsx", "_v2.xlsx")
r = c3.post("/reference", data={"kind": "spec", "csrf": tok3}, files={"file": (new_name, SPEC.read_bytes(), "application/octet-stream")}, follow_redirects=True)
check(new_name in r.text and "is now in use" in r.text, "admin upload of the Specifications Table is used")
r = c.get("/home")
check("Replace a reference file" not in r.text, "non-admin does not see the upload form")
check(c.post("/reference", data={"kind": "spec", "csrf": csrf_of(r.text)}, files={"file": (new_name, SPEC.read_bytes(), "application/octet-stream")}).status_code == 403,
      "non-admin upload refused")

if pdf_dir:
    print("Bid run (replay AI)")
    r = c.get("/home")
    files = [("files", (p.name, p.read_bytes(), "application/pdf")) for p in sorted(pdf_dir.glob("*.pdf"))]
    r = c.post("/jobs", data={"title": "BI BCF test", "csrf": csrf_of(r.text)}, files=files, follow_redirects=False)
    check(r.status_code == 303 and r.headers["location"].startswith("/jobs/"), "upload accepted, job created")
    job_url = r.headers["location"]
    t0 = time.time()
    while time.time() - t0 < 600:
        s = c.get(job_url + "/status").json()
        if s["status"] in ("done", "failed"):
            break
        time.sleep(2)
    check(s["status"] == "done", f"job finished (status {s['status']}, error {s.get('error')})")
    r = c.get(job_url)
    check("Best-fit site" in r.text and "VITRO Makati 2" in r.text, "results page shows verdict and best-fit site")
    links = re.findall(r'href="(/jobs/[^"]+/files/[^"]+)"', r.text)
    check(len(links) == 2, "two download links")
    for link in links:
        d = c.get(link)
        check(d.status_code == 200 and d.content[:2] == b"PK", f"download {link.rsplit('/', 1)[1]} is a valid Office file")
    sign_in(c2 := TestClient(main.app), "d.user@vitrodc.com")
    check(c2.get(job_url).status_code == 404 and c2.get(links[0]).status_code == 404,
          "another user cannot see the run or its files")
    check(c.get(job_url + "/files/..%2Fapp.db").status_code == 404, "file path outside the run refused")
    bad = c.post("/jobs", data={"csrf": csrf_of(c.get("/home").text)},
                 files=[("files", ("x.pdf", b"not a pdf", "application/pdf"))])
    check(bad.status_code == 400, "non-PDF content refused")

print(f"\nAll {ok_count} checks passed. Data in {tmp}")
