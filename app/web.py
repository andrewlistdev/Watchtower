"""Admin GUI: first-run setup, sign-in, settings (secrets), people, dashboard."""

from __future__ import annotations

import logging
import os
import re
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   session, url_for)

from .config import Config, ConfigMissing
from .runtime import check_connections, data_dir, shift_view, short_error
from .settings_store import FIELDS, FIELDS_BY_KEY, SECTIONS, SettingsStore
from .state import State
from .worker import Worker

log = logging.getLogger("web")

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
USERNAME_RE = re.compile(r"^[a-zA-Z0-9._@-]{3,64}$")
MIN_PASSWORD = 12
PUBLIC_ENDPOINTS = {"static", "healthz", "login", "setup"}

STATE_LABELS = {
    "creating": "Check SDP: outcome unknown",
    "failed_create": "Couldn't create in SDP",
    "open": "Open in SDP",
    "aw_closed": "Closed",
}


def _session_key() -> bytes:
    path = os.path.join(data_dir(), "session.key")
    if os.path.exists(path):
        with open(path, "rb") as fh:
            return fh.read()
    key = secrets.token_bytes(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key)
    return key


class LoginThrottle:
    """Five failed sign-ins from one address within 10 minutes locks it out for 5."""

    def __init__(self):
        self.fails: dict[str, list[float]] = defaultdict(list)

    def blocked(self, ip: str) -> int:
        now = time.monotonic()
        recent = [t for t in self.fails[ip] if now - t < 600]
        self.fails[ip] = recent
        if len(recent) >= 5:
            return int(300 - (now - recent[-1])) if now - recent[-1] < 300 else 0
        return 0

    def fail(self, ip: str) -> None:
        self.fails[ip].append(time.monotonic())

    def clear(self, ip: str) -> None:
        self.fails.pop(ip, None)


def create_app(store: SettingsStore, worker: Worker | None, db_path: str) -> Flask:
    app = Flask(__name__)
    app.secret_key = _session_key()
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "").lower() in {"1", "true", "yes"},
        SESSION_COOKIE_NAME="relay_session",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    throttle = LoginThrottle()
    setup_state = {"token": None}

    def setup_token() -> str:
        if setup_state["token"] is None:
            setup_state["token"] = secrets.token_urlsafe(18)
            log.warning("=" * 64)
            log.warning("No admin account yet. Open the admin page and use this setup code:")
            log.warning("    %s", setup_state["token"])
            log.warning("=" * 64)
        return setup_state["token"]

    app.extensions["setup_token"] = setup_token

    # ---- helpers ----------------------------------------------------------

    def tz() -> ZoneInfo:
        try:
            return ZoneInfo(store.resolved("display_timezone") or "UTC")
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo("UTC")

    def local(dt: datetime | str | None, fmt: str = "%b %-d, %-I:%M %p") -> str:
        if not dt:
            return ""
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        return dt.astimezone(tz()).strftime(fmt)

    def ago(dt: datetime | None) -> str:
        if not dt:
            return "never"
        secs = int((datetime.now(timezone.utc) - dt).total_seconds())
        if secs < 90:
            return "just now"
        if secs < 5400:
            mins = secs // 60
            return f"{mins} minute{'s' if mins != 1 else ''} ago"
        return local(dt)

    def tidy_error(text: str | None) -> str:
        """Pull the human-readable message out of an API error body when there is one."""
        if not text:
            return ""
        messages = re.findall(r'"message"\s*:\s*"([^"]+)"', text)
        service = text.split(" ", 1)[0] if text[:1].isalpha() else ""
        if messages:
            return f"{service} said: " + "; ".join(dict.fromkeys(messages))
        return text[:200]

    app.jinja_env.filters["local"] = local
    app.jinja_env.filters["tidy_error"] = tidy_error
    app.jinja_env.globals["ago"] = ago

    def csrf_token() -> str:
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(24)
        return session["csrf"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    def current_config() -> Config | None:
        try:
            return Config.load(store.resolved)
        except ConfigMissing:
            return None

    # ---- request hooks ----------------------------------------------------

    @app.before_request
    def gatekeeper():
        if request.method == "POST":
            sent = request.form.get("csrf", "")
            if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
                abort(400, "Your session expired. Reload the page and try again.")
        if request.endpoint in PUBLIC_ENDPOINTS:
            return None
        if not store.has_admin():
            return redirect(url_for("setup"))
        user = session.get("user")
        if not user or not store.admin_exists(user):
            session.clear()
            return redirect(url_for("login", next=request.path))
        g.user = user
        return None

    @app.after_request
    def headers(resp):
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
            "font-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
        )
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["X-Frame-Options"] = "DENY"
        if request.endpoint != "static":
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.errorhandler(400)
    def bad_request(err):
        return render_template("message.html", title="Request not accepted",
                               message=getattr(err, "description", "Bad request")), 400

    # ---- setup and sign-in ------------------------------------------------

    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        if store.has_admin():
            return redirect(url_for("dashboard"))
        token = setup_token()
        errors = {}
        form = request.form
        if request.method == "POST":
            if not secrets.compare_digest(form.get("code", "").strip(), token):
                errors["code"] = "That code doesn't match. Copy it from the container log."
            if not USERNAME_RE.match(form.get("username", "")):
                errors["username"] = "Use 3–64 letters, numbers, dots, dashes or @."
            if len(form.get("password", "")) < MIN_PASSWORD:
                errors["password"] = f"Use at least {MIN_PASSWORD} characters."
            elif form.get("password") != form.get("confirm"):
                errors["confirm"] = "The passwords don't match."
            if not errors:
                store.create_admin(form["username"], form["password"])
                store.audit(form["username"], "created the first admin account")
                setup_state["token"] = None
                session.clear()
                session.permanent = True
                session["user"] = form["username"]
                flash("Admin account created. Next, add your credentials.")
                return redirect(url_for("settings"))
        return render_template("setup.html", errors=errors, form=form)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not store.has_admin():
            return redirect(url_for("setup"))
        error = None
        ip = request.remote_addr or "?"
        if request.method == "POST":
            wait = throttle.blocked(ip)
            if wait:
                error = f"Too many failed attempts. Try again in {max(wait // 60, 1)} minutes."
            elif store.verify_admin(request.form.get("username", ""), request.form.get("password", "")):
                throttle.clear(ip)
                session.clear()
                session.permanent = True
                session["user"] = request.form["username"]
                nxt = request.args.get("next", "")
                return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
            else:
                throttle.fail(ip)
                log.warning("Failed admin sign-in from %s", ip)
                error = "Username or password is incorrect."
        return render_template("login.html", error=error)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ---- dashboard --------------------------------------------------------

    @app.get("/")
    def dashboard():
        cfg = current_config()
        status = worker.status if worker else None
        shift, shift_error = None, None
        people = store.people_map()
        if cfg:
            try:
                shift = shift_view(cfg, people)
            except Exception as exc:
                shift_error = short_error(exc)
        state = State(db_path)
        rows = state.all_rows()[:100]
        by_email = {p.sdp_email.lower(): p.pagerduty_user for p in people.values()}
        previews = []
        if worker and worker._syncer is not None:
            previews = sorted(worker._syncer.previews.values(), key=lambda p: p["aw_id"], reverse=True)
        return render_template(
            "dashboard.html", cfg=cfg, status=status, shift=shift, shift_error=shift_error,
            strip=strip_layout(shift, tz()) if shift else None, rows=rows, previews=previews,
            by_email=by_email, state_labels=STATE_LABELS,
            missing=store.missing_required(),
        )

    @app.post("/check-now")
    def check_now():
        if worker:
            worker.wake()
        flash("Checking now. Refresh in a few seconds to see the result.")
        return redirect(url_for("dashboard"))

    @app.get("/healthz")
    def healthz():
        st = worker.status if worker else None
        return jsonify(
            phase=st.phase if st else "no-worker",
            last_check_at=st.last_check_at.isoformat() if st and st.last_check_at else None,
            last_check_ok=st.last_check_ok if st else None,
        )

    # ---- settings ---------------------------------------------------------

    def validate(key: str, value: str) -> str | None:
        f = FIELDS_BY_KEY[key]
        if not value:
            return None
        if f.kind == "int":
            if not value.isdigit():
                return "Enter a whole number."
        if f.kind == "select" and value not in {c[0] for c in f.choices}:
            return "Pick one of the options."
        if key == "aw_org_uuid" and not UUID_RE.match(value.lower()):
            return "That isn't a UUID like 550e8400-e29b-41d4-a716-446655440000."
        if key == "sdp_base_url" and not value.startswith("https://"):
            return "Start with https://"
        if key.endswith("_email") and "@" not in value:
            return "Enter an email address."
        if key == "display_timezone":
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError):
                return "Use a time zone name like America/New_York."
        return None

    @app.route("/settings", methods=["GET", "POST"])
    def settings():
        errors: dict[str, str] = {}
        results = None
        if request.method == "POST":
            changes, labels = {}, []
            for f in FIELDS:
                if f.kind == "bool":
                    if f"present_{f.key}" in request.form:
                        new = "true" if request.form.get(f.key) == "on" else "false"
                        if new != (store.resolved(f.key) or f.default):
                            changes[f.key] = new
                    continue
                if f.secret:
                    if request.form.get(f"clear_{f.key}") == "on":
                        changes[f.key] = None
                        continue
                    new = request.form.get(f.key, "").strip()
                    if new:
                        changes[f.key] = new
                    continue
                new = request.form.get(f.key, "").strip()
                if new != (store.saved(f.key) or "") and not (
                        not store.saved(f.key) and new == (store.resolved(f.key) or "")):
                    changes[f.key] = new or None
            for key, value in changes.items():
                if value:
                    err = validate(key, value)
                    if err:
                        errors[key] = err
            if not errors:
                for key, value in changes.items():
                    if value:
                        store.set(key, value, g.user)
                    else:
                        store.clear(key)
                    labels.append(FIELDS_BY_KEY[key].label + (" (removed)" if not value else ""))
                if labels:
                    store.audit(g.user, "changed " + ", ".join(labels))
                    if worker:
                        worker.wake()
                test = request.form.get("test")
                if test in {"aw", "sdp", "pd"}:
                    cfg = current_config()
                    if cfg is None:
                        missing = ", ".join(f.label for f in store.missing_required())
                        flash(f"Saved. To test, first fill in: {missing}.")
                    else:
                        results = check_connections(cfg, only=test)
                        return render_template("settings.html", **settings_context(errors, results, test))
                    return redirect(url_for("settings") + f"#{test}")
                flash("Settings saved." if labels else "No changes to save.")
                return redirect(url_for("settings"))
        return render_template("settings.html", **settings_context(errors, results, None))

    def settings_context(errors, results, tested):
        sections = []
        for key, title, blurb in SECTIONS:
            sections.append({
                "key": key, "title": title, "blurb": blurb,
                "fields": [store.info(f) for f in FIELDS if f.section == key],
            })
        return dict(sections=sections, errors=errors, results=results, tested=tested,
                    form=request.form if errors else {}, audit=store.recent_audit(),
                    missing=store.missing_required())

    # ---- people -----------------------------------------------------------

    @app.route("/people", methods=["GET", "POST"])
    def people():
        errors: list[str] = []
        if request.method == "POST":
            rows, seen = [], set()
            indexes = sorted({int(k.split("-")[1]) for k in request.form if k.startswith("p-")})
            for i in indexes:
                def v(name):
                    return request.form.get(f"p-{i}-{name}", "").strip()
                if request.form.get(f"p-{i}-remove") == "on":
                    continue
                if not any(v(n) for n in ("pagerduty_id", "pagerduty_user", "aw_email", "sdp_email")):
                    continue
                pd_id = v("pagerduty_id").upper()
                name = v("pagerduty_user") or pd_id
                if not re.match(r"^P[A-Z0-9]{6}$", pd_id):
                    errors.append(f"{name}: the PagerDuty ID should look like PGF0XOX.")
                if pd_id in seen:
                    errors.append(f"{pd_id} is listed twice.")
                seen.add(pd_id)
                email = v("sdp_email") or v("aw_email")
                if not email or "@" not in email:
                    errors.append(f"{name}: add an email so SDP can find the technician.")
                rows.append({
                    "pagerduty_id": pd_id, "pagerduty_user": name, "aw_assignee": v("aw_assignee"),
                    "aw_email": v("aw_email"), "sdp_email": v("sdp_email"),
                    "active": int(request.form.get(f"p-{i}-active") == "on"),
                })
            if not errors:
                store.replace_people(rows, g.user)
                if worker:
                    worker.wake()
                flash(f"Saved {len(rows)} people.")
                return redirect(url_for("people"))
            return render_template("people.html", rows=rows, errors=errors)
        rows = [dict(r) for r in store.raw_people()]
        return render_template("people.html", rows=rows, errors=errors)

    # ---- account ----------------------------------------------------------

    @app.route("/account", methods=["GET", "POST"])
    def account():
        errors = {}
        if request.method == "POST":
            action = request.form.get("action")
            if action == "password":
                if not store.verify_admin(g.user, request.form.get("current", "")):
                    errors["current"] = "That isn't your current password."
                elif len(request.form.get("new", "")) < MIN_PASSWORD:
                    errors["new"] = f"Use at least {MIN_PASSWORD} characters."
                elif request.form.get("new") != request.form.get("confirm"):
                    errors["confirm"] = "The passwords don't match."
                else:
                    store.set_password(g.user, request.form["new"])
                    store.audit(g.user, "changed their password")
                    flash("Password changed.")
                    return redirect(url_for("account"))
            elif action == "add":
                username = request.form.get("username", "")
                if not USERNAME_RE.match(username):
                    errors["username"] = "Use 3–64 letters, numbers, dots, dashes or @."
                elif store.admin_exists(username):
                    errors["username"] = "That admin already exists."
                elif len(request.form.get("password", "")) < MIN_PASSWORD:
                    errors["password"] = f"Use at least {MIN_PASSWORD} characters."
                else:
                    store.create_admin(username, request.form["password"])
                    store.audit(g.user, f"added admin {username}")
                    flash(f"Added {username}. Share the password with them securely.")
                    return redirect(url_for("account"))
        return render_template("account.html", errors=errors, admins=store.list_admins())

    return app


# ---- shift strip geometry ---------------------------------------------------

def strip_layout(view, zone: ZoneInfo) -> dict:
    """Positions (0–1000 wide) for the SVG shift strip."""
    span = (view.window_end - view.window_start).total_seconds()

    def x(dt: datetime) -> float:
        secs = (min(max(dt, view.window_start), view.window_end) - view.window_start).total_seconds()
        return round(secs / span * 1000, 1)

    blocks = []
    for entry, person in view.shifts:
        x0, x1 = x(entry.start), x(entry.end)
        blocks.append({
            "x": x0, "w": max(x1 - x0, 1),
            "name": person.pagerduty_user if person else entry.user_name,
            "mapped": bool(person and person.active),
            "current": entry.start <= view.now < entry.end,
            "until": entry.end.astimezone(zone).strftime("%-I:%M %p"),
            "label_x": x0 + 10,
            "wide": (x1 - x0) > 95,
        })
    handoff = None
    if view.handoff_start:
        current_end = next((e.end for e, _ in view.shifts if e.start <= view.now < e.end), None)
        if current_end:
            handoff = {"x": x(view.handoff_start), "w": max(x(current_end) - x(view.handoff_start), 1)}
    ticks = []
    t = view.window_start.astimezone(zone).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while t < view.window_end:
        if t.hour % 2 == 0:
            ticks.append({"x": x(t), "label": t.strftime("%-I %p").lower()})
        t += timedelta(hours=1)
    return {"blocks": blocks, "handoff": handoff, "now_x": x(view.now), "ticks": ticks}
