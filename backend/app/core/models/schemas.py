"""Pydantic request/response schemas for the API layer."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field


# --- Auth Schemas ---


class LoginRequest(BaseModel):
    """Request schema for user login."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class RegisterRequest(BaseModel):
    """Request schema for user registration."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    company_name: str = Field(min_length=1, max_length=255)


class LoginResponse(BaseModel):
    """Response schema for successful login."""

    token: str
    expires_at: datetime
    company_name: str


# --- Batch Schemas ---


class BatchStatusResponse(BaseModel):
    """Response schema for batch processing status."""

    batch_id: str
    status: str
    total_rows: int
    processed_rows: int
    error_rows: int
    uploaded_at: datetime
    completed_at: Optional[datetime] = None


# --- Feedback Schemas ---


class FeedbackResponse(BaseModel):
    """Response schema for an individual analyzed feedback."""

    id: str
    original_text: str
    sentiment: str
    score: float
    keywords: list[str]
    analyzed_at: datetime


# --- Summary Schemas ---


class BatchSummaryResponse(BaseModel):
    """Response schema for batch sentiment summary."""

    batch_id: str
    total_feedbacks: int
    sentiment_distribution: dict[str, int]  # {"positivo": 45, "neutro": 30, "negativo": 25}
    sentiment_percentages: dict[str, float]  # {"positivo": 45.0, ...}
    urgent_count: int


# --- Keyword Schemas ---


class KeywordResponse(BaseModel):
    """Response schema for keyword frequency data."""

    word: str
    frequency: int


# --- Pagination ---


class PaginatedResponse(BaseModel):
    """Generic paginated response wrapper."""

    items: list[Any]
    total: int
    page: int
    page_size: int
    total_pages: int
