"""Arctic Wolf Ticket API client (spec: Ticket API 1.0.0, OpenAPI 3.1).

The API supports list / get / create / close / comment / attachment only.
There is no endpoint to set or change a ticket's assignee.
"""

from __future__ import annotations

from typing import Iterator

from .http import DEFAULT_TIMEOUT, APIError, check, make_session

PAGE_SIZE = 100  # API maximum


class ArcticWolfClient:
    def __init__(self, base_url: str, token: str, org_uuid: str):
        self.base = f"{base_url}/api/v1/organizations/{org_uuid}/tickets"
        self.session = make_session()
        self.session.headers.update(
            {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        )

    def list_tickets(
        self,
        statuses: list[str] | None = None,
        created_after: str | None = None,
        updated_after: str | None = None,
    ) -> Iterator[dict]:
        """Yield every ticket matching the filters, following offset pagination."""
        params: dict[str, str | int] = {"limit": PAGE_SIZE, "offset": 0}
        if statuses:
            params["status"] = ",".join(statuses)
        if created_after:
            params["createdAfter"] = created_after
        if updated_after:
            params["updatedAfter"] = updated_after
        while True:
            resp = check(
                "ArcticWolf",
                self.session.get(self.base, params=params, timeout=DEFAULT_TIMEOUT),
            )
            data = resp.json()
            results = data.get("results", [])
            yield from results
            meta = data.get("meta", {})
            params["offset"] = int(params["offset"]) + len(results)
            if not results or params["offset"] >= meta.get("total", 0):
                break

    def get_ticket(self, ticket_id: int) -> dict:
        resp = check(
            "ArcticWolf",
            self.session.get(f"{self.base}/{ticket_id}", timeout=DEFAULT_TIMEOUT),
        )
        return resp.json()

    def close_ticket(self, ticket_id: int, comment: str | None) -> dict:
        body = {"comment": comment[:65535]} if comment else {}
        resp = check(
            "ArcticWolf",
            self.session.post(
                f"{self.base}/{ticket_id}/close", json=body, timeout=DEFAULT_TIMEOUT
            ),
        )
        return resp.json()

    def is_closed(self, ticket_id: int) -> bool:
        try:
            return self.get_ticket(ticket_id).get("status") == "CLOSED"
        except APIError:
            return False
