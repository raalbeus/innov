"""Settings, read from environment variables (or a .env file next to the app).

Every external dependency has a local mode so the app can run before IT
provides credentials:
  MAIL_MODE    console  -> OTP is written to the server log (development only)
               graph    -> OTP is emailed from MAIL_SENDER via Microsoft Graph
  SOURCE_MODE  local    -> reference files are read from LOCAL_REF_DIR
               sharepoint -> reference files are read from a SharePoint folder via Microsoft Graph
  AI_MODE      claude   -> Claude API (ANTHROPIC_API_KEY)
               replay   -> reuses saved AI outputs from REPLAY_DIR (testing the app without an API key)
"""
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def _load_dotenv():
    f = BASE / ".env"
    if not f.exists():
        return
    for line in f.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def env(name, default=None):
    return os.environ.get(name, default)


APP_NAME = "VITRO Bid Qualification"
DATA_DIR = Path(env("DATA_DIR", BASE / "data"))
ENGINE_DIR = BASE / "engine"
SCRIPTS_DIR = ENGINE_DIR / "scripts"
MEMO_TEMPLATE = ENGINE_DIR / "templates" / "VITRO_Memo_Template.docx"
BLANK_REGISTER = ENGINE_DIR / "templates" / "VITRO_Reference_Register.xlsx"

# Session and sign-in
SESSION_SECRET = env("SESSION_SECRET")  # required; long random string
SESSION_HOURS = int(env("SESSION_HOURS", "8"))
COOKIE_SECURE = env("COOKIE_SECURE", "true").lower() == "true"  # set false only for local http testing
ALLOWED_DOMAINS = [d.strip().lower() for d in env("ALLOWED_DOMAINS", "vitrodc.com").split(",") if d.strip()]
# Extra addresses outside the allowed domains (e.g. a named person on a personal account). Set in the
# environment or the hosting platform's secrets, never in the repository.
ALLOWED_EMAILS = {e.strip().lower() for e in env("ALLOWED_EMAILS", "").split(",") if e.strip()}
# Who may replace the reference files from the app (local reference folder only).
ADMIN_EMAILS = {e.strip().lower() for e in env("ADMIN_EMAILS", "").split(",") if e.strip()}
# Sandbox testing only: skip sign-in and act as TEST_USER. Refused unless MAIL_MODE=console.
SKIP_LOGIN = env("SKIP_LOGIN", "false").lower() == "true"
TEST_USER = env("TEST_USER", "tester@vitrodc.com").strip().lower()
OTP_TTL_MIN = int(env("OTP_TTL_MIN", "10"))
OTP_MAX_ATTEMPTS = int(env("OTP_MAX_ATTEMPTS", "5"))
OTP_MAX_SENDS_PER_15MIN = int(env("OTP_MAX_SENDS_PER_15MIN", "3"))

# Microsoft 365 (Entra ID app registration, client-credentials flow)
GRAPH_TENANT_ID = env("GRAPH_TENANT_ID")
GRAPH_CLIENT_ID = env("GRAPH_CLIENT_ID")
GRAPH_CLIENT_SECRET = env("GRAPH_CLIENT_SECRET")

MAIL_MODE = env("MAIL_MODE", "console")
MAIL_SENDER = env("MAIL_SENDER")  # e.g. bidtool@vitrodc.com

SOURCE_MODE = env("SOURCE_MODE", "local")
LOCAL_REF_DIR = Path(env("LOCAL_REF_DIR", DATA_DIR / "reference"))
SHAREPOINT_HOST = env("SHAREPOINT_HOST")  # e.g. vitrodc.sharepoint.com
SHAREPOINT_SITE_PATH = env("SHAREPOINT_SITE_PATH")  # e.g. /sites/Solutions
SHAREPOINT_FOLDER = env("SHAREPOINT_FOLDER")  # e.g. Bid Qualification/Reference
SPEC_PATTERN = env("SPEC_PATTERN", "VITRO_Specifications_Table")
REGISTER_PATTERN = env("REGISTER_PATTERN", "VITRO_Reference_Register")

# AI
AI_MODE = env("AI_MODE", "claude")
CLAUDE_MODEL = env("CLAUDE_MODEL", "claude-opus-5-5")
CLAUDE_EFFORT = env("CLAUDE_EFFORT", "high")
REPLAY_DIR = Path(env("REPLAY_DIR", DATA_DIR / "replay"))

MAX_UPLOAD_MB = int(env("MAX_UPLOAD_MB", "200"))


def check():
    """Return a list of configuration problems that stop the app from starting safely."""
    problems = []
    if not SESSION_SECRET or len(SESSION_SECRET) < 32:
        problems.append("SESSION_SECRET must be set to a random string of at least 32 characters.")
    if MAIL_MODE == "graph" and not all([GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET, MAIL_SENDER]):
        problems.append("MAIL_MODE=graph needs GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET and MAIL_SENDER.")
    if SOURCE_MODE == "sharepoint" and not all([GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET,
                                                 SHAREPOINT_HOST, SHAREPOINT_SITE_PATH, SHAREPOINT_FOLDER]):
        problems.append("SOURCE_MODE=sharepoint needs the GRAPH_* settings and SHAREPOINT_HOST, "
                        "SHAREPOINT_SITE_PATH, SHAREPOINT_FOLDER.")
    if AI_MODE == "claude" and not (env("ANTHROPIC_API_KEY") or env("ANTHROPIC_AUTH_TOKEN")):
        problems.append("AI_MODE=claude needs ANTHROPIC_API_KEY.")
    if SKIP_LOGIN and MAIL_MODE != "console":
        problems.append("SKIP_LOGIN=true is for sandbox testing only and needs MAIL_MODE=console. "
                        "Remove SKIP_LOGIN in production.")
    if MAIL_MODE not in ("console", "graph"):
        problems.append("MAIL_MODE must be console or graph.")
    if SOURCE_MODE not in ("local", "sharepoint"):
        problems.append("SOURCE_MODE must be local or sharepoint.")
    if AI_MODE not in ("claude", "replay"):
        problems.append("AI_MODE must be claude or replay.")
    return problems


def warnings():
    """Settings that are allowed but must not reach production."""
    w = []
    if SKIP_LOGIN:
        w.append(f"SKIP_LOGIN=true: sign-in is off. Anyone who can open this address works as {TEST_USER}. "
                 "Sandbox testing only.")
    if MAIL_MODE == "console":
        w.append("MAIL_MODE=console: sign-in codes are written to the server log. Development only.")
    if not COOKIE_SECURE:
        w.append("COOKIE_SECURE=false: session cookie is sent over plain http. Development only.")
    if AI_MODE == "replay":
        w.append("AI_MODE=replay: results come from saved test outputs, not from the uploaded documents.")
    return w
