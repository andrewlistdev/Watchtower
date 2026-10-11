"""Runtime configuration, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _req(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def _opt(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: str) -> list[str]:
    return [p.strip() for p in _opt(name, default).split(",") if p.strip()]


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

    # Service behaviour
    poll_seconds: int
    dry_run: bool
    aw_closed_note: bool
    identity_map_path: str
    db_path: str
    priority_map: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Config":
        priority_map = {
            "LOW": _opt("SDP_PRIORITY_LOW", "Low"),
            "NORMAL": _opt("SDP_PRIORITY_NORMAL", "Medium"),
            "HIGH": _opt("SDP_PRIORITY_HIGH", "High"),
            "URGENT": _opt("SDP_PRIORITY_URGENT", "Urgent"),
        }
        return cls(
            aw_base_url=_req("AW_BASE_URL").rstrip("/"),
            aw_api_token=_req("AW_API_TOKEN"),
            aw_org_uuid=_req("AW_ORG_UUID"),
            aw_open_statuses=_list("AW_OPEN_STATUSES", "NEW,OPEN,HOLD,PENDING"),
            aw_backfill_open=_bool("AW_BACKFILL_OPEN", False),
            sdp_base_url=_req("SDP_BASE_URL").rstrip("/"),
            zoho_accounts_url=_opt("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.com").rstrip("/"),
            zoho_client_id=_req("ZOHO_CLIENT_ID"),
            zoho_client_secret=_req("ZOHO_CLIENT_SECRET"),
            zoho_refresh_token=_req("ZOHO_REFRESH_TOKEN"),
            sdp_ack_status=_opt("SDP_ACK_STATUS", "In Progress"),
            sdp_close_statuses=_list("SDP_CLOSE_STATUSES", "Resolved,Closed"),
            sdp_requester_email=_opt("SDP_REQUESTER_EMAIL"),
            sdp_group=_opt("SDP_GROUP"),
            sdp_aw_id_udf=_opt("SDP_AW_ID_UDF"),
            sdp_fallback_technician_email=_opt("SDP_FALLBACK_TECHNICIAN_EMAIL"),
            pd_api_token=_req("PD_API_TOKEN"),
            pd_schedule_id=_req("PD_SCHEDULE_ID"),
            handoff_minutes=int(_opt("HANDOFF_MINUTES", "30")),
            pd_lookahead_hours=int(_opt("PD_LOOKAHEAD_HOURS", "48")),
            poll_seconds=int(_opt("POLL_SECONDS", "60")),
            dry_run=_bool("DRY_RUN", True),
            aw_closed_note=_bool("AW_CLOSED_NOTE", True),
            identity_map_path=_opt("IDENTITY_MAP_PATH", "/app/config/identity_map.csv"),
            db_path=_opt("DB_PATH", "/data/state.db"),
            priority_map=priority_map,
        )
