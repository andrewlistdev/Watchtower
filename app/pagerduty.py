"""PagerDuty REST API v2 client: reads the rendered (final) on-call schedule."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .http import DEFAULT_TIMEOUT, check, make_session
from .oncall import ScheduleEntry, parse_ts


class PagerDutyClient:
    def __init__(self, token: str):
        self.session = make_session()
        self.session.headers.update(
            {
                "Authorization": f"Token token={token}",
                "Accept": "application/vnd.pagerduty+json;version=2",
            }
        )

    def schedule_entries(
        self, schedule_id: str, now: datetime, lookahead_hours: int
    ) -> list[ScheduleEntry]:
        """Final-schedule entries (overrides applied) from now through the lookahead window."""
        since = now.astimezone(timezone.utc).replace(microsecond=0)
        until = since + timedelta(hours=lookahead_hours)
        resp = check(
            "PagerDuty",
            self.session.get(
                f"https://api.pagerduty.com/schedules/{schedule_id}",
                params={
                    "since": since.isoformat(),
                    "until": until.isoformat(),
                    "time_zone": "UTC",
                },
                timeout=DEFAULT_TIMEOUT,
            ),
        )
        schedule = resp.json()["schedule"]
        rendered = (schedule.get("final_schedule") or {}).get("rendered_schedule_entries") or []
        entries = []
        for e in rendered:
            user = e.get("user") or {}
            if not user.get("id"):
                continue
            entries.append(
                ScheduleEntry(
                    user_id=user["id"],
                    user_name=user.get("summary", user["id"]),
                    start=parse_ts(e["start"]),
                    end=parse_ts(e["end"]),
                )
            )
        entries.sort(key=lambda x: x.start)
        return entries
