"""Unit tests for last-session sets summary formatting."""

from __future__ import annotations

from app.services.sessions import summarize_sets_payload


def test_summarize_uniform_reps() -> None:
    assert (
        summarize_sets_payload(
            {
                "schema_version": 1,
                "sets": [{"reps": 10}, {"reps": 10}, {"reps": 10}],
            }
        )
        == "3×10"
    )


def test_summarize_mixed_reps() -> None:
    assert (
        summarize_sets_payload(
            {"schema_version": 1, "sets": [{"reps": 10}, {"reps": 8}, {"reps": 10}]}
        )
        == "10/8/10"
    )


def test_summarize_uniform_duration() -> None:
    assert (
        summarize_sets_payload(
            {
                "schema_version": 1,
                "sets": [{"duration_sec": 20}, {"duration_sec": 20}],
            }
        )
        == "2×20s"
    )


def test_summarize_completed_type_c() -> None:
    assert (
        summarize_sets_payload({"schema_version": 1, "completed": True, "sets": []})
        == "completed"
    )


def test_summarize_empty() -> None:
    assert summarize_sets_payload(None) is None
    assert summarize_sets_payload({"schema_version": 1, "sets": []}) is None
