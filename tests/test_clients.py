import json
from datetime import datetime, timezone

from watchtower.arcticwolf import ArcticWolfClient
from watchtower.pagerduty import PagerDutyClient
from watchtower.servicedesk import ServiceDeskClient


class Resp:
    def __init__(self, status, data, url="https://x", method="GET"):
        self.status_code = status
        self._data = data
        self.text = json.dumps(data)
        self.url = url
        self.request = type("R", (), {"method": method})()

    def json(self):
        return self._data


def test_aw_list_follows_pagination():
    c = ArcticWolfClient("https://aw", "tok", "org")
    pages = [
        {"results": [{"id": i} for i in range(100)], "meta": {"offset": 0, "limit": 100, "total": 130}},
        {"results": [{"id": i} for i in range(100, 130)], "meta": {"offset": 100, "limit": 100, "total": 130}},
    ]
    seen = []

    def fake_get(url, params, timeout):
        seen.append(dict(params))
        return Resp(200, pages[len(seen) - 1])

    c.session.get = fake_get
    ids = [t["id"] for t in c.list_tickets(["NEW", "OPEN"], created_after="2026-10-12T00:00:00Z")]
    assert len(ids) == 130
    assert seen[0]["status"] == "NEW,OPEN" and seen[0]["createdAfter"] == "2026-10-12T00:00:00Z"
    assert seen[1]["offset"] == 100
    assert c.session.headers["Authorization"] == "Bearer tok"


def test_sdp_sends_input_data_form_and_refreshes_on_401(monkeypatch):
    c = ServiceDeskClient("https://sdp/app/itdesk", "https://accounts.zoho.com", "id", "sec", "ref")
    tokens = iter(["tok1", "tok2"])
    monkeypatch.setattr(
        "watchtower.servicedesk.requests.post",
        lambda url, params, timeout, headers=None: Resp(200, {"access_token": next(tokens), "expires_in": 3600}),
    )
    calls = []

    def fake_request(method, url, headers, timeout, data=None, params=None):
        calls.append((method, url, headers["Authorization"], data))
        if len(calls) == 1:
            return Resp(401, {"response_status": {"status": "failed"}}, url, method)
        return Resp(201, {"request": {"id": "555"}, "response_status": {"status": "success"}}, url, method)

    c.session.request = fake_request
    out = c.create_request({"subject": "x", "technician": {"email_id": "a@b.com"}})
    assert out["id"] == "555"
    method, url, auth, data = calls[1]
    assert url == "https://sdp/app/itdesk/api/v3/requests"
    assert auth == "Zoho-oauthtoken tok2"
    assert json.loads(data["input_data"]) == {"request": {"subject": "x", "technician": {"email_id": "a@b.com"}}}


def test_sdp_note_uses_request_note_wrapper(monkeypatch):
    c = ServiceDeskClient("https://sdp", "https://acc", "id", "sec", "ref")
    monkeypatch.setattr("watchtower.servicedesk.requests.post",
                        lambda url, params, timeout, headers=None: Resp(200, {"access_token": "t", "expires_in": 3600}))
    captured = {}

    def fake_request(method, url, headers, timeout, data=None, params=None):
        captured.update(url=url, body=json.loads(data["input_data"]))
        return Resp(200, {"response_status": {"status": "success"}}, url, method)

    c.session.request = fake_request
    c.add_note("42", "hello", mark_first_response=True)
    assert captured["url"].endswith("/requests/42/notes")
    assert captured["body"]["request_note"]["mark_first_response"] is True


def test_pagerduty_parses_final_schedule():
    c = PagerDutyClient("pdtok")
    payload = {"schedule": {"final_schedule": {"rendered_schedule_entries": [
        {"start": "2026-10-12T15:00:00Z", "end": "2026-10-12T23:00:00Z",
         "user": {"id": "PE77ZFQ", "summary": "Doug Feltner"}},
        {"start": "2026-10-12T08:00:00Z", "end": "2026-10-12T15:00:00Z",
         "user": {"id": "PPSNFCK", "summary": "Amanda Tillman"}},
    ]}}}
    c.session.get = lambda url, params, timeout: Resp(200, payload)
    entries = c.schedule_entries("SCHED", datetime(2026, 10, 12, 14, tzinfo=timezone.utc), 48)
    assert [e.user_id for e in entries] == ["PPSNFCK", "PE77ZFQ"]
    assert c.session.headers["Authorization"] == "Token token=pdtok"


def test_zoho_exchange_maps_errors(monkeypatch):
    import pytest
    from watchtower.http import APIError
    from watchtower.servicedesk import exchange_grant_code
    monkeypatch.setattr("watchtower.servicedesk.requests.post",
                        lambda url, params, headers, timeout: Resp(200, {"error": "invalid_code"}))
    with pytest.raises(APIError) as exc:
        exchange_grant_code("https://accounts.zoho.com", "id", "sec", "code")
    assert "expire" in exc.value.body
    monkeypatch.setattr("watchtower.servicedesk.requests.post",
                        lambda url, params, headers, timeout: Resp(200, {"access_token": "a", "refresh_token": "r"}))
    assert exchange_grant_code("https://accounts.zoho.com", "id", "sec", "code") == "r"


def test_org_lookup_parsing_handles_nesting():
    from watchtower.arcticwolf import _find_records, describe_organization
    data = {"data": {"organizations": [
        {"uuid": "8F14E45F-CEEA-4E7A-9B2B-3C1E7F0A1D22", "displayName": "Arrowhead", "location": {"pod": "eu001"}},
        {"id": "not-a-uuid", "name": "Other"},
    ]}}
    orgs = [describe_organization(r) for r in _find_records(data)]
    assert orgs[0]["id"] == "8f14e45f-ceea-4e7a-9b2b-3c1e7f0a1d22" and orgs[0]["pod"] == "eu001"
    assert orgs[0]["name"] == "Arrowhead"
    assert orgs[1]["id"] is None and orgs[1]["pod"] is None
