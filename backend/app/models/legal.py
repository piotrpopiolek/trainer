from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    Text,
    UniqueConstraint,
    desc,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LegalDocument(Base):
    __tablename__ = "legal_documents"
    __table_args__ = (UniqueConstraint("slug", "version", name="uq_legal_documents_slug_version"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LegalDocumentTranslation(Base):
    __tablename__ = "legal_document_translations"
    __table_args__ = (
        CheckConstraint(
            "char_length(locale) BETWEEN 2 AND 35",
            name="ck_legal_document_translations_locale_len",
        ),
        UniqueConstraint(
            "document_id",
            "locale",
            "content_hash",
            name="uq_legal_document_translations_doc_locale_hash",
        ),
    )

    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("legal_documents.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    locale: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UserLegalAcceptance(Base):
    __tablename__ = "user_legal_acceptances"
    __table_args__ = (
        UniqueConstraint("user_id", "document_id", name="uq_user_legal_acceptances_user_doc"),
        ForeignKeyConstraint(
            ["document_id", "accepted_locale", "accepted_content_hash"],
            [
                "legal_document_translations.document_id",
                "legal_document_translations.locale",
                "legal_document_translations.content_hash",
            ],
            name="fk_user_legal_acceptances_translation",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_user_legal_acceptances_user_accepted_at",
            "user_id",
            desc("accepted_at"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("legal_documents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    accepted_locale: Mapped[str] = mapped_column(Text, nullable=False)
    accepted_content_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
