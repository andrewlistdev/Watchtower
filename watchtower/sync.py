"""The three flows:

  1. Arctic Wolf -> SDP: new AW ticket becomes an SDP request, routed to whoever is on
     call in PagerDuty (with the 30-minute handoff rule) and set to the routed status.
  2. SDP -> Arctic Wolf: when the SDP request reaches a close status (Resolved/Closed),
     close the AW ticket with the resolution as the closing comment.
  3. Arctic Wolf closed it first: add a note on the SDP request so the tech knows.
"""

from __future__ import annotations

import html
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import requests

from .arcticwolf import ArcticWolfClient
from .config import Config
from .http import APIError
from .identity import Person
from .oncall import pick_on_shift
from .pagerduty import PagerDutyClient
from .servicedesk import ServiceDeskClient
from .state import State

log = logging.getLogger("sync")

BACKFILL_MARKER = "backfill"


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def strip_html(text: str) -> str:
    text = re.sub(r"<\s*br\s*/?\s*>|</p>|</div>", "\n", text or "", flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def _api_message(exc: Exception) -> str:
    """The human-readable part of an API error, for the routing history."""
    body = getattr(exc, "body", "") or str(exc)
    messages = re.findall(r'"message"\s*:\s*"([^"]+)"', body)
    if messages:
        return "; ".join(dict.fromkeys(messages))
    status = getattr(exc, "status", None)
    return f"HTTP {status}" if status else str(exc)[:200]


@dataclass
class Assignment:
    email: str | None
    pd_id: str | None
    name: str | None
    reason: str


class Syncer:
    def __init__(
        self,
        cfg: Config,
        aw: ArcticWolfClient,
        sdp: ServiceDeskClient,
        pd: PagerDutyClient,
        state: State,
        people: dict[str, Person],
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.cfg = cfg
        self.aw = aw
        self.sdp = sdp
        self.pd = pd
        self.state = state
        self.people = people
        self.now = now
        self._pd_cache: tuple[float, list] | None = None
        self._warned_stuck: set[int] = set()
        self._dry_seen: set[int] = set()
        # Dry-run previews for the dashboard: AW id -> what would happen.
        self.previews: dict[int, dict] = {}

    # ------------------------------------------------------------------ cycle

    def run_cycle(self) -> None:
        self.previews.clear()  # rebuilt each dry-run check from what is open now
        self._warn_stuck_creates()
        self.ingest_new_tickets()
        self.close_aw_when_sdp_closed()
        self.note_sdp_when_aw_closed()

    # ------------------------------------------------------- PagerDuty pick

    def _schedule(self):
        if self._pd_cache and time.monotonic() - self._pd_cache[0] < 60:
            return self._pd_cache[1]
        entries = self.pd.schedule_entries(
            self.cfg.pd_schedule_id, self.now(), self.cfg.pd_lookahead_hours
        )
        self._pd_cache = (time.monotonic(), entries)
        return entries

    def choose_assignee(self) -> Assignment:
        reason = ""
        try:
            selection = pick_on_shift(self._schedule(), self.now(), self.cfg.handoff_minutes, self.cfg.zone)
        except Exception as exc:  # PagerDuty down shouldn't stop tickets flowing
            selection = None
            reason = f"Couldn't read the PagerDuty schedule ({exc.__class__.__name__}: {exc})."
        if selection:
            person = self.people.get(selection.entry.user_id)
            if person and person.active:
                return Assignment(person.sdp_email, person.pagerduty_id, person.pagerduty_user, selection.reason)
            reason = (
                f"No eligible on-call responder was found. {selection.entry.user_name} "
                f"({selection.entry.user_id}) is on call in PagerDuty but isn't an active responder "
                f"in Watchtower."
            )
        elif not reason:
            reason = "No on-call coverage is configured for this period."
        if self.cfg.sdp_fallback_technician_email:
            return Assignment(
                self.cfg.sdp_fallback_technician_email,
                None,
                None,
                f"{reason} Routed to the fallback technician instead.",
            )
        return Assignment(None, None, None, reason)

    # ------------------------------------------------- flow 1: AW -> SDP

    def _created_after(self) -> str | None:
        if self.cfg.dry_run:
            return None  # preview every open ticket; nothing is persisted
        value = self.state.get_meta("created_after")
        if value is None:
            value = BACKFILL_MARKER if self.cfg.aw_backfill_open else iso(self.now())
            self.state.set_meta("created_after", value)
            log.info(
                "First run: %s",
                "importing all currently open AW tickets"
                if value == BACKFILL_MARKER
                else f"only AW tickets created after {value} will be imported",
            )
        return None if value == BACKFILL_MARKER else value

    def ingest_new_tickets(self) -> None:
        created_after = self._created_after()
        for ticket in self.aw.list_tickets(self.cfg.aw_open_statuses, created_after=created_after):
            aw_id = int(ticket["id"])
            row = self.state.get(aw_id)
            if row is not None:
                if row["state"] != "failed_create":
                    continue
                self.state.clear_failed(aw_id)  # retry a create that SDP rejected last time
            self._create_sdp_request(ticket)

    def _build_request(self, ticket: dict, who: Assignment) -> dict:
        aw_id = ticket["id"]
        aw_assignee = ticket.get("assignee") or {}
        details = [
            ("Arctic Wolf ticket", str(aw_id)),
            ("AW status", f"{ticket.get('status', '')} ({ticket.get('portalStatus', '')})"),
            ("AW priority", ticket.get("priority", "")),
            ("AW type", f"{ticket.get('type', '')} ({ticket.get('portalType', '')})"),
            ("AW created", ticket.get("createdAt", "")),
            (
                "AW assigned to",
                " ".join(filter(None, [aw_assignee.get("firstName"), aw_assignee.get("lastName")]))
                or "-",
            ),
        ]
        header = "<br>".join(f"<b>{html.escape(k)}:</b> {html.escape(str(v))}" for k, v in details)
        body = html.escape(ticket.get("description") or "").replace("\n", "<br>")
        request: dict = {
            "subject": f"[AW-{aw_id}] {ticket.get('title') or 'Arctic Wolf ticket'}"[:250],
            "description": f"{header}<br><br>{body}",
        }
        priority = self.cfg.priority_map.get(ticket.get("priority") or "")
        if priority:
            request["priority"] = {"name": priority}
        if self.cfg.sdp_requester_email:
            request["requester"] = {"email_id": self.cfg.sdp_requester_email}
        if self.cfg.sdp_group:
            request["group"] = {"name": self.cfg.sdp_group}
        if self.cfg.sdp_aw_id_udf:
            request["udf_fields"] = {self.cfg.sdp_aw_id_udf: str(aw_id)}
        if who.email:
            request["technician"] = {"email_id": who.email}
            request["status"] = {"name": self.cfg.sdp_ack_status}
        return request

    def _create_sdp_request(self, ticket: dict) -> None:
        aw_id = int(ticket["id"])
        who = self.choose_assignee()
        request = self._build_request(ticket, who)

        if self.cfg.dry_run:
            self.previews[aw_id] = {
                "aw_id": aw_id,
                "title": ticket.get("title") or "",
                "aw_status": ticket.get("status") or "",
                "technician": who.email,
                "name": who.name,
                "reason": who.reason,
            }
            if aw_id not in self._dry_seen:
                self._dry_seen.add(aw_id)
                log.info(
                    "[DRY RUN] AW %s %r -> new SDP request, technician=%s, status=%s. Why: %s",
                    aw_id, ticket.get("title"), who.email or "(unassigned)",
                    (request.get("status") or {}).get("name", "(default)"), who.reason,
                )
            return

        self.state.begin_create(aw_id, ticket.get("title") or "")
        try:
            try:
                created = self.sdp.create_request(request)
            except APIError as exc:
                if "technician" not in request:
                    raise
                # SDP rejected the create (e.g. technician email not found). Create it
                # unassigned rather than lose the ticket, and say why in a note.
                log.warning("AW %s: SDP rejected assignment to %s (%s); creating unassigned",
                            aw_id, who.email, exc)
                request.pop("technician", None)
                request.pop("status", None)
                who = Assignment(None, None, None,
                                 f"ServiceDesk Plus rejected the assignment to {who.email} "
                                 f"({_api_message(exc)}), so the ticket was created unassigned.")
                created = self.sdp.create_request(request)
        except APIError as exc:
            self.state.fail_create(aw_id, str(exc))
            self.state.record_event(
                aw_id, "failed",
                f"Couldn't create the ServiceDesk Plus request: {_api_message(exc)}. Retrying each check.",
                dedupe=True)
            log.error("AW %s: SDP create failed, will retry next cycle: %s", aw_id, exc)
            return
        except requests.RequestException as exc:
            # Unknown outcome (timeout etc.). Leave the row in 'creating' so we never
            # create a duplicate; it is flagged every cycle until someone checks SDP.
            self.state.set_error(aw_id, f"create outcome unknown: {exc}")
            self.state.record_event(
                aw_id, "unknown",
                f"ServiceDesk Plus didn't confirm the request was created. Search SDP for "
                f"[AW-{aw_id}] before anything else happens to this ticket.")
            log.critical("AW %s: SDP create outcome unknown (%s). Check SDP for '[AW-%s]'.",
                         aw_id, exc, aw_id)
            return

        sdp_id = str(created["id"])
        self.state.finish_create(aw_id, sdp_id, who.email, who.pd_id, who.reason, who.name)
        log.info("AW %s -> SDP %s, technician=%s (%s)", aw_id, sdp_id, who.email or "unassigned", who.reason)

        if who.email:
            owner = who.name or who.email
            self.state.record_event(aw_id, "routed",
                                    f"Routed to {owner} in ServiceDesk Plus request #{sdp_id}. {who.reason}")
            # Mark first response and set the routed status, as before; the note says plainly that
            # Watchtower did this, not the responder.
            note = (f"Watchtower routed this ticket to {owner}. {who.reason} "
                    f"Status set to {self.cfg.sdp_ack_status}; {owner} hasn't acknowledged it yet.")
        else:
            self.state.record_event(aw_id, "unassigned",
                                    f"Created ServiceDesk Plus request #{sdp_id} without an owner. {who.reason}")
            note = f"Watchtower couldn't route this ticket. {who.reason} Assign it manually."
        try:
            self.sdp.add_note(sdp_id, html.escape(note, quote=False), mark_first_response=bool(who.email))
        except (APIError, requests.RequestException) as exc:
            log.warning("SDP %s: could not add routing note: %s", sdp_id, exc)

    def _warn_stuck_creates(self) -> None:
        for row in self.state.stuck_creating():
            if row["aw_id"] not in self._warned_stuck:
                self._warned_stuck.add(row["aw_id"])
                log.critical(
                    "AW %s is stuck in 'creating' (last error: %s). Check SDP for '[AW-%s]', then "
                    "run `docker compose run --rm watchtower resolve-stuck %s <sdp_id>` (or `... %s none`).",
                    row["aw_id"], row["last_error"], row["aw_id"], row["aw_id"], row["aw_id"],
                )

    # ------------------------------------------ flow 2: SDP closed -> close AW

    def _closing_comment(self, req: dict) -> str:
        tech = (req.get("technician") or {}).get("name") or "the assigned technician"
        status = (req.get("status") or {}).get("name", "")
        text = strip_html(self.sdp.resolution_text(req))
        comment = f"{status} in our ServiceDesk Plus (request #{req.get('id')}) by {tech}."
        if text:
            comment += f"\n\nResolution:\n{text}"
        return comment

    def close_aw_when_sdp_closed(self) -> None:
        close_statuses = {s.lower() for s in self.cfg.sdp_close_statuses}
        for row in self.state.open_mappings():
            aw_id, sdp_id = int(row["aw_id"]), row["sdp_id"]
            try:
                req = self.sdp.get_request(sdp_id)
            except (APIError, requests.RequestException) as exc:
                self.state.set_refresh_error(aw_id, f"SDP read failed: {exc}")
                log.warning("SDP %s (AW %s): could not read status: %s", sdp_id, aw_id, exc)
                continue
            self._refresh(row, req)
            status_name = (req.get("status") or {}).get("name") or ""
            status = status_name.lower()
            if status not in close_statuses:
                continue
            comment = self._closing_comment(req)
            if self.cfg.dry_run:
                log.info("[DRY RUN] would close AW %s (SDP %s is %s)", aw_id, sdp_id, status)
                continue
            tech = (req.get("technician") or {}).get("name")
            try:
                self.aw.close_ticket(aw_id, comment)
            except (APIError, requests.RequestException) as exc:
                if self.aw.is_closed(aw_id):
                    self.state.mark_aw_closed(aw_id, "sdp")
                    self.state.record_event(
                        aw_id, "resolved",
                        f"Ticket marked as {status_name} in ServiceDesk Plus. The Arctic Wolf ticket was "
                        f"already closed.")
                    log.info("AW %s was already closed; marked done", aw_id)
                else:
                    self.state.set_error(aw_id, f"AW close failed: {exc}")
                    self.state.record_event(
                        aw_id, "failed",
                        f"Couldn't close the Arctic Wolf ticket: {_api_message(exc)}. Retrying each check.",
                        dedupe=True)
                    log.error("AW %s: close failed, will retry: %s", aw_id, exc)
                continue
            self.state.mark_aw_closed(aw_id, "sdp")
            self.state.record_event(
                aw_id, "resolved",
                f"Ticket marked as {status_name} in ServiceDesk Plus{f' by {tech}' if tech else ''}. "
                f"Arctic Wolf ticket closed with the resolution as the closing comment.")
            log.info("Closed AW %s because SDP %s is %s", aw_id, sdp_id, status)

    def _refresh(self, row, req: dict) -> None:
        """Keep the current owner and SDP status up to date, and log changes to the history."""
        aw_id = int(row["aw_id"])
        tech = req.get("technician") or {}
        name = tech.get("name") or None
        email = (tech.get("email_id") or "").lower() or None
        status = (req.get("status") or {}).get("name") or None
        before_email = (row["owner_email"] or "").lower() or None
        before_name = row["owner_name"] or before_email
        # Keep the friendlier name we already have when SDP only reports the same email.
        display = name or (row["owner_name"] if email and email == before_email else None) or email
        self.state.update_refresh(aw_id, display, email, status)

        if email and before_email:
            changed = email != before_email
        elif not (email or name):
            changed = bool(before_email or before_name)
        else:
            changed = (name or email or "").lower() != (before_name or "").lower()
        if changed:
            now_owner = name or email
            if now_owner and before_name:
                msg = f"Ownership changed from {before_name} to {now_owner} in ServiceDesk Plus."
            elif now_owner:
                msg = f"{now_owner} took ownership in ServiceDesk Plus."
            else:
                msg = f"{before_name} was removed as owner in ServiceDesk Plus. The ticket is unassigned."
            self.state.record_event(aw_id, "reassigned", msg, actor="ServiceDesk Plus")
        if status and row["sdp_status"] and status != row["sdp_status"]:
            self.state.record_event(aw_id, "status",
                                    f"Status changed from {row['sdp_status']} to {status} in ServiceDesk Plus.",
                                    actor="ServiceDesk Plus")

    # ------------------------------------ flow 3: AW closed first -> SDP note

    def note_sdp_when_aw_closed(self) -> None:
        if self.cfg.dry_run:
            return
        started = self.now()
        since = self.state.get_meta("aw_closed_checked") or iso(started - timedelta(days=1))
        for ticket in self.aw.list_tickets(["CLOSED"], updated_after=since):
            aw_id = int(ticket["id"])
            row = self.state.get(aw_id)
            if row is None or row["state"] != "open":
                continue
            if self.cfg.aw_closed_note:
                try:
                    self.sdp.add_note(
                        row["sdp_id"],
                        html.escape(f"Arctic Wolf closed ticket {aw_id} on their side. "
                                    "Resolve this request if no further work is needed.", quote=False),
                    )
                except (APIError, requests.RequestException) as exc:
                    log.warning("SDP %s: could not add AW-closed note: %s", row["sdp_id"], exc)
                    continue  # try again next cycle
            self.state.mark_aw_closed(aw_id, "arcticwolf")
            self.state.record_event(
                aw_id, "closed_by_source",
                f"Arctic Wolf closed this ticket on their side."
                + (f" Note added to ServiceDesk Plus request #{row['sdp_id']}." if self.cfg.aw_closed_note else ""),
                actor="Arctic Wolf")
            log.info("AW %s was closed by Arctic Wolf; noted on SDP %s", aw_id, row["sdp_id"])
        # Small overlap so a ticket updated during this query isn't missed next time.
        self.state.set_meta("aw_closed_checked", iso(started - timedelta(minutes=2)))
