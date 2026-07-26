"""IDOR suite placeholders — real cases land with first user-owned routers (FR-005b)."""

import pytest


@pytest.mark.idor
def test_idor_suite_is_wired() -> None:
    """Ensures `pytest -m idor` collects at least one test in CI."""
    assert True
