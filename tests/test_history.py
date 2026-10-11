"""Routing history, current-owner refresh, status labels and the schema migration."""

import sqlite3
from datetime import datetime, timedelta, timezone

from tests.test_sync import FakeAW, FakePD, FakeSDP, NOW, PEOPLE, SCHEDULE, make_cfg
from watchtower.state import State
from watchtower.status import ticket_status
from watchtower.sync import Syncer


def make(**cfg):
    aw, sdp = FakeAW(), FakeSDP()
    s = Syncer(make_cfg(**cfg), aw, sdp, FakePD(SCHEDULE), State(":memory:"), PEOPLE, now=lambda: NOW)
    return s, aw, sdp


def kinds(state, aw_id):
    return [e["kind"] for e in reversed(state.events(aw_id))]


def test_routing_is_recorded_with_reason():
    s, aw, sdp = make()
    aw.add(1)
    s.run_cycle()
    (event,) = s.state.events(1)
    assert event["kind"] == "routed"
    assert "Routed to Amanda Tillman" in event["message"] and "on call until" in event["message"]


def test_reassignment_in_sdp_updates_owner_and_history():
    s, aw, sdp = make()
    aw.add(2)
    s.run_cycle()
    req = next(iter(sdp.requests.values()))
    req["technician"] = {"name": "Doug Feltner", "email_id": "dfeltner@arrowheadep.com"}
    s.run_cycle()
    row = s.state.get(2)
    assert row["owner_name"] == "Doug Feltner" and row["owner_email"] == "dfeltner@arrowheadep.com"
    assert "Ownership changed from Amanda Tillman to Doug Feltner" in s.state.events(2)[0]["message"]


def test_same_owner_reported_by_sdp_is_not_a_reassignment():
    s, aw, sdp = make()
    aw.add(3)
    s.run_cycle()
    next(iter(sdp.requests.values()))["technician"] = {"name": "Amanda Tillman",
                                                       "email_id": "ATillman@arrowheadep.com"}
    s.run_cycle()
    s.run_cycle()
    assert kinds(s.state, 3) == ["routed"]


def test_status_change_and_resolution_are_recorded():
    s, aw, sdp = make()
    aw.add(4)
    s.run_cycle()
    req = next(iter(sdp.requests.values()))
    req["technician"] = {"name": "Amanda Tillman", "email_id": "atillman@arrowheadep.com"}
    s.run_cycle()  # first refresh: records SDP status "In Progress"
    req["status"] = {"name": "On Hold"}
    s.run_cycle()
    req["status"] = {"name": "Resolved"}
    s.run_cycle()
    assert kinds(s.state, 4) == ["routed", "status", "status", "resolved"]
    assert "by Amanda Tillman" in s.state.events(4)[0]["message"]


def test_repeated_failures_are_logged_once():
    from watchtower.http import APIError
    s, aw, sdp = make()
    s.people = {}
    sdp.create_exc = APIError("ServiceDesk", "POST", "/requests", 400,
                              '{"response_status":{"messages":[{"message":"Invalid priority"}]}}')
    aw.add(5)
    for _ in range(3):
        s.run_cycle()
    events = s.state.events(5)
    assert len(events) == 1 and "Invalid priority" in events[0]["message"]


def test_refresh_failure_marks_ticket_stale():
    s, aw, sdp = make()
    aw.add(6)
    s.run_cycle()
    sdp.get_request = lambda rid: (_ for _ in ()).throw(
        __import__("requests").ConnectionError("down"))
    s.run_cycle()
    st = ticket_status(s.state.get(6), ["Resolved", "Closed"], timedelta(minutes=3), NOW)
    assert st.stale and st.group == "attention"
    assert "could not be refreshed" in st.detail


def _row(**kw):
    base = dict(aw_id=1, state="open", last_error=None, closed_by=None, owner_email=None, owner_name=None,
                sdp_status=None, refreshed_at=None, refresh_error=None)
    base.update(kw)
    return base


def test_status_labels_never_say_acknowledged():
    close = ["Resolved", "Closed"]
    win = timedelta(minutes=3)
    cases = {
        "Needs check": _row(state="creating"),
        "Routing failed": _row(state="failed_create", last_error="x"),
        "Routed": _row(owner_email="a@b.c", sdp_status="In Progress"),
        "Unassigned": _row(),
        "Resolving": _row(owner_email="a@b.c", sdp_status="Resolved"),
        "Close failed": _row(owner_email="a@b.c", last_error="AW close failed: boom"),
        "Resolved": _row(state="aw_closed", closed_by="sdp"),
        "Closed in Arctic Wolf": _row(state="aw_closed", closed_by="arcticwolf"),
    }
    for label, row in cases.items():
        st = ticket_status(row, close, win, NOW)
        assert st.label == label
        assert "acknowledged" not in st.label.lower()


def test_old_database_is_migrated(tmp_path):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE tickets (aw_id INTEGER PRIMARY KEY, sdp_id TEXT, state TEXT NOT NULL, aw_title TEXT,
          assigned_email TEXT, assigned_pd_id TEXT, assign_reason TEXT, created_at TEXT NOT NULL,
          aw_closed_at TEXT, closed_by TEXT, last_error TEXT);
        INSERT INTO tickets(aw_id, sdp_id, state, aw_title, assigned_email, created_at)
          VALUES (7, '1001', 'open', 'Old ticket', 'a@b.c', '2026-10-10T00:00:00Z');
    """)
    conn.commit()
    conn.close()
    st = State(str(db))
    row = st.get(7)
    assert row["owner_email"] is None and "refresh_error" in row.keys()
    st.record_event(7, "routed", "ok")
    assert st.events(7)[0]["message"] == "ok"
