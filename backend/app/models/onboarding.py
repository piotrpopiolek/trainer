from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _json_schema_check(column: str) -> str:
    return (
        f"({column} ? 'schema_version') AND ({column}->>'schema_version')::int >= 1"
    )


class UserOnboarding(Base):
    __tablename__ = "user_onboarding"
    __table_args__ = (
        CheckConstraint(
            _json_schema_check("questionnaire"),
            name="ck_user_onboarding_questionnaire_schema",
        ),
        CheckConstraint(
            _json_schema_check("placement_test"),
            name="ck_user_onboarding_placement_test_schema",
        ),
        CheckConstraint(
            _json_schema_check("recommended_steps"),
            name="ck_user_onboarding_recommended_steps_schema",
        ),
        CheckConstraint(
            _json_schema_check("chosen_steps"),
            name="ck_user_onboarding_chosen_steps_schema",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    questionnaire: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text('\'{"schema_version":1}\'::jsonb')
    )
    placement_test: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text('\'{"schema_version":1}\'::jsonb')
    )
    recommended_steps: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text('\'{"schema_version":1}\'::jsonb')
    )
    chosen_steps: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text('\'{"schema_version":1}\'::jsonb')
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
