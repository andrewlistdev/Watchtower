"""Glue shared by the worker, the web GUI and the CLI."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .arcticwolf import ArcticWolfClient
from .config import Config
from .identity import Person
from .oncall import ScheduleEntry, merge_adjacent, pick_on_shift
from .pagerduty import PagerDutyClient
from .servicedesk import ServiceDeskClient
from .settings_store import SettingsStore
from .state import State
from .sync import Syncer


def data_dir() -> str:
    path = os.environ.get("DATA_DIR", "/data")
    os.makedirs(path, exist_ok=True)
    return path


def db_path() -> str:
    return os.environ.get("DB_PATH") or os.path.join(data_dir(), "state.db")


def open_store() -> SettingsStore:
    store = SettingsStore(db_path())
    store.seed_people_from_csv(os.environ.get("IDENTITY_MAP_PATH", "/app/config/identity_map.csv"))
    return store


def build_syncer(cfg: Config, state: State, people: dict[str, Person]) -> Syncer:
    return Syncer(
        cfg=cfg,
        aw=ArcticWolfClient(cfg.aw_base_url, cfg.aw_api_token, cfg.aw_org_uuid),
        sdp=ServiceDeskClient(cfg.sdp_base_url, cfg.zoho_accounts_url, cfg.zoho_client_id,
                              cfg.zoho_client_secret, cfg.zoho_refresh_token),
        pd=PagerDutyClient(cfg.pd_api_token),
        state=state,
        people=people,
    )


@dataclass
class CheckResult:
    service: str
    ok: bool
    message: str


def check_connections(cfg: Config, only: str | None = None) -> list[CheckResult]:
    """Read-only call to each service with the current settings."""
    results = []
    tests = {
        "aw": ("Arctic Wolf", lambda: next(iter(
            ArcticWolfClient(cfg.aw_base_url, cfg.aw_api_token, cfg.aw_org_uuid).list_tickets(["OPEN"])), None)),
        "sdp": ("ServiceDesk Plus", lambda: ServiceDeskClient(
            cfg.sdp_base_url, cfg.zoho_accounts_url, cfg.zoho_client_id,
            cfg.zoho_client_secret, cfg.zoho_refresh_token).ping()),
        "pd": ("PagerDuty", lambda: PagerDutyClient(cfg.pd_api_token).schedule_entries(
            cfg.pd_schedule_id, datetime.now(timezone.utc), 1)),
    }
    for key, (name, fn) in tests.items():
        if only and key != only:
            continue
        try:
            fn()
            results.append(CheckResult(name, True, "Connected"))
        except Exception as exc:  # report every failure the same way
            results.append(CheckResult(name, False, short_error(exc)))
    return results


def check_section(get, section: str) -> CheckResult:
    """Test one service using only that section's settings, so each can be checked on its own."""
    from .settings_store import FIELDS, SECTIONS
    name = dict((k, t) for k, t, _ in SECTIONS)[section]
    missing = [f.label for f in FIELDS if f.section == section and f.required and not get(f.key)]
    if missing:
        return CheckResult(name, False, "Fill in " + ", ".join(missing) + " first.")
    try:
        if section == "aw":
            next(iter(ArcticWolfClient(get("aw_base_url"), get("aw_api_token"), get("aw_org_uuid"))
                      .list_tickets(["OPEN"])), None)
        elif section == "sdp":
            ServiceDeskClient(get("sdp_base_url"), get("zoho_accounts_url"), get("zoho_client_id"),
                              get("zoho_client_secret"), get("zoho_refresh_token")).ping()
        elif section == "pd":
            PagerDutyClient(get("pd_api_token")).schedule_entries(get("pd_schedule_id"),
                                                                   datetime.now(timezone.utc), 1)
        return CheckResult(name, True, "Connected")
    except Exception as exc:  # report every failure the same way
        return CheckResult(name, False, short_error(exc))


def short_error(exc: Exception) -> str:
    text = str(exc)
    for marker in ("401", "403", "404"):
        if f"-> {marker}" in text:
            return {"401": "Rejected the credentials (401).",
                    "403": "Credentials work but lack permission (403).",
                    "404": "Not found (404). Check the ID or URL."}[marker]
    body = getattr(exc, "body", None)
    if getattr(exc, "service", None) == "Zoho" and body and not body.lstrip().startswith("{"):
        return body
    if "Max retries exceeded" in text or "NameResolution" in text or "ProxyError" in text:
        return "Couldn't reach the server. Check the URL and this machine's network access."
    return text[:300]


@dataclass
class ShiftView:
    now: datetime
    window_start: datetime
    window_end: datetime
    shifts: list[tuple[ScheduleEntry, Person | None]]
    handoff_start: datetime | None
    assignee_name: str | None
    assignee_email: str | None
    reason: str


def shift_view(cfg: Config, people: dict[str, Person], hours: int = 12,
               now: datetime | None = None, entries: list[ScheduleEntry] | None = None) -> ShiftView:
    """Who is on call now and next, for the overview strip and `whois`.

    The window starts two hours back so the strip shows the shift in progress.
    """
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(hours=2)
    window_end = window_start + timedelta(hours=hours)
    if entries is None:
        pd = PagerDutyClient(cfg.pd_api_token)
        lookahead = max(hours, cfg.pd_lookahead_hours) + 2
        entries = pd.schedule_entries(cfg.pd_schedule_id, window_start, lookahead)
    shifts = merge_adjacent(entries)
    visible = [s for s in shifts if s.start < window_end and s.end > window_start]
    current = next((s for s in visible if s.start <= now < s.end), None)
    handoff = current.end - timedelta(minutes=cfg.handoff_minutes) if current else None

    sel = pick_on_shift(entries, now, cfg.handoff_minutes, cfg.zone)
    name = email = None
    if sel is None:
        reason = "No on-call coverage is configured for this period. Review the PagerDuty schedule."
    else:
        person = people.get(sel.entry.user_id)
        reason = sel.reason
        if person and person.active:
            name, email = person.pagerduty_user, person.sdp_email
        elif cfg.sdp_fallback_technician_email:
            email = cfg.sdp_fallback_technician_email
            reason += (f" {sel.entry.user_name} isn't an active responder in Watchtower, so it routes to "
                       f"the fallback technician.")
        else:
            reason += (f" No eligible on-call responder was found: {sel.entry.user_name} isn't an active "
                       f"responder in Watchtower. Add them on the Responders page, or the ticket stays unassigned.")
    return ShiftView(
        now=now, window_start=window_start, window_end=window_end,
        shifts=[(s, people.get(s.user_id)) for s in visible],
        handoff_start=handoff, assignee_name=name, assignee_email=email, reason=reason,
    )
