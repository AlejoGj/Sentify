"""Feedback ORM model."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Feedback(Base):
    """Represents an individual customer feedback/review within a batch."""

    __tablename__ = "feedbacks"
    __table_args__ = (
        Index("idx_feedbacks_batch_id", "batch_id"),
        Index("idx_feedbacks_score", "score"),
        Index("idx_feedbacks_sentiment", "sentiment"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    batch_id: Mapped[str] = mapped_column(
        String, ForeignKey("batches.id"), nullable=False
    )
    original_text: Mapped[str] = mapped_column(
        String(5000), nullable=False
    )  # max 5000 chars
    sentiment: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # positivo | neutro | negativo
    score: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # -1.0 to 1.0
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending"
    )  # pending | success | error
    error_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    batch: Mapped[Batch] = relationship("Batch", back_populates="feedbacks")
    keywords: Mapped[list[Keyword]] = relationship(
        "Keyword", back_populates="feedback", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Feedback(id={self.id!r}, sentiment={self.sentiment!r}, score={self.score!r})>"
