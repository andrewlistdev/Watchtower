"""Shift-handoff rule, kept free of I/O so it can be unit tested.

Rule: a new ticket goes to whoever is on shift now, unless their shift ends within
HANDOFF_MINUTES, in which case it goes to the person coming on shift next.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class ScheduleEntry:
    user_id: str
    user_name: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Selection:
    entry: ScheduleEntry
    reason: str


def parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def merge_adjacent(entries: list[ScheduleEntry]) -> list[ScheduleEntry]:
    """Join back-to-back entries for the same person.

    PagerDuty can split one person's shift into several rendered entries (layer
    boundaries, overrides). Without merging, the handoff window would fire at the
    split point instead of at the real end of their shift.
    """
    merged: list[ScheduleEntry] = []
    for e in sorted(entries, key=lambda x: x.start):
        last = merged[-1] if merged else None
        if last and last.user_id == e.user_id and e.start <= last.end:
            merged[-1] = ScheduleEntry(last.user_id, last.user_name, last.start, max(last.end, e.end))
        else:
            merged.append(e)
    return merged


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def pick_on_shift(
    entries: list[ScheduleEntry], now: datetime, handoff_minutes: int = 30
) -> Selection | None:
    shifts = merge_adjacent(entries)
    handoff = timedelta(minutes=handoff_minutes)

    current = next((s for s in shifts if s.start <= now < s.end), None)
    if current is None:
        upcoming = next((s for s in shifts if s.start > now), None)
        if upcoming is None:
            return None
        return Selection(
            upcoming,
            f"No one on shift now; {upcoming.user_name} comes on at {_fmt(upcoming.start)}",
        )

    remaining = current.end - now
    if remaining > handoff:
        return Selection(
            current,
            f"{current.user_name} is on shift until {_fmt(current.end)}",
        )

    following = next(
        (s for s in shifts if s.start >= current.end and s.user_id != current.user_id), None
    )
    if following is None:
        return Selection(
            current,
            f"{current.user_name}'s shift ends at {_fmt(current.end)} but no next shift is "
            f"scheduled in the lookahead window, so it stays with them",
        )
    minutes_left = int(remaining.total_seconds() // 60)
    return Selection(
        following,
        f"{current.user_name}'s shift ends in {minutes_left} min "
        f"(at {_fmt(current.end)}), so it goes to {following.user_name}, next on shift",
    )
