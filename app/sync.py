"""The three flows:

  1. Arctic Wolf -> SDP: new AW ticket becomes an SDP request, assigned to whoever is
     on shift in PagerDuty (with the 30-minute handoff rule) and acknowledged.
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

    # ------------------------------------------------------------------ cycle

    def run_cycle(self) -> None:
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
            selection = pick_on_shift(self._schedule(), self.now(), self.cfg.handoff_minutes)
        except Exception as exc:  # PagerDuty down shouldn't stop tickets flowing
            selection = None
            reason = f"PagerDuty lookup failed ({exc.__class__.__name__}: {exc})"
        if selection:
            person = self.people.get(selection.entry.user_id)
            if person and person.active:
                return Assignment(person.sdp_email, person.pagerduty_id, person.pagerduty_user, selection.reason)
            reason = (
                f"{selection.reason}; but PagerDuty user {selection.entry.user_name} "
                f"({selection.entry.user_id}) is not active in the identity map"
            )
        elif not reason:
            reason = "Nobody is on the PagerDuty schedule in the lookahead window"
        if self.cfg.sdp_fallback_technician_email:
            return Assignment(
                self.cfg.sdp_fallback_technician_email,
                None,
                None,
                f"{reason}; assigned to the fallback technician",
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
                                 f"Auto-assignment to {who.email} was rejected by SDP: {exc.body[:300]}")
                created = self.sdp.create_request(request)
        except APIError as exc:
            self.state.fail_create(aw_id, str(exc))
            log.error("AW %s: SDP create failed, will retry next cycle: %s", aw_id, exc)
            return
        except requests.RequestException as exc:
            # Unknown outcome (timeout etc.). Leave the row in 'creating' so we never
            # create a duplicate; it is flagged every cycle until someone checks SDP.
            self.state.set_error(aw_id, f"create outcome unknown: {exc}")
            log.critical("AW %s: SDP create outcome unknown (%s). Check SDP for '[AW-%s]'.",
                         aw_id, exc, aw_id)
            return

        sdp_id = str(created["id"])
        self.state.finish_create(aw_id, sdp_id, who.email, who.pd_id, who.reason)
        log.info("AW %s -> SDP %s, technician=%s (%s)", aw_id, sdp_id, who.email or "unassigned", who.reason)

        if who.email:
            note = (f"Acknowledged automatically and assigned to {who.name or who.email}. "
                    f"PagerDuty: {who.reason}.")
        else:
            note = f"Not auto-assigned: {who.reason}. Please assign manually."
        try:
            self.sdp.add_note(sdp_id, html.escape(note), mark_first_response=bool(who.email))
        except (APIError, requests.RequestException) as exc:
            log.warning("SDP %s: could not add acknowledgement note: %s", sdp_id, exc)

    def _warn_stuck_creates(self) -> None:
        for row in self.state.stuck_creating():
            if row["aw_id"] not in self._warned_stuck:
                self._warned_stuck.add(row["aw_id"])
                log.critical(
                    "AW %s is stuck in 'creating' (last error: %s). Check SDP for '[AW-%s]', then "
                    "run `python -m app resolve-stuck %s <sdp_id>` or `... resolve-stuck %s none`.",
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
                self.state.set_error(aw_id, f"SDP get failed: {exc}")
                log.warning("SDP %s (AW %s): could not read status: %s", sdp_id, aw_id, exc)
                continue
            status = ((req.get("status") or {}).get("name") or "").lower()
            if status not in close_statuses:
                continue
            comment = self._closing_comment(req)
            if self.cfg.dry_run:
                log.info("[DRY RUN] would close AW %s (SDP %s is %s)", aw_id, sdp_id, status)
                continue
            try:
                self.aw.close_ticket(aw_id, comment)
            except (APIError, requests.RequestException) as exc:
                if self.aw.is_closed(aw_id):
                    self.state.mark_aw_closed(aw_id, "sdp")
                    log.info("AW %s was already closed; marked done", aw_id)
                else:
                    self.state.set_error(aw_id, f"AW close failed: {exc}")
                    log.error("AW %s: close failed, will retry: %s", aw_id, exc)
                continue
            self.state.mark_aw_closed(aw_id, "sdp")
            log.info("Closed AW %s because SDP %s is %s", aw_id, sdp_id, status)

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
                        html.escape(f"Arctic Wolf closed AW ticket {aw_id} on their side. "
                                    "Resolve this request if no further work is needed."),
                    )
                except (APIError, requests.RequestException) as exc:
                    log.warning("SDP %s: could not add AW-closed note: %s", row["sdp_id"], exc)
                    continue  # try again next cycle
            self.state.mark_aw_closed(aw_id, "arcticwolf")
            log.info("AW %s was closed by Arctic Wolf; noted on SDP %s", aw_id, row["sdp_id"])
        # Small overlap so a ticket updated during this query isn't missed next time.
        self.state.set_meta("aw_closed_checked", iso(started - timedelta(minutes=2)))
