"""VITRO Bid Qualification web app.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8000   (behind HTTPS in production)
"""
import logging
import re
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import auth, config, db, mailer, pipeline, refsource, specstore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bidapp")

problems = config.check()
if problems:
    raise SystemExit("Configuration problems:\n- " + "\n- ".join(problems))
for w in config.warnings():
    log.warning(w)

db.init()
db.jobs_mark_interrupted()
executor = ThreadPoolExecutor(max_workers=2)
HERE = Path(__file__).parent
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.globals.update(app_name=config.APP_NAME, warnings=config.warnings(),
                             domains=config.ALLOWED_DOMAINS)


def verdict_class(v):
    if v in ("Go", "Pass", "Comply"):
        return "green"
    if v in ("No-Go", "Fail", "Gap"):
        return "red"
    if v in ("Partner scope", "N/A", "Not required", None, ""):
        return "neutral"
    return "amber"


templates.env.filters["verdict_class"] = verdict_class
templates.env.filters["ts"] = lambda t: time.strftime("%Y-%m-%d %H:%M", time.localtime(t))

app = FastAPI(title=config.APP_NAME, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET, session_cookie="bq_session",
                   max_age=config.SESSION_HOURS * 3600, same_site="lax", https_only=config.COOKIE_SECURE)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data:; style-src 'self'; "
                                               "script-src 'self'; frame-ancestors 'none'; form-action 'self'")
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Cache-Control"] = "no-store"
    return resp


def page(request, name, **ctx):
    if "csrf" not in request.session:
        auth.new_csrf(request.session)
    return templates.TemplateResponse(request, name, {"csrf": request.session["csrf"],
                                                      "user": auth.current_user(request), **ctx})


def require_user(request):
    user = auth.current_user(request)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def require_csrf(request, token):
    if not auth.check_csrf(request.session, token):
        raise HTTPException(status_code=400, detail="Form expired. Reload the page and try again.")


# ------------------------------------------------------------------ sign-in
@app.get("/", include_in_schema=False)
def root(request: Request):
    return RedirectResponse("/home" if auth.current_user(request) else "/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return page(request, "login.html")


@app.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, email: str = Form(...), csrf: str = Form("")):
    require_csrf(request, csrf)
    email = auth.normalize(email)
    if not auth.domain_allowed(email):
        db.audit(email, "login_rejected_domain")
        return page(request, "login.html", error="This address cannot sign in. Use your company email ("
                    + ", ".join("@" + d for d in config.ALLOWED_DOMAINS)
                    + ") or ask the administrator to add your address.", email=email)
    code, err = auth.issue_code(email)
    if err:
        db.audit(email, "otp_rate_limited")
        return page(request, "login.html", error=err, email=email)
    try:
        mailer.send_code(email, code)
    except Exception as e:
        log.error("OTP email to %s failed: %s", email, e)
        return page(request, "login.html", error="The sign-in email could not be sent. Try again or contact IT.",
                    email=email)
    db.audit(email, "otp_sent")
    request.session["pending_email"] = email
    return RedirectResponse("/verify", status_code=303)


@app.get("/verify", response_class=HTMLResponse)
def verify_form(request: Request):
    if not request.session.get("pending_email"):
        return RedirectResponse("/login", status_code=303)
    return page(request, "verify.html", email=request.session["pending_email"], ttl=config.OTP_TTL_MIN)


@app.post("/verify", response_class=HTMLResponse)
def verify_submit(request: Request, code: str = Form(...), csrf: str = Form("")):
    require_csrf(request, csrf)
    email = request.session.get("pending_email")
    if not email:
        return RedirectResponse("/login", status_code=303)
    ok, err = auth.verify_code(email, code)
    if not ok:
        db.audit(email, "otp_failed")
        return page(request, "verify.html", email=email, ttl=config.OTP_TTL_MIN, error=err)
    auth.sign_in(request, email)
    db.audit(email, "login")
    return RedirectResponse("/home", status_code=303)


@app.post("/logout")
def logout(request: Request, csrf: str = Form("")):
    require_csrf(request, csrf)
    db.audit(auth.current_user(request), "logout")
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ------------------------------------------------------------------ app
# Flow: 1 sign in -> 2 confirm a Specifications Table -> 3 upload the bid documents.
def confirmed_spec(request):
    """The Specifications Table this user confirmed in step 2, or None."""
    spec = specstore.get(request.session.get("spec_id"))
    if not spec:
        request.session.pop("spec_id", None)
    return spec


@app.get("/home", response_class=HTMLResponse)
def home(request: Request):
    user = require_user(request)
    return page(request, "home.html", step=1, spec=confirmed_spec(request), jobs=db.jobs_for(user),
                note=request.session.pop("note", None))


@app.get("/spec", response_class=HTMLResponse)
def spec_page(request: Request):
    """Step 2: upload a Specifications Table or reuse a recent one."""
    require_user(request)
    ref = refsource.status()
    return page(request, "spec.html", step=2, spec=confirmed_spec(request), recent=db.specs_recent(5), ref=ref,
                max_mb=specstore.MAX_SPEC_MB, note=request.session.pop("note", None),
                error=request.session.pop("spec_error", None))


@app.post("/spec")
async def spec_upload(request: Request, file: UploadFile = File(...), csrf: str = Form("")):
    user = require_user(request)
    require_csrf(request, csrf)
    data = await file.read(specstore.MAX_SPEC_MB * 1024 * 1024 + 1)
    try:
        spec = specstore.add(data, file.filename, user)
    except specstore.SpecError as e:
        db.audit(user, "spec_rejected", {"file": specstore.safe_name(file.filename), "reason": str(e)})
        request.session["spec_error"] = str(e)
        return RedirectResponse("/spec", status_code=303)
    db.audit(user, "spec_uploaded", {"spec": spec["id"], "file": spec["name"], "sha256": spec["sha256"]})
    return RedirectResponse(f"/spec/{spec['id']}", status_code=303)


@app.post("/spec/import")
def spec_import(request: Request, csrf: str = Form("")):
    """Use the latest Specifications Table in the reference folder (it is copied and checked like an upload)."""
    user = require_user(request)
    require_csrf(request, csrf)
    st = refsource.status()
    if not st.get("spec"):
        raise HTTPException(404, "There is no Specifications Table in the reference folder.")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        f = refsource.fetch(st["spec"], Path(tmp))
        try:
            spec = specstore.add(f.read_bytes(), f.name, user, source="reference folder")
        except specstore.SpecError as e:
            request.session["spec_error"] = f"{st['spec']['name']}: {e}"
            return RedirectResponse("/spec", status_code=303)
    db.audit(user, "spec_imported", {"spec": spec["id"], "file": spec["name"]})
    return RedirectResponse(f"/spec/{spec['id']}", status_code=303)


@app.get("/spec/{spec_id}", response_class=HTMLResponse)
def spec_review(request: Request, spec_id: str):
    """Summary of a table for the user to check before confirming it."""
    require_user(request)
    spec = specstore.get(spec_id)
    if not spec:
        raise HTTPException(404, "Not found.")
    current = confirmed_spec(request)
    return page(request, "spec_review.html", step=2, s=spec, confirmed=bool(current and current["id"] == spec_id))


@app.post("/spec/{spec_id}/confirm")
def spec_confirm(request: Request, spec_id: str, csrf: str = Form("")):
    user = require_user(request)
    require_csrf(request, csrf)
    spec = specstore.get(spec_id)
    if not spec:
        raise HTTPException(404, "Not found.")
    request.session["spec_id"] = spec_id
    db.audit(user, "spec_confirmed", {"spec": spec_id, "file": spec["name"]})
    return RedirectResponse("/bid", status_code=303)


@app.get("/spec/{spec_id}/file")
def spec_file(request: Request, spec_id: str):
    user = require_user(request)
    spec = specstore.get(spec_id)
    if not spec:
        raise HTTPException(404, "Not found.")
    db.audit(user, "spec_download", {"spec": spec_id})
    return FileResponse(specstore.path_of(spec), filename=spec["name"])


@app.get("/bid", response_class=HTMLResponse)
def bid_page(request: Request):
    """Step 3: upload the bid documents. Locked until a Specifications Table is confirmed."""
    user = require_user(request)
    spec = confirmed_spec(request)
    if not spec:
        request.session["note"] = "Confirm a Specifications Table before uploading the bid documents."
        return RedirectResponse("/spec", status_code=303)
    return page(request, "bid.html", step=3, spec=spec, ref=refsource.status(), max_mb=config.MAX_UPLOAD_MB,
                admin=auth.is_admin(user) and config.SOURCE_MODE == "local", note=request.session.pop("note", None))


@app.post("/reference")
async def upload_reference(request: Request, file: UploadFile = File(...), csrf: str = Form("")):
    """Admins replace the Reference Register (local reference folder only)."""
    user = require_user(request)
    require_csrf(request, csrf)
    if not auth.is_admin(user) or config.SOURCE_MODE != "local":
        raise HTTPException(403, "Only administrators can change the Reference Register.")
    name = specstore.safe_name(file.filename)
    data = await file.read()
    if not name.lower().endswith(".xlsx") or not data.startswith(b"PK"):
        raise HTTPException(400, "Upload the Reference Register as an Excel .xlsx file.")
    if not name.lower().startswith(config.REGISTER_PATTERN.lower()):
        raise HTTPException(400, f"The file name must start with {config.REGISTER_PATTERN} so the app can find it.")
    import tempfile
    from openpyxl import load_workbook
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / name
        f.write_bytes(data)
        try:
            load_workbook(f, read_only=True)
        except Exception:
            raise HTTPException(400, "This file could not be read as an Excel workbook.")
    config.LOCAL_REF_DIR.mkdir(parents=True, exist_ok=True)
    (config.LOCAL_REF_DIR / name).write_bytes(data)
    db.audit(user, "reference_uploaded", {"kind": "register", "file": name})
    request.session["note"] = f"{name} is now the Reference Register."
    return RedirectResponse("/bid", status_code=303)


@app.post("/jobs")
async def create_job(request: Request, files: list[UploadFile] = File(...), title: str = Form(""),
                     csrf: str = Form(""), spec_id: str = Form("")):
    user = require_user(request)
    require_csrf(request, csrf)
    spec = confirmed_spec(request)
    if not spec:
        raise HTTPException(409, "Confirm a Specifications Table (step 2) before starting a qualification.")
    if spec_id and spec_id != spec["id"]:
        raise HTTPException(409, "The Specifications Table changed in another tab. Reload this page and try again.")
    job_id = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
    up = config.DATA_DIR / "jobs" / job_id / "upload"
    up.mkdir(parents=True, exist_ok=True)
    total, saved = 0, []
    for f in files:
        name = re.sub(r"[^A-Za-z0-9._ ()-]+", "_", Path(f.filename or "file.pdf").name)[:120]
        if not name.lower().endswith(".pdf"):
            continue
        data = await f.read()
        total += len(data)
        if total > config.MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(413, f"Upload exceeds {config.MAX_UPLOAD_MB} MB.")
        if not data.startswith(b"%PDF"):
            raise HTTPException(400, f"{name} is not a PDF.")
        (up / name).write_bytes(data)
        saved.append(name)
    if not saved:
        raise HTTPException(400, "Upload the bid documents as PDF files.")
    db.job_create(job_id, user, title.strip()[:120] or saved[0])
    db.audit(user, "job_started", {"job": job_id, "files": saved, "spec": spec["id"]})
    executor.submit(pipeline.run, job_id, user, up, title.strip(), spec)
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


def own_job(request, job_id):
    user = require_user(request)
    job = db.job_get(job_id)
    if not job or job["owner"] != user:
        raise HTTPException(404, "Not found.")
    return user, job


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: str):
    _, job = own_job(request, job_id)
    return page(request, "job.html", job=job)


@app.get("/jobs/{job_id}/status")
def job_status(request: Request, job_id: str):
    _, job = own_job(request, job_id)
    return JSONResponse({k: job[k] for k in ("status", "step", "progress", "error")})


@app.get("/jobs/{job_id}/files/{name}")
def job_file(request: Request, job_id: str, name: str):
    user, job = own_job(request, job_id)
    files = (job.get("result") or {}).get("files", {})
    if name not in files.values():
        raise HTTPException(404, "Not found.")
    db.audit(user, "download", {"job": job_id, "file": name})
    return FileResponse(config.DATA_DIR / "jobs" / job_id / "output" / name, filename=name)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    if exc.status_code == 303:
        return RedirectResponse(exc.headers["Location"], status_code=303)
    resp = page(request, "error.html", status=exc.status_code, message=exc.detail)
    resp.status_code = exc.status_code
    return resp
