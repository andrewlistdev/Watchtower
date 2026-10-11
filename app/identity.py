"""Identity map: PagerDuty user ID -> ServiceDesk Plus technician (and Arctic Wolf name)."""

from __future__ import annotations

import csv
from dataclasses import dataclass


@dataclass(frozen=True)
class Person:
    pagerduty_user: str
    pagerduty_id: str
    aw_assignee: str
    aw_email: str
    sdp_email: str
    active: bool


def load_identity_map(path: str) -> dict[str, Person]:
    """Load the CSV, keyed by PagerDuty ID. sdp_email falls back to aw_email when blank."""
    people: dict[str, Person] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            pd_id = (row.get("pagerduty_id") or "").strip()
            if not pd_id:
                continue
            aw_email = (row.get("aw_email") or "").strip()
            people[pd_id] = Person(
                pagerduty_user=(row.get("pagerduty_user") or "").strip(),
                pagerduty_id=pd_id,
                aw_assignee=(row.get("aw_assignee") or "").strip(),
                aw_email=aw_email,
                sdp_email=(row.get("sdp_email") or "").strip() or aw_email,
                active=(row.get("status") or "").strip().lower() == "active",
            )
    return people
