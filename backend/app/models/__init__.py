"""ORM models for Trainer."""

from app.models.auth import AuthSession, OAuthState
from app.models.body_measurement import BodyMeasurement
from app.models.catalog import (
    Exercise,
    ExerciseStep,
    ExerciseStepTranslation,
    ExerciseTranslation,
    Program,
    ProgramDay,
    ProgramDayExercise,
    ProgramDayTranslation,
    ProgramTranslation,
)
from app.models.legal import LegalDocument, LegalDocumentTranslation, UserLegalAcceptance
from app.models.onboarding import UserOnboarding
from app.models.progression import (
    ProgressionEvent,
    ProgressionSchema,
    UserExerciseProgress,
    UserProgramEnrollment,
)
from app.models.sync import ClientMutation, RateLimitBucket, SyncConflictLog, SyncDevice
from app.models.user import User
from app.models.workout import SessionExerciseLog, WorkoutSession

__all__ = [
    "AuthSession",
    "BodyMeasurement",
    "ClientMutation",
    "Exercise",
    "ExerciseStep",
    "ExerciseStepTranslation",
    "ExerciseTranslation",
    "LegalDocument",
    "LegalDocumentTranslation",
    "OAuthState",
    "Program",
    "ProgramDay",
    "ProgramDayExercise",
    "ProgramDayTranslation",
    "ProgramTranslation",
    "ProgressionEvent",
    "ProgressionSchema",
    "RateLimitBucket",
    "SessionExerciseLog",
    "SyncConflictLog",
    "SyncDevice",
    "User",
    "UserExerciseProgress",
    "UserLegalAcceptance",
    "UserOnboarding",
    "UserProgramEnrollment",
    "WorkoutSession",
]
