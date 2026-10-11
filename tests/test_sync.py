from datetime import datetime, timedelta, timezone

import pytest
import requests

from app.config import Config
from app.http import APIError
from app.identity import Person
from app.oncall import ScheduleEntry
from app.state import State
from app.sync import Syncer

NOW = datetime(2026, 10, 12, 14, 0, tzinfo=timezone.utc)


def make_cfg(**overrides) -> Config:
    base = dict(
        aw_base_url="https://aw", aw_api_token="t", aw_org_uuid="org",
        aw_open_statuses=["NEW", "OPEN", "HOLD", "PENDING"], aw_backfill_open=False,
        sdp_base_url="https://sdp", zoho_accounts_url="https://acc", zoho_client_id="c",
        zoho_client_secret="s", zoho_refresh_token="r", sdp_ack_status="In Progress",
        sdp_close_statuses=["Resolved", "Closed"], sdp_requester_email="", sdp_group="",
        sdp_aw_id_udf="udf_sline_301", sdp_fallback_technician_email="",
        pd_api_token="p", pd_schedule_id="SCHED", handoff_minutes=30, pd_lookahead_hours=48,
        poll_seconds=60, dry_run=False, aw_closed_note=True,
        priority_map={"LOW": "Low", "NORMAL": "Medium", "HIGH": "High", "URGENT": "Urgent"},
    )
    base.update(overrides)
    return Config(**base)


class FakeAW:
    def __init__(self):
        self.tickets = {}
        self.list_calls = []
        self.closed = []
        self.close_error = None

    def add(self, tid, status="NEW", **kw):
        self.tickets[tid] = {"id": tid, "title": f"Ticket {tid}", "description": "desc",
                             "status": status, "priority": "HIGH", **kw}

    def list_tickets(self, statuses=None, created_after=None, updated_after=None):
        self.list_calls.append((tuple(statuses or []), created_after, updated_after))
        return [t for t in self.tickets.values() if not statuses or t["status"] in statuses]

    def close_ticket(self, tid, comment):
        if self.close_error:
            raise self.close_error
        self.closed.append((tid, comment))
        self.tickets[tid]["status"] = "CLOSED"
        return self.tickets[tid]

    def is_closed(self, tid):
        return self.tickets[tid]["status"] == "CLOSED"


class FakeSDP:
    def __init__(self):
        self.requests = {}
        self.notes = []
        self.next_id = 1000
        self.reject_technician = False
        self.create_exc = None

    def create_request(self, req):
        if self.create_exc:
            raise self.create_exc
        if self.reject_technician and "technician" in req:
            raise APIError("ServiceDesk", "POST", "/requests", 400, "technician not found")
        self.next_id += 1
        stored = {"id": str(self.next_id), "status": req.get("status", {"name": "Open"}), **req}
        stored["status"] = req.get("status", {"name": "Open"})
        self.requests[stored["id"]] = stored
        return stored

    def get_request(self, rid):
        return self.requests[rid]

    def add_note(self, rid, description, mark_first_response=False, show_to_requester=False):
        self.notes.append((rid, description, mark_first_response))

    def resolution_text(self, req):
        return (req.get("resolution") or {}).get("content", "")


class FakePD:
    def __init__(self, entries):
        self.entries = entries

    def schedule_entries(self, schedule_id, now, lookahead_hours):
        return self.entries


PEOPLE = {
    "PPSNFCK": Person("Amanda Tillman", "PPSNFCK", "Amanda Tillman", "atillman@arrowheadep.com",
                      "atillman@arrowheadep.com", True),
    "PE77ZFQ": Person("Doug Feltner", "PE77ZFQ", "Doug Feltner", "dfeltner@arrowheadep.com",
                      "dfeltner@arrowheadep.com", True),
}

# Amanda 08:00-15:00, Doug 15:00-23:00 (UTC)
SCHEDULE = [
    ScheduleEntry("PPSNFCK", "Amanda Tillman", NOW - timedelta(hours=6), NOW + timedelta(hours=1)),
    ScheduleEntry("PE77ZFQ", "Doug Feltner", NOW + timedelta(hours=1), NOW + timedelta(hours=9)),
]


@pytest.fixture
def env():
    def _make(now=NOW, schedule=SCHEDULE, **cfg):
        aw, sdp, pd = FakeAW(), FakeSDP(), FakePD(schedule)
        s = Syncer(make_cfg(**cfg), aw, sdp, pd, State(":memory:"), PEOPLE, now=lambda: now)
        return s, aw, sdp
    return _make


def test_new_ticket_assigned_to_on_shift_and_acknowledged(env):
    s, aw, sdp = env()
    aw.add(1)
    s.run_cycle()
    (req,) = sdp.requests.values()
    assert req["subject"] == "[AW-1] Ticket 1"
    assert req["technician"] == {"email_id": "atillman@arrowheadep.com"}
    assert req["status"] == {"name": "In Progress"}
    assert req["priority"] == {"name": "High"}
    assert req["udf_fields"] == {"udf_sline_301": "1"}
    rid, note, first_response = sdp.notes[0]
    assert "Acknowledged" in note and first_response is True
    assert s.state.get(1)["state"] == "open"


def test_ticket_not_created_twice(env):
    s, aw, sdp = env()
    aw.add(1)
    s.run_cycle()
    s.run_cycle()
    assert len(sdp.requests) == 1


def test_handoff_window_assigns_next_shift(env):
    s, aw, sdp = env(now=NOW + timedelta(minutes=40))  # Amanda has 20 min left
    aw.add(2)
    s.run_cycle()
    (req,) = sdp.requests.values()
    assert req["technician"] == {"email_id": "dfeltner@arrowheadep.com"}


def test_unmapped_pagerduty_user_creates_unassigned(env):
    sched = [ScheduleEntry("PXXXXXX", "Someone New", NOW - timedelta(hours=1), NOW + timedelta(hours=5))]
    s, aw, sdp = env(schedule=sched)
    aw.add(3)
    s.run_cycle()
    (req,) = sdp.requests.values()
    assert "technician" not in req
    assert "Not auto-assigned" in sdp.notes[0][1]


def test_fallback_technician_used_when_unmapped(env):
    s, aw, sdp = env(schedule=[], sdp_fallback_technician_email="queue@arrowheadep.com")
    aw.add(4)
    s.run_cycle()
    (req,) = sdp.requests.values()
    assert req["technician"] == {"email_id": "queue@arrowheadep.com"}


def test_sdp_rejects_technician_creates_unassigned(env):
    s, aw, sdp = env()
    sdp.reject_technician = True
    aw.add(5)
    s.run_cycle()
    (req,) = sdp.requests.values()
    assert "technician" not in req
    assert "rejected by SDP" in sdp.notes[0][1]


def test_resolved_in_sdp_closes_aw_with_resolution(env):
    s, aw, sdp = env()
    aw.add(6)
    s.run_cycle()
    (req,) = sdp.requests.values()
    req["status"] = {"name": "Resolved"}
    req["technician"] = {"name": "Amanda Tillman"}
    req["resolution"] = {"content": "<p>Isolated host and reset creds</p>"}
    s.run_cycle()
    (closed_id, comment), = aw.closed
    assert closed_id == 6
    assert "Resolved in our ServiceDesk Plus" in comment
    assert "Isolated host and reset creds" in comment and "<p>" not in comment
    assert s.state.get(6)["state"] == "aw_closed"
    s.run_cycle()
    assert len(aw.closed) == 1  # not closed again


def test_in_progress_does_not_close_aw(env):
    s, aw, sdp = env()
    aw.add(7)
    s.run_cycle()
    s.run_cycle()
    assert aw.closed == []


def test_close_error_but_already_closed_is_marked_done(env):
    s, aw, sdp = env()
    aw.add(8)
    s.run_cycle()
    next(iter(sdp.requests.values()))["status"] = {"name": "Closed"}
    aw.tickets[8]["status"] = "CLOSED"
    aw.close_error = APIError("ArcticWolf", "POST", "/close", 400, "already closed")
    s.run_cycle()
    assert s.state.get(8)["state"] == "aw_closed"


def test_aw_closed_first_adds_sdp_note(env):
    s, aw, sdp = env()
    aw.add(9)
    s.run_cycle()
    aw.tickets[9]["status"] = "CLOSED"
    s.run_cycle()
    assert any("Arctic Wolf closed AW ticket 9" in n[1] for n in sdp.notes)
    assert s.state.get(9)["closed_by"] == "arcticwolf"


def test_first_run_only_imports_new_tickets(env):
    s, aw, sdp = env()
    s.run_cycle()
    statuses, created_after, _ = aw.list_calls[0]
    assert created_after == "2026-10-12T14:00:00Z"


def test_backfill_imports_existing(env):
    s, aw, sdp = env(aw_backfill_open=True)
    s.run_cycle()
    _, created_after, _ = aw.list_calls[0]
    assert created_after is None


def test_dry_run_writes_nothing(env):
    s, aw, sdp = env(dry_run=True)
    aw.add(10)
    s.run_cycle()
    assert sdp.requests == {} and sdp.notes == [] and s.state.get(10) is None


def test_create_timeout_never_duplicates(env):
    s, aw, sdp = env()
    sdp.create_exc = requests.Timeout("read timed out")
    aw.add(11)
    s.run_cycle()
    assert s.state.get(11)["state"] == "creating"
    sdp.create_exc = None
    s.run_cycle()
    assert sdp.requests == {}  # left for an operator to check, not recreated
    assert s.state.resolve_stuck(11, None)
    s.run_cycle()
    assert len(sdp.requests) == 1


def test_rejected_create_is_retried_next_cycle(env):
    s, aw, sdp = env(schedule=[])  # unassigned, so no technician fallback path
    sdp.create_exc = APIError("ServiceDesk", "POST", "/requests", 400, "bad priority")
    aw.add(12)
    s.run_cycle()
    assert s.state.get(12)["state"] == "failed_create"
    sdp.create_exc = None
    s.run_cycle()
    assert s.state.get(12)["state"] == "open"
