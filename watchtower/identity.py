"""A person who can be assigned tickets (managed on the People page)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Person:
    pagerduty_user: str
    pagerduty_id: str
    aw_assignee: str
    aw_email: str
    sdp_email: str  # falls back to aw_email when blank
    active: bool
