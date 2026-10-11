"""ServiceDesk Plus Cloud (v3 API) client using Zoho OAuth refresh tokens.

Notes from the SDP Cloud v3 docs:
  * Auth header:  Authorization: Zoho-oauthtoken <access token>
  * Accept:       application/vnd.manageengine.sdp.v3+json
  * Writes send JSON in a form field named `input_data`
  * technician can be set by {"email_id": ...}; notes use the "request_note" wrapper
"""

from __future__ import annotations

import json
import time

import requests

from .http import DEFAULT_TIMEOUT, APIError, check, make_session

ACCEPT = "application/vnd.manageengine.sdp.v3+json"


class ServiceDeskClient:
    def __init__(
        self,
        base_url: str,
        accounts_url: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ):
        # base_url includes the portal, e.g. https://sdpondemand.manageengine.com/app/itdesk
        self.api = f"{base_url}/api/v3"
        self.accounts_url = accounts_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.session = make_session()
        self._token: str | None = None
        self._token_expires = 0.0

    # ---- auth -------------------------------------------------------------

    def _access_token(self, force: bool = False) -> str:
        if force or not self._token or time.time() >= self._token_expires:
            resp = check(
                "Zoho",
                requests.post(
                    f"{self.accounts_url}/oauth/v2/token",
                    params={
                        "refresh_token": self.refresh_token,
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "grant_type": "refresh_token",
                    },
                    timeout=DEFAULT_TIMEOUT,
                ),
            )
            data = resp.json()
            if "access_token" not in data:
                raise APIError("Zoho", "POST", "oauth/v2/token", resp.status_code, resp.text)
            self._token = data["access_token"]
            # Refresh two minutes early.
            self._token_expires = time.time() + int(data.get("expires_in", 3600)) - 120
        return self._token  # type: ignore[return-value]

    def _call(self, method: str, path: str, input_data: dict | None = None) -> dict:
        url = f"{self.api}{path}"
        for attempt in (1, 2):
            headers = {
                "Authorization": f"Zoho-oauthtoken {self._access_token(force=attempt == 2)}",
                "Accept": ACCEPT,
            }
            kwargs: dict = {"headers": headers, "timeout": DEFAULT_TIMEOUT}
            if input_data is not None:
                encoded = {"input_data": json.dumps(input_data)}
                if method == "GET":
                    kwargs["params"] = encoded
                else:
                    kwargs["data"] = encoded
            resp = self.session.request(method, url, **kwargs)
            # A 401 means the request was rejected, so retrying once with a fresh token is safe.
            if resp.status_code == 401 and attempt == 1:
                continue
            check("ServiceDesk", resp)
            data = resp.json()
            status = data.get("response_status")
            if isinstance(status, dict) and status.get("status") == "failed":
                raise APIError("ServiceDesk", method, url, resp.status_code, resp.text)
            return data
        raise AssertionError("unreachable")

    # ---- requests ---------------------------------------------------------

    def create_request(self, request: dict) -> dict:
        return self._call("POST", "/requests", {"request": request})["request"]

    def update_request(self, request_id: str, fields: dict) -> dict:
        return self._call("PUT", f"/requests/{request_id}", {"request": fields})["request"]

    def get_request(self, request_id: str) -> dict:
        return self._call("GET", f"/requests/{request_id}")["request"]

    def add_note(
        self,
        request_id: str,
        description: str,
        mark_first_response: bool = False,
        show_to_requester: bool = False,
    ) -> dict:
        return self._call(
            "POST",
            f"/requests/{request_id}/notes",
            {
                "request_note": {
                    "description": description,
                    "show_to_requester": show_to_requester,
                    "mark_first_response": mark_first_response,
                    "add_to_linked_requests": False,
                }
            },
        )

    def resolution_text(self, request: dict) -> str:
        """Best-effort resolution text for a request already fetched with get_request."""
        resolution = request.get("resolution") or {}
        content = resolution.get("content") if isinstance(resolution, dict) else None
        if content:
            return content
        try:
            data = self._call("GET", f"/requests/{request['id']}/resolutions")
            return (data.get("resolution") or {}).get("content") or ""
        except APIError:
            return ""

    def ping(self) -> None:
        self._call("GET", "/requests", {"list_info": {"row_count": 1}})
