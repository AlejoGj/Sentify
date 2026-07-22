"""Keyword ORM model."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Keyword(Base):
    """Represents a keyword extracted from a feedback text."""

    __tablename__ = "keywords"
    __table_args__ = (
        Index("idx_keywords_word", "word"),
        Index("idx_keywords_feedback_id", "feedback_id"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    feedback_id: Mapped[str] = mapped_column(
        String, ForeignKey("feedbacks.id"), nullable=False
    )
    word: Mapped[str] = mapped_column(
        String, nullable=False
    )  # lowercase, > 2 chars

    # Relationships
    feedback: Mapped[Feedback] = relationship(
        "Feedback", back_populates="keywords"
    )

    def __repr__(self) -> str:
        return f"<Keyword(id={self.id!r}, word={self.word!r})>"
