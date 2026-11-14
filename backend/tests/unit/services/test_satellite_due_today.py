"""Schedule flag without a database session."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from app.models.catalog import Exercise
from app.services.today import _satellite_due_today


def test_satellite_due_today_weekdays_and_categories() -> None:
    monday = date(2026, 9, 7)  # ISO Monday
    sat = Exercise(
        id=uuid4(),
        kind="satellite",
        name="WD",
        exercise_type="B",
        schedule_kind="weekdays",
        weekdays=[1, 3, 5],
        active_metrics={"schema_version": 1, "metrics": ["reps"]},
    )
    assert _satellite_due_today(sat, local_date=monday, is_rest_day=True) is True
    assert (
        _satellite_due_today(sat, local_date=date(2026, 9, 8), is_rest_day=False)
        is False
    )

    post = Exercise(
        id=uuid4(),
        kind="satellite",
        name="Post",
        exercise_type="B",
        schedule_kind="category",
        schedule_category="post_workout",
        active_metrics={"schema_version": 1, "metrics": ["reps"]},
    )
    assert _satellite_due_today(post, local_date=monday, is_rest_day=True) is False
    assert _satellite_due_today(post, local_date=monday, is_rest_day=False) is True

    rest = Exercise(
        id=uuid4(),
        kind="satellite",
        name="Rest",
        exercise_type="C",
        schedule_kind="category",
        schedule_category="rest_day",
        active_metrics={"schema_version": 1, "metrics": []},
    )
    assert _satellite_due_today(rest, local_date=monday, is_rest_day=True) is True
    assert _satellite_due_today(rest, local_date=monday, is_rest_day=False) is False
