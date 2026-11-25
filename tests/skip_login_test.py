"""SKIP_LOGIN (sandbox testing): the app opens without sign-in, and the setting is refused outside sandbox mode.

Run:  python3 tests/skip_login_test.py
"""
import os
import re
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp(prefix="bq-skip-"))
fx = tmp / "fixtures"
subprocess.run([sys.executable, str(ROOT / "tests" / "make_sample_fixtures.py"), str(fx)], check=True, capture_output=True)
base = {"SESSION_SECRET": secrets.token_urlsafe(48), "COOKIE_SECURE": "false", "SOURCE_MODE": "local",
        "AI_MODE": "replay", "DATA_DIR": str(tmp / "data"), "LOCAL_REF_DIR": str(tmp / "ref"),
        "REPLAY_DIR": str(fx / "replay"), "SKIP_LOGIN": "true"}

# refused outside sandbox mail mode
env = {**os.environ, **base, "MAIL_MODE": "graph", "GRAPH_TENANT_ID": "x", "GRAPH_CLIENT_ID": "x",
       "GRAPH_CLIENT_SECRET": "x", "MAIL_SENDER": "x@vitrodc.com"}
r = subprocess.run([sys.executable, "-c", "from app import main"], cwd=ROOT, env=env, capture_output=True, text=True)
assert r.returncode != 0 and "SKIP_LOGIN=true is for sandbox testing only" in (r.stderr + r.stdout), r.stderr[-500:]
print("  ok  SKIP_LOGIN refused with MAIL_MODE=graph")

os.environ.update({**base, "MAIL_MODE": "console"})
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402

c = TestClient(main.app)
r = c.get("/", follow_redirects=True)
assert r.url.path == "/home" and "tester@vitrodc.com" in r.text and "SKIP_LOGIN=true" in r.text, r.url
print("  ok  opens on home as the test user, with the test-mode banner")
assert c.get("/login", follow_redirects=False).headers["location"] == "/home"
print("  ok  sign-in page redirects to home")
assert "Sign out" not in r.text
print("  ok  no sign-out link")
assert c.get("/bid", follow_redirects=False).headers["location"] == "/spec"
print("  ok  step 3 still locked until a table is confirmed")
spec = next(fx.glob("*.xlsx"))
tok = re.search(r'name="csrf" value="([^"]+)"', c.get("/spec").text).group(1)
r = c.post("/spec", data={"csrf": tok}, files={"file": (spec.name, spec.read_bytes(), "application/octet-stream")},
           follow_redirects=False)
review = r.headers["location"]
tok = re.search(r'name="csrf" value="([^"]+)"', c.get(review).text).group(1)
assert c.post(review + "/confirm", data={"csrf": tok}, follow_redirects=False).headers["location"] == "/bid"
assert c.get("/bid").status_code == 200
print("  ok  upload and confirm the table without signing in")
print("All SKIP_LOGIN checks passed.")
