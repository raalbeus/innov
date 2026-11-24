"""Specifications Tables uploaded in step 2 of the flow.

Any signed-in user can upload a table. Each file is checked with read_specs.py, stored once
(identical files are reused), summarised, and recorded with every run that uses it.
"""
import collections
import hashlib
import json
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import config, db

STORE = config.DATA_DIR / "specs"
MAX_SPEC_MB = 25


class SpecError(Exception):
    """The file cannot be used as the VITRO Specifications Table. The message is shown to the user."""


def safe_name(name):
    return re.sub(r"[^A-Za-z0-9._ ()-]+", "_", Path(name or "").name)[:120] or "specifications.xlsx"


def read(path, out_dir):
    """Run read_specs.py on path; return specs.json as a dict. Raises SpecError if unreadable."""
    try:
        r = subprocess.run([sys.executable, str(config.SCRIPTS_DIR / "read_specs.py"), str(path), str(out_dir)],
                           cwd=config.SCRIPTS_DIR, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        raise SpecError("Reading this file took too long. Check that it is the Specifications Table.")
    f = Path(out_dir) / "specs.json"
    if r.returncode != 0 or not f.exists():
        raise SpecError("This file could not be read as the VITRO Specifications Table. "
                        "Upload the .xlsx with site names in row 1 from column H.")
    return json.loads(f.read_text())


def summarise(specs):
    """Counts shown to the user before they confirm the table."""
    rows = specs["rows"]
    sites = specs["sites"]
    filled = collections.Counter()
    for row in rows:
        for site, c in row["cells"].items():
            if c["status"] != "Blank":
                filled[site] += 1
    sections = collections.Counter(r["section"] or "General" for r in rows)
    return {
        "sheet": specs["source"].get("sheet"),
        "sites": [{"name": s["name"], "city": s.get("city", ""), "ownership": s.get("ownership", ""),
                   "filled": filled[s["name"]], "blank": len(rows) - filled[s["name"]]} for s in sites],
        "rows": len(rows),
        "sections": [{"name": k, "rows": v} for k, v in sections.items()],
    }


def add(data, name, user, source="upload"):
    """Validate and store a table. Returns the spec record (an existing one if the file is identical)."""
    name = safe_name(name)
    if not name.lower().endswith(".xlsx") or not data.startswith(b"PK"):
        raise SpecError("Upload the Specifications Table as an Excel .xlsx file.")
    if len(data) > MAX_SPEC_MB * 1024 * 1024:
        raise SpecError(f"The file is larger than {MAX_SPEC_MB} MB.")
    sha = hashlib.sha256(data).hexdigest()
    existing = db.spec_by_sha(sha, name)
    if existing and path_of(existing).exists():
        return existing
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / name
        f.write_bytes(data)
        specs = read(f, tmp)
    if not specs["sites"]:
        raise SpecError("No data center sites were found. Site names must be in row 1, from column H.")
    if not specs["rows"]:
        raise SpecError("No specification rows were found under the site columns.")
    spec_id = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
    d = STORE / spec_id
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(data)
    db.spec_add(spec_id, name, sha, source, user, summarise(specs))
    return db.spec_get(spec_id)


def path_of(spec):
    return STORE / spec["id"] / spec["name"]


def get(spec_id):
    """The stored record, or None if the id is unknown or its file is missing."""
    if not spec_id or not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{6}", spec_id):
        return None
    spec = db.spec_get(spec_id)
    return spec if spec and path_of(spec).exists() else None


def copy_to(spec, dest_dir):
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / spec["name"]
    shutil.copy2(path_of(spec), out)
    return out
