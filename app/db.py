"""SQLite storage: sign-in codes, Specifications Tables, jobs and the audit log."""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager

from . import config

_lock = threading.Lock()
DB_PATH = config.DATA_DIR / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS otp (
  email TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  created REAL NOT NULL,
  expires REAL NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  used INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS otp_email ON otp(email, created);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  owner TEXT NOT NULL,
  title TEXT,
  created REAL NOT NULL,
  status TEXT NOT NULL,          -- queued, running, done, failed
  step TEXT,
  progress INTEGER DEFAULT 0,
  error TEXT,
  reference TEXT,                -- JSON: spec and register file names and dates used
  result TEXT                    -- JSON: verdict, recommended site, file names
);
CREATE TABLE IF NOT EXISTS specs (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,            -- original file name
  sha256 TEXT NOT NULL,
  source TEXT NOT NULL,          -- "upload" or "reference folder"
  uploaded_by TEXT NOT NULL,
  uploaded REAL NOT NULL,
  summary TEXT NOT NULL          -- JSON: sites, row counts, blank cells
);
CREATE INDEX IF NOT EXISTS specs_sha ON specs(sha256);
CREATE TABLE IF NOT EXISTS audit (
  ts REAL NOT NULL,
  email TEXT,
  action TEXT NOT NULL,
  detail TEXT
);
"""


@contextmanager
def conn():
    with _lock:
        c = sqlite3.connect(DB_PATH)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()


def init():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with conn() as c:
        c.executescript(SCHEMA)


def audit(email, action, detail=None):
    with conn() as c:
        c.execute("INSERT INTO audit(ts, email, action, detail) VALUES (?,?,?,?)",
                  (time.time(), email, action, json.dumps(detail) if detail is not None else None))


def spec_add(spec_id, name, sha256, source, uploaded_by, summary):
    with conn() as c:
        c.execute("INSERT INTO specs(id, name, sha256, source, uploaded_by, uploaded, summary) VALUES (?,?,?,?,?,?,?)",
                  (spec_id, name, sha256, source, uploaded_by, time.time(), json.dumps(summary)))


def spec_get(spec_id):
    with conn() as c:
        r = c.execute("SELECT * FROM specs WHERE id=?", (spec_id,)).fetchone()
    return _spec(r)


def spec_by_sha(sha256, name):
    with conn() as c:
        r = c.execute("SELECT * FROM specs WHERE sha256=? AND name=? ORDER BY uploaded DESC LIMIT 1",
                      (sha256, name)).fetchone()
    return _spec(r)


def specs_recent(limit=5):
    with conn() as c:
        rows = c.execute("SELECT * FROM specs ORDER BY uploaded DESC LIMIT ?", (limit,)).fetchall()
    return [_spec(r) for r in rows]


def _spec(r):
    if r is None:
        return None
    d = dict(r)
    d["summary"] = json.loads(d["summary"])
    return d


def job_create(job_id, owner, title):
    with conn() as c:
        c.execute("INSERT INTO jobs(id, owner, title, created, status, step, progress) VALUES (?,?,?,?,?,?,?)",
                  (job_id, owner, title, time.time(), "queued", "Queued", 0))


def job_update(job_id, **fields):
    for k in ("reference", "result"):
        if k in fields and not isinstance(fields[k], str):
            fields[k] = json.dumps(fields[k])
    cols = ", ".join(f"{k}=?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))


def job_get(job_id):
    with conn() as c:
        r = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return _job(r)


def jobs_for(owner, limit=50):
    with conn() as c:
        rows = c.execute("SELECT * FROM jobs WHERE owner=? ORDER BY created DESC LIMIT ?", (owner, limit)).fetchall()
    return [_job(r) for r in rows]


def jobs_mark_interrupted():
    """Jobs left running when the server stopped cannot resume; mark them failed."""
    with conn() as c:
        c.execute("UPDATE jobs SET status='failed', error='Server restarted while this job was running. "
                  "Start it again.' WHERE status IN ('queued','running')")


def _job(r):
    if r is None:
        return None
    d = dict(r)
    for k in ("reference", "result"):
        d[k] = json.loads(d[k]) if d.get(k) else None
    return d
