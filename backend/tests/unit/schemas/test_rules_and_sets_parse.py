"""Sets and progression-rules parsers."""

from __future__ import annotations

import pytest

from app.schemas.common import parse_versioned
from app.schemas.rules import ProgressionRulesV1
from app.schemas.sets import SessionSetsV1
from app.services.errors import DomainError


def test_parse_sets_requires_schema_version() -> None:
    with pytest.raises(DomainError) as exc:
        parse_versioned(SessionSetsV1, {"sets": []})
    assert exc.value.error_code == "schema_version_required"

def test_parse_rejects_unsupported_schema_version() -> None:
    with pytest.raises(DomainError) as exc:
        parse_versioned(SessionSetsV1, {"schema_version": 2, "sets": []})
    assert exc.value.error_code == "schema_version_unsupported"

def test_parse_rules_v1_from_seed_shape() -> None:
    rules = parse_versioned(
        ProgressionRulesV1,
        {
            "schema_version": 1,
            "advance": {"sets": 3, "min_reps": 10, "require_both_sides": False},
            "regress": {"fail_sessions": 2},
            "goal": None,
        },
    )
    assert rules.advance is not None
    assert rules.advance.min_reps == 10

def test_parse_rules_v2_standards_and_advance_match() -> None:
    from app.schemas.rules import ProgressionRulesV2, parse_progression_rules

    payload = {
        "schema_version": 2,
        "standards": {
            "beginner": {"sets": 1, "min_reps": 10, "require_both_sides": False},
            "intermediate": {"sets": 2, "min_reps": 25, "require_both_sides": False},
            "progression": {"sets": 3, "min_reps": 50, "require_both_sides": False},
        },
        "advance": {"sets": 3, "min_reps": 50, "require_both_sides": False},
        "regress": {"fail_sessions": 2},
        "goal": None,
    }
    rules = parse_progression_rules(payload)
    assert isinstance(rules, ProgressionRulesV2)
    assert rules.advance.min_reps == 50
    assert rules.standards.progression.min_reps == 50

def test_parse_rules_v2_rejects_advance_mismatch() -> None:
    from app.schemas.rules import ProgressionRulesV2
    from app.services.errors import DomainError

    with pytest.raises(DomainError):
        parse_versioned(
            ProgressionRulesV2,
            {
                "schema_version": 2,
                "standards": {
                    "beginner": {"sets": 1, "min_reps": 10, "require_both_sides": False},
                    "intermediate": {"sets": 2, "min_reps": 25, "require_both_sides": False},
                    "progression": {"sets": 3, "min_reps": 50, "require_both_sides": False},
                },
                "advance": {"sets": 3, "min_reps": 10, "require_both_sides": False},
                "regress": {"fail_sessions": 2},
                "goal": None,
            },
        )
