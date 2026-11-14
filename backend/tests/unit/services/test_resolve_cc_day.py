"""Fixed-weekday CC day resolution. Clock is an argument."""

from __future__ import annotations

from datetime import date

from app.services.cc_day import resolve_cc_day


def test_resolve_cc_day_mon_wed_fri_anchor_1() -> None:
    # 2026-07-27 is Monday
    mon = date(2026, 7, 27)
    assert resolve_cc_day(mon, anchor_weekday=1).day_index == 1
    assert resolve_cc_day(date(2026, 7, 28), anchor_weekday=1).is_rest_day
    assert resolve_cc_day(date(2026, 7, 29), anchor_weekday=1).day_index == 2
    assert resolve_cc_day(date(2026, 7, 31), anchor_weekday=1).day_index == 3

def test_resolve_cc_day_rotation_offset() -> None:
    mon = date(2026, 7, 27)
    r = resolve_cc_day(mon, anchor_weekday=1, rotation_offset=1)
    assert r.day_index == 2

def test_resolve_cc_day_before_started_on() -> None:
    r = resolve_cc_day(
        date(2026, 7, 27),
        anchor_weekday=1,
        started_on=date(2026, 8, 1),
    )
    assert r.before_started_on
    assert r.is_rest_day
