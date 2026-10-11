import re
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from watchtower.oncall import ScheduleEntry
from watchtower.runtime import shift_view
from watchtower.settings_store import SettingsStore
from watchtower.web import create_app, strip_layout

SECRET = "aw-super-secret-token-12345678"


def csrf(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    for var in ("AW_API_TOKEN", "APP_ENCRYPTION_KEY"):
        monkeypatch.delenv(var, raising=False)
    db = str(tmp_path / "state.db")
    store = SettingsStore(db)
    app = create_app(store, worker=None, db_path=db)
    app.testing = True
    return app, store, db


def sign_up(app):
    client = app.test_client()
    page = client.get("/setup").get_data(as_text=True)
    token = app.extensions["setup_token"]()
    resp = client.post("/setup", data={"csrf": csrf(page), "code": token, "username": "andrew",
                                       "password": "correct horse battery", "confirm": "correct horse battery"})
    assert resp.status_code == 302
    return client


def test_first_visit_requires_setup_code(env):
    app, store, _ = env
    client = app.test_client()
    assert client.get("/").headers["Location"].endswith("/setup")
    page = client.get("/setup").get_data(as_text=True)
    resp = client.post("/setup", data={"csrf": csrf(page), "code": "wrong", "username": "andrew",
                                       "password": "correct horse battery", "confirm": "correct horse battery"})
    assert "doesn&#39;t match" in resp.get_data(as_text=True)
    assert not store.has_admin()


def test_setup_creates_admin_and_signs_in(env):
    app, store, _ = env
    client = sign_up(app)
    assert store.has_admin()
    assert client.get("/settings").status_code == 200
    # Setup page is closed once an admin exists.
    assert client.get("/setup").status_code == 302


def test_post_without_csrf_is_rejected(env):
    app, _, _ = env
    client = sign_up(app)
    assert client.post("/settings", data={"aw_org_uuid": "x"}).status_code == 400


def test_signed_out_users_are_sent_to_login(env):
    app, _, _ = env
    sign_up(app)
    fresh = app.test_client()
    assert "/login" in fresh.get("/settings").headers["Location"]


def test_wrong_password_and_lockout(env):
    app, _, _ = env
    sign_up(app)
    c = app.test_client()
    for _ in range(5):
        page = c.get("/login").get_data(as_text=True)
        r = c.post("/login", data={"csrf": csrf(page), "username": "andrew", "password": "nope nope nope"})
        assert "incorrect" in r.get_data(as_text=True)
    page = c.get("/login").get_data(as_text=True)
    r = c.post("/login", data={"csrf": csrf(page), "username": "andrew", "password": "correct horse battery"})
    assert "Too many failed attempts" in r.get_data(as_text=True)


def test_secret_is_encrypted_and_never_shown(env):
    app, store, db = env
    client = sign_up(app)
    page = client.get("/settings").get_data(as_text=True)
    client.post("/settings", data={"csrf": csrf(page), "aw_api_token": SECRET})
    raw = sqlite3.connect(db).execute("SELECT value, encrypted FROM settings WHERE key='aw_api_token'").fetchone()
    assert raw[1] == 1 and SECRET not in raw[0]
    assert store.resolved("aw_api_token") == SECRET
    html = client.get("/settings").get_data(as_text=True)
    assert SECRET not in html
    assert "ends in 5678" in html


def test_blank_secret_keeps_value_and_remove_clears_it(env):
    app, store, _ = env
    client = sign_up(app)
    page = client.get("/settings").get_data(as_text=True)
    client.post("/settings", data={"csrf": csrf(page), "pd_api_token": SECRET})
    page = client.get("/settings").get_data(as_text=True)
    client.post("/settings", data={"csrf": csrf(page), "pd_api_token": ""})
    assert store.resolved("pd_api_token") == SECRET
    page = client.get("/settings").get_data(as_text=True)
    client.post("/settings", data={"csrf": csrf(page), "clear_pd_api_token": "on"})
    assert store.resolved("pd_api_token") is None


def test_validation_blocks_bad_values(env):
    app, store, _ = env
    client = sign_up(app)
    page = client.get("/settings").get_data(as_text=True)
    resp = client.post("/settings", data={"csrf": csrf(page), "aw_org_uuid": "not-a-uuid",
                                          "aw_api_token": SECRET})
    html = resp.get_data(as_text=True)
    assert "isn&#39;t a UUID" in html
    assert store.saved("aw_org_uuid") is None and store.saved("aw_api_token") is None  # nothing saved


def test_changes_are_audited_without_values(env):
    app, store, _ = env
    client = sign_up(app)
    page = client.get("/settings").get_data(as_text=True)
    client.post("/settings", data={"csrf": csrf(page), "aw_api_token": SECRET,
                                   "aw_org_uuid": "550e8400-e29b-41d4-a716-446655440000"})
    actions = " ".join(r["action"] for r in store.recent_audit())
    assert "API token" in actions and SECRET not in actions


def test_bool_toggle_and_defaults_not_saved(env):
    app, store, _ = env
    client = sign_up(app)
    page = client.get("/settings").get_data(as_text=True)
    # Submitting the page untouched (defaults shown) must not save anything.
    client.post("/settings", data={"csrf": csrf(page), "present_dry_run": "1", "dry_run": "on",
                                   "sdp_ack_status": "In Progress"})
    assert store.saved("dry_run") is None and store.saved("sdp_ack_status") is None
    page = client.get("/settings").get_data(as_text=True)
    client.post("/settings", data={"csrf": csrf(page), "present_dry_run": "1"})  # unchecked
    assert store.resolved("dry_run") == "false"


def test_people_save_and_validation(env):
    app, store, _ = env
    client = sign_up(app)
    page = client.get("/responders").get_data(as_text=True)
    bad = client.post("/responders", data={"csrf": csrf(page), "p-0-pagerduty_user": "Amanda",
                                       "p-0-pagerduty_id": "nope", "p-0-aw_email": "a@x.com"})
    assert "should look like" in bad.get_data(as_text=True)
    page = client.get("/responders").get_data(as_text=True)
    client.post("/responders", data={
        "csrf": csrf(page),
        "p-0-pagerduty_user": "Amanda Tillman", "p-0-pagerduty_id": "ppsnfck",
        "p-0-aw_email": "atillman@arrowheadep.com", "p-0-active": "on",
        "p-1-pagerduty_user": "Soulaymane", "p-1-pagerduty_id": "PZWPPTP",
        "p-1-aw_email": "soulaymane.ben-el-arabi@mybihr.com", "p-1-sdp_email": "sbenelarabi@arrowheadep.com",
    })
    people = store.people_map()
    assert people["PPSNFCK"].sdp_email == "atillman@arrowheadep.com" and people["PPSNFCK"].active
    assert people["PZWPPTP"].sdp_email == "sbenelarabi@arrowheadep.com" and not people["PZWPPTP"].active


def test_dashboard_waits_for_settings(env):
    app, _, _ = env
    client = sign_up(app)
    html = client.get("/").get_data(as_text=True)
    assert "PagerDuty settings" in html


def test_seed_people_from_csv(env, tmp_path):
    _, store, _ = env
    csv_path = tmp_path / "map.csv"
    csv_path.write_text("pagerduty_user,pagerduty_id,aw_assignee,aw_email,sdp_email,status\n"
                        "Doug Feltner,PE77ZFQ,Doug Feltner,dfeltner@arrowheadep.com,,Active\n")
    assert store.seed_people_from_csv(str(csv_path)) == 1
    assert store.seed_people_from_csv(str(csv_path)) == 0  # only on first start


def test_strip_layout_marks_handoff(env):
    from watchtower.config import Config
    _, store, _ = env
    now = datetime(2026, 10, 12, 14, 40, tzinfo=timezone.utc)
    entries = [
        ScheduleEntry("PPSNFCK", "Amanda Tillman", now - timedelta(hours=7), now + timedelta(minutes=20)),
        ScheduleEntry("PE77ZFQ", "Doug Feltner", now + timedelta(minutes=20), now + timedelta(hours=8)),
    ]
    cfg = Config(**{**dict(aw_base_url="", aw_api_token="", aw_org_uuid="", aw_open_statuses=[],
                           aw_backfill_open=False, sdp_base_url="", zoho_accounts_url="", zoho_client_id="",
                           zoho_client_secret="", zoho_refresh_token="", sdp_ack_status="",
                           sdp_close_statuses=[], sdp_requester_email="", sdp_group="", sdp_aw_id_udf="",
                           sdp_fallback_technician_email="", pd_api_token="", pd_schedule_id="",
                           handoff_minutes=30, pd_lookahead_hours=48, poll_seconds=60, dry_run=True,
                           aw_closed_note=True)})
    view = shift_view(cfg, {}, now=now, entries=entries)
    assert "Doug Feltner" in view.reason  # inside the handoff window
    layout = strip_layout(view, ZoneInfo("America/New_York"))
    assert layout["now_x"] == pytest.approx(166.7, abs=0.2)  # 2h into a 12h window
    assert layout["handoff"]["x"] < layout["now_x"] < layout["handoff"]["x"] + layout["handoff"]["w"]
    assert [b["current"] for b in layout["blocks"]] == [True, False]


def test_old_people_address_redirects(env):
    app, _, _ = env
    client = sign_up(app)
    resp = client.get("/people")
    assert resp.status_code == 301 and resp.headers["Location"].endswith("/responders")


def test_theme_defaults_to_dark_and_can_be_changed(env):
    app, _, _ = env
    client = sign_up(app)
    assert 'data-theme="dark"' in client.get("/account").get_data(as_text=True)
    page = client.get("/account").get_data(as_text=True)
    resp = client.post("/account", data={"csrf": csrf(page), "action": "theme", "theme": "light"})
    assert "wt_theme=light" in resp.headers["Set-Cookie"]
    assert 'data-theme="light"' in client.get("/").get_data(as_text=True)
    page = client.get("/account").get_data(as_text=True)
    client.post("/account", data={"csrf": csrf(page), "action": "theme", "theme": "<script>"})
    assert 'data-theme="dark"' in client.get("/").get_data(as_text=True)


def _seed_ticket(db):
    from watchtower.state import State
    st = State(db)
    st.begin_create(48211, "Suspicious PowerShell on FIN-LT-042")
    st.finish_create(48211, "1043", "atillman@arrowheadep.com", "PPSNFCK",
                     "Amanda Tillman is on call until Mon 7:00 PM EDT.", "Amanda Tillman")
    st.record_event(48211, "routed", "Routed to Amanda Tillman in ServiceDesk Plus request #1043.")
    return st


def test_overview_lists_tickets_with_owner_and_status(env):
    app, _, db = env
    client = sign_up(app)
    _seed_ticket(db)
    html = client.get("/").get_data(as_text=True)
    assert "Suspicious PowerShell" in html and "Amanda Tillman" in html and ">Routed<" in html
    assert "Acknowledged" not in html
    assert "No tickets match this filter." in client.get("/?show=closed").get_data(as_text=True)


def test_ticket_page_shows_reason_and_history(env):
    app, _, db = env
    client = sign_up(app)
    _seed_ticket(db)
    html = client.get("/tickets/48211").get_data(as_text=True)
    assert "Why Watchtower routed it here" in html and "on call until" in html
    assert "Routed to Amanda Tillman in ServiceDesk Plus request #1043." in html
    assert client.get("/tickets/99999").status_code == 404


def test_activity_merges_routing_and_settings(env):
    app, _, db = env
    client = sign_up(app)
    _seed_ticket(db)
    html = client.get("/activity").get_data(as_text=True)
    assert "Routed to Amanda Tillman" in html and "Created the first admin account." in html
    settings_only = client.get("/activity?kind=settings").get_data(as_text=True)
    assert "Routed to Amanda Tillman" not in settings_only


def test_logo_component_renders_inline_svg(env):
    app, _, _ = env
    client = sign_up(app)
    html = client.get("/").get_data(as_text=True)
    assert 'class="wt-logo wt-logo--auto"' in html and 'aria-label="Watchtower"' in html
    assert 'href="/static/brand/favicon.svg"' in html
