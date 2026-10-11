from datetime import datetime, timedelta, timezone

from app.oncall import ScheduleEntry, merge_adjacent, pick_on_shift

T0 = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)


def shift(user, start_h, end_h):
    return ScheduleEntry(user, user.title(), T0 + timedelta(hours=start_h), T0 + timedelta(hours=end_h))


SCHEDULE = [shift("amanda", 0, 8), shift("doug", 8, 16), shift("jeff", 16, 24)]


def test_mid_shift_goes_to_current():
    sel = pick_on_shift(SCHEDULE, T0 + timedelta(hours=3), 30)
    assert sel.entry.user_id == "amanda"


def test_31_minutes_left_stays_with_current():
    sel = pick_on_shift(SCHEDULE, T0 + timedelta(hours=8) - timedelta(minutes=31), 30)
    assert sel.entry.user_id == "amanda"


def test_exactly_30_minutes_left_hands_off():
    sel = pick_on_shift(SCHEDULE, T0 + timedelta(hours=8) - timedelta(minutes=30), 30)
    assert sel.entry.user_id == "doug"
    assert "next on shift" in sel.reason


def test_5_minutes_left_hands_off():
    sel = pick_on_shift(SCHEDULE, T0 + timedelta(hours=16) - timedelta(minutes=5), 30)
    assert sel.entry.user_id == "jeff"


def test_split_entries_for_same_person_are_merged():
    # PagerDuty renders Amanda's shift as two pieces (e.g. a layer boundary at 04:00).
    split = [shift("amanda", 0, 4), shift("amanda", 4, 8), shift("doug", 8, 16)]
    assert len(merge_adjacent(split)) == 2
    # 04:00 minus 10 min would wrongly look like the end of a shift without merging.
    sel = pick_on_shift(split, T0 + timedelta(hours=4) - timedelta(minutes=10), 30)
    assert sel.entry.user_id == "amanda"


def test_handoff_skips_to_next_different_person():
    # Override gives Amanda a back-to-back extra hour; handoff goes to Doug at 09:00.
    sched = [shift("amanda", 0, 8), shift("amanda", 8, 9), shift("doug", 9, 16)]
    sel = pick_on_shift(sched, T0 + timedelta(hours=9) - timedelta(minutes=20), 30)
    assert sel.entry.user_id == "doug"


def test_gap_in_schedule_goes_to_next_person_coming_on():
    sched = [shift("amanda", 0, 8), shift("doug", 10, 16)]
    sel = pick_on_shift(sched, T0 + timedelta(hours=9), 30)
    assert sel.entry.user_id == "doug"


def test_handoff_with_no_next_shift_stays_with_current():
    sched = [shift("amanda", 0, 8)]
    sel = pick_on_shift(sched, T0 + timedelta(hours=8) - timedelta(minutes=10), 30)
    assert sel.entry.user_id == "amanda"


def test_empty_schedule_returns_none():
    assert pick_on_shift([], T0, 30) is None
