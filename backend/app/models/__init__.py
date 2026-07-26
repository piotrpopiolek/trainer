"""ORM models for Trainer (db-core slice)."""

from app.models.auth import AuthSession, OAuthState
from app.models.body_measurement import BodyMeasurement
from app.models.legal import LegalDocument, LegalDocumentTranslation, UserLegalAcceptance
from app.models.onboarding import UserOnboarding
from app.models.user import User

__all__ = [
    "AuthSession",
    "BodyMeasurement",
    "LegalDocument",
    "LegalDocumentTranslation",
    "OAuthState",
    "User",
    "UserLegalAcceptance",
    "UserOnboarding",
]
