"""Arctic Wolf Ticket API client (spec: Ticket API 1.0.0, OpenAPI 3.1).

The API supports list / get / create / close / comment / attachment only.
There is no endpoint to set or change a ticket's assignee.
"""

from __future__ import annotations

import re
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


# ---- Organization lookup (Arctic Wolf Organizations API) ---------------------
# Arctic Wolf's docs: call this with your Personal API Key to learn which region
# (POD) and organization ID to use with the Ticket API.

ORGANIZATIONS_URL = "https://eloc.global-prod.arcticwolf.net/api/v1/organizations"
TICKET_API_URL = "https://ticket-api.managedgw.{pod}-prod.arcticwolf.net"

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
_POD = re.compile(r"^[a-z]{2}\d{3}$", re.I)


def _flatten(d: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in d.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_flatten(value, f"{name}."))
        elif isinstance(value, (str, int, float, bool)) and value != "":
            out[name] = str(value)
    return out


def _find_records(data) -> list[dict]:
    """The first list of objects in the response, wherever the API nests it."""
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        for value in data.values():
            found = _find_records(value)
            if found:
                return found
        return [data] if any(_UUID.match(str(v)) for v in _flatten(data).values()) else []
    return []


def describe_organization(record: dict) -> dict:
    """Pick out the organization ID, region (POD) and name from one record."""
    fields = _flatten(record)

    def first(keys_like: tuple[str, ...], pattern: re.Pattern | None = None) -> str | None:
        ranked = sorted(fields.items(), key=lambda kv: not any(k in kv[0].lower() for k in keys_like))
        for key, value in ranked:
            if pattern is not None and not pattern.match(value):
                continue
            if pattern is None and not any(k in key.lower() for k in keys_like):
                continue
            return value
        return None

    org_id = first(("organizationuuid", "organizationid", "uuid", "id"), _UUID)
    pod = first(("pod", "region", "location", "datacenter"), _POD)
    name = first(("name",))
    return {
        "id": org_id.lower() if org_id else None,
        "pod": pod.lower() if pod else None,
        "name": name,
        "base_url": TICKET_API_URL.format(pod=pod.lower()) if pod else None,
        "fields": fields,
    }


def lookup_organizations(token: str) -> list[dict]:
    session = make_session()
    session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/json"})
    resp = check("ArcticWolf", session.get(ORGANIZATIONS_URL, timeout=DEFAULT_TIMEOUT))
    return [describe_organization(r) for r in _find_records(resp.json())]
