"""Ticket state -> what the admin page shows (BRAND_GUIDE.md §5 "Status distinction").

Watchtower never shows "Acknowledged": it can see that a ticket was routed and what
ServiceDesk Plus reports, but not that the responder accepted responsibility.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Tones map to the wt-status-* colour tokens.
TONES = ("unassigned", "routed", "acknowledged", "escalated", "resolved", "error", "info")

FILTERS = {
    "all": "All",
    "attention": "Needs attention",
    "routed": "Routed",
    "closed": "Closed",
}


@dataclass(frozen=True)
class TicketStatus:
    key: str
    label: str
    tone: str
    detail: str = ""
    stale: bool = False

    @property
    def group(self) -> str:
        if self.key in ("unknown", "failed", "unassigned", "close_failed") or self.stale:
            return "attention"
        if self.key == "routed":
            return "routed"
        return "closed"


def api_message(text: str | None) -> str:
    """Pull the readable message out of a stored API error."""
    if not text:
        return ""
    messages = re.findall(r'"message"\s*:\s*"([^"]+)"', text)
    if messages:
        return "; ".join(dict.fromkeys(messages))
    return text[:200]


def ticket_status(row, close_statuses: list[str], stale_after: timedelta,
                  now: datetime | None = None) -> TicketStatus:
    now = now or datetime.now(timezone.utc)
    state = row["state"]
    aw_id = row["aw_id"]

    if state == "creating":
        return TicketStatus("unknown", "Needs check", "escalated",
                            f"ServiceDesk Plus didn't confirm the request was created. Search SDP for "
                            f"[AW-{aw_id}], then link or recreate it.")
    if state == "failed_create":
        return TicketStatus("failed", "Routing failed", "error",
                            f"Couldn't create the ServiceDesk Plus request: {api_message(row['last_error'])}. "
                            f"Retrying each check.")
    if state == "aw_closed":
        if row["closed_by"] == "arcticwolf":
            return TicketStatus("closed_by_source", "Closed in Arctic Wolf", "info",
                                "Arctic Wolf closed it first. The ServiceDesk Plus request may still be open.")
        return TicketStatus("resolved", "Resolved", "resolved",
                            "Resolved in ServiceDesk Plus. Arctic Wolf ticket closed.")

    # Open in SDP.
    stale = bool(row["refresh_error"])
    if not stale and row["refreshed_at"]:
        refreshed = datetime.fromisoformat(row["refreshed_at"].replace("Z", "+00:00"))
        stale = now - refreshed > stale_after
    stale_note = " Ticket status could not be refreshed. The displayed state may be out of date." if stale else ""

    error = row["last_error"] or ""
    if error.startswith("AW close failed"):
        return TicketStatus("close_failed", "Close failed", "error",
                            f"Resolved in ServiceDesk Plus, but closing the Arctic Wolf ticket failed: "
                            f"{api_message(error.split(':', 1)[-1])}. Retrying each check.{stale_note}", stale)
    sdp_status = row["sdp_status"]
    if sdp_status and sdp_status.lower() in {s.lower() for s in close_statuses}:
        return TicketStatus("closing", "Resolving", "resolved",
                            f"Marked {sdp_status} in ServiceDesk Plus. Arctic Wolf ticket closes on the next "
                            f"check.{stale_note}", stale)
    if row["owner_email"] or row["owner_name"]:
        detail = f"ServiceDesk Plus status: {sdp_status}." if sdp_status else ""
        return TicketStatus("routed", "Routed", "routed", (detail + stale_note).strip(), stale)
    return TicketStatus("unassigned", "Unassigned", "unassigned",
                        ("No owner in ServiceDesk Plus." + stale_note).strip(), stale)
