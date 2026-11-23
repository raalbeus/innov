"""The reference folder: the VITRO Specifications Table and the Reference Register.

The latest file matching each pattern (by modified date) is used and cached
locally; the file name and modified date are recorded with every job.
"""
import datetime as dt
import json
import shutil
from urllib.parse import quote

from . import config

CACHE = config.DATA_DIR / "refcache"


def _pick(files, pattern):
    hits = [f for f in files if f["name"].lower().startswith(pattern.lower()) and f["name"].lower().endswith(".xlsx")
            and not f["name"].startswith("~$")]
    return max(hits, key=lambda f: f["modified"]) if hits else None


def list_folder():
    """Return [{name, modified (ISO), size, id/path}] for .xlsx files in the reference folder."""
    if config.SOURCE_MODE == "local":
        d = config.LOCAL_REF_DIR
        if not d.exists():
            return []
        return [{"name": p.name, "path": str(p), "size": p.stat().st_size,
                 "modified": dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc).isoformat()}
                for p in d.iterdir() if p.is_file()]
    from . import graph

    site = graph.get(f"/sites/{config.SHAREPOINT_HOST}:{config.SHAREPOINT_SITE_PATH}").json()
    folder = quote(config.SHAREPOINT_FOLDER.strip("/"))
    items = graph.get(f"/sites/{site['id']}/drive/root:/{folder}:/children").json().get("value", [])
    return [{"name": i["name"], "id": i["id"], "site": site["id"], "size": i.get("size", 0),
             "modified": i.get("lastModifiedDateTime"), "web_url": i.get("webUrl")}
            for i in items if "file" in i]


def status():
    """What the app will use right now. Never raises; errors are reported."""
    try:
        files = list_folder()
    except Exception as e:  # network, permission or configuration problems
        return {"ok": False, "error": f"Cannot read the reference folder: {e}", "location": location()}
    spec, reg = _pick(files, config.SPEC_PATTERN), _pick(files, config.REGISTER_PATTERN)
    return {"ok": spec is not None, "location": location(), "spec": spec, "register": reg,
            "error": None if spec else f"No file starting with '{config.SPEC_PATTERN}' found in the folder."}


def location():
    if config.SOURCE_MODE == "local":
        return f"Local folder {config.LOCAL_REF_DIR}"
    return f"SharePoint {config.SHAREPOINT_HOST}{config.SHAREPOINT_SITE_PATH} / {config.SHAREPOINT_FOLDER}"


def fetch(item, dest_dir):
    """Download (or copy) one reference file into dest_dir; return its local path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / item["name"]
    if config.SOURCE_MODE == "local":
        shutil.copy2(item["path"], out)
        return out
    from . import graph

    r = graph.get(f"/sites/{item['site']}/drive/items/{item['id']}/content", stream=True)
    with open(out, "wb") as fh:
        for chunk in r.iter_content(1 << 16):
            fh.write(chunk)
    (dest_dir / (item["name"] + ".meta.json")).write_text(json.dumps(item))
    return out
