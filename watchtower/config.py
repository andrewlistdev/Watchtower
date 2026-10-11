"""Runtime configuration, resolved from the admin GUI settings (with environment fallback)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


class ConfigMissing(Exception):
    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__("Missing required settings: " + ", ".join(missing))


def _bool(value: str | None, default: bool) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _list(value: str | None) -> list[str]:
    return [p.strip() for p in (value or "").split(",") if p.strip()]


@dataclass
class Config:
    # Arctic Wolf
    aw_base_url: str
    aw_api_token: str
    aw_org_uuid: str
    aw_open_statuses: list[str]
    aw_backfill_open: bool

    # ServiceDesk Plus Cloud (Zoho OAuth)
    sdp_base_url: str
    zoho_accounts_url: str
    zoho_client_id: str
    zoho_client_secret: str
    zoho_refresh_token: str
    sdp_ack_status: str
    sdp_close_statuses: list[str]
    sdp_requester_email: str
    sdp_group: str
    sdp_aw_id_udf: str
    sdp_fallback_technician_email: str

    # PagerDuty
    pd_api_token: str
    pd_schedule_id: str
    handoff_minutes: int
    pd_lookahead_hours: int

    # Behaviour
    poll_seconds: int
    dry_run: bool
    aw_closed_note: bool
    priority_map: dict[str, str] = field(default_factory=dict)
    display_timezone: str = "UTC"

    @property
    def zone(self):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            return ZoneInfo(self.display_timezone or "UTC")
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo("UTC")

    @classmethod
    def load(cls, get: Callable[[str], str | None]) -> "Config":
        """Build from a lookup function (SettingsStore.resolved). Raises ConfigMissing."""
        from .settings_store import FIELDS, SECTIONS

        titles = {key: title for key, title, _ in SECTIONS}
        missing = [f"{titles[f.section]}: {f.label}" for f in FIELDS if f.required and not get(f.key)]
        if missing:
            raise ConfigMissing(missing)

        def s(key: str) -> str:
            return (get(key) or "").strip()

        return cls(
            aw_base_url=s("aw_base_url").rstrip("/"),
            aw_api_token=s("aw_api_token"),
            aw_org_uuid=s("aw_org_uuid"),
            aw_open_statuses=_list(get("aw_open_statuses")),
            aw_backfill_open=_bool(get("aw_backfill_open"), False),
            sdp_base_url=s("sdp_base_url").rstrip("/"),
            zoho_accounts_url=s("zoho_accounts_url").rstrip("/"),
            zoho_client_id=s("zoho_client_id"),
            zoho_client_secret=s("zoho_client_secret"),
            zoho_refresh_token=s("zoho_refresh_token"),
            sdp_ack_status=s("sdp_ack_status"),
            sdp_close_statuses=_list(get("sdp_close_statuses")),
            sdp_requester_email=s("sdp_requester_email"),
            sdp_group=s("sdp_group"),
            sdp_aw_id_udf=s("sdp_aw_id_udf"),
            sdp_fallback_technician_email=s("sdp_fallback_technician_email"),
            pd_api_token=s("pd_api_token"),
            pd_schedule_id=s("pd_schedule_id"),
            handoff_minutes=int(s("handoff_minutes") or 30),
            pd_lookahead_hours=int(s("pd_lookahead_hours") or 48),
            poll_seconds=max(15, int(s("poll_seconds") or 60)),
            dry_run=_bool(get("dry_run"), True),
            aw_closed_note=_bool(get("aw_closed_note"), True),
            priority_map={
                "LOW": s("sdp_priority_low"),
                "NORMAL": s("sdp_priority_normal"),
                "HIGH": s("sdp_priority_high"),
                "URGENT": s("sdp_priority_urgent"),
            },
            display_timezone=s("display_timezone") or "UTC",
        )
