"""Email one-time-password (OTP) sign-in.

- Only addresses in ALLOWED_DOMAINS can request a code.
- Codes are 6 digits from `secrets`, stored only as an HMAC (keyed with
  SESSION_SECRET), valid for OTP_TTL_MIN minutes, single use.
- At most OTP_MAX_ATTEMPTS wrong entries per code, and OTP_MAX_SENDS_PER_15MIN
  codes per address per 15 minutes.
- Requesting a new code voids earlier unused codes for that address.
"""
import hashlib
import hmac
import re
import secrets
import time

from . import config, db

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$")


def normalize(email):
    return (email or "").strip().lower()


def domain_allowed(email):
    """True for an address in ALLOWED_DOMAINS or listed in ALLOWED_EMAILS."""
    if not EMAIL_RE.match(email):
        return False
    return email.rsplit("@", 1)[1] in config.ALLOWED_DOMAINS or email in config.ALLOWED_EMAILS


def is_admin(email):
    return bool(email) and email in config.ADMIN_EMAILS


def _hash(email, code):
    key = (config.SESSION_SECRET or "").encode()
    return hmac.new(key, f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


def issue_code(email):
    """Return (code, error). The caller sends the code; error is a user-facing message."""
    now = time.time()
    with db.conn() as c:
        recent = c.execute("SELECT COUNT(*) FROM otp WHERE email=? AND created>?", (email, now - 900)).fetchone()[0]
        if recent >= config.OTP_MAX_SENDS_PER_15MIN:
            return None, "Too many codes requested. Wait 15 minutes and try again."
        c.execute("UPDATE otp SET used=1 WHERE email=? AND used=0", (email,))
        code = f"{secrets.randbelow(1_000_000):06d}"
        c.execute("INSERT INTO otp(email, code_hash, created, expires) VALUES (?,?,?,?)",
                  (email, _hash(email, code), now, now + config.OTP_TTL_MIN * 60))
    return code, None


def verify_code(email, code):
    """Return (ok, error)."""
    code = re.sub(r"\D", "", code or "")
    now = time.time()
    with db.conn() as c:
        row = c.execute("SELECT rowid, * FROM otp WHERE email=? AND used=0 ORDER BY created DESC LIMIT 1",
                        (email,)).fetchone()
        if row is None or row["expires"] < now:
            return False, "The code has expired or was not requested. Request a new code."
        if row["attempts"] >= config.OTP_MAX_ATTEMPTS:
            c.execute("UPDATE otp SET used=1 WHERE rowid=?", (row["rowid"],))
            return False, "Too many wrong attempts. Request a new code."
        if len(code) != 6 or not hmac.compare_digest(row["code_hash"], _hash(email, code)):
            c.execute("UPDATE otp SET attempts=attempts+1 WHERE rowid=?", (row["rowid"],))
            left = config.OTP_MAX_ATTEMPTS - row["attempts"] - 1
            return False, f"Incorrect code. {left} attempt(s) left." if left > 0 else \
                "Too many wrong attempts. Request a new code."
        c.execute("UPDATE otp SET used=1 WHERE rowid=?", (row["rowid"],))
    return True, None


def new_csrf(session):
    session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]


def check_csrf(session, token):
    return bool(token) and hmac.compare_digest(session.get("csrf", ""), token)


def current_user(request):
    s = request.session
    if not s.get("email") or s.get("expires", 0) < time.time():
        return None
    return s["email"]


def sign_in(request, email):
    request.session.clear()
    request.session["email"] = email
    request.session["expires"] = time.time() + config.SESSION_HOURS * 3600
    new_csrf(request.session)
