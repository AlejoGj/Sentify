"""
Property-based tests for SQLiteStorageProvider.

Feature: sentiment-analysis-platform
"""

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.models.base import Base
from app.core.models.user import User  # noqa: F401
from app.core.models.batch import Batch  # noqa: F401
from app.core.models.feedback import Feedback
from app.core.models.keyword import Keyword  # noqa: F401
from app.infrastructure.storage.sqlite_storage_provider import SQLiteStorageProvider


# ---------------------------------------------------------------------------
# Helper: create a fresh storage provider with in-memory SQLite
# ---------------------------------------------------------------------------

def _make_storage_provider():
    """Create a fresh in-memory SQLite storage provider with user and batch."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    storage = SQLiteStorageProvider(session_factory)

    # Create a user and batch required for storing feedback
    user_id = storage.create_user("prop_test@test.com", "hashed_pw", "Test Corp")
    batch_id = storage.create_batch(user_id, "test.csv")

    return storage, session_factory, batch_id


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

valid_sentiments = st.sampled_from(["positivo", "neutro", "negativo"])
valid_scores = st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False)
feedback_text = st.text(min_size=1, max_size=5000)


# ---------------------------------------------------------------------------
# Property 12: Feedback text persistence round-trip
# ---------------------------------------------------------------------------


class TestFeedbackTextPersistenceRoundTrip:
    """
    Property 12: Feedback text persistence round-trip

    For any text string of at most 5,000 characters, storing it as a feedback
    and then retrieving it SHALL return the exact original text without
    modification, along with its computed sentiment and score.

    **Validates: Requirements 5.1, 5.4**
    """

    @given(
        text=feedback_text,
        sentiment=valid_sentiments,
        score=valid_scores,
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_round_trip_preserves_text_sentiment_and_score(
        self, text: str, sentiment: str, score: float
    ):
        """
        Property 12: Feedback text persistence round-trip

        Storing a feedback and retrieving it preserves the original text,
        sentiment, and score exactly.

        **Validates: Requirements 5.1, 5.4**
        """
        storage, session_factory, batch_id = _make_storage_provider()

        # Store feedback with a known keyword (>2 chars, lowercase)
        feedback_id = storage.store_feedback(
            batch_id=batch_id,
            text=text,
            sentiment=sentiment,
            score=score,
            keywords=["testword"],
            status="success",
        )

        # Retrieve directly from the database to verify round-trip
        session = session_factory()
        try:
            feedback = session.query(Feedback).filter(Feedback.id == feedback_id).first()

            assert feedback is not None, "Feedback should be persisted"
            assert feedback.original_text == text, (
                f"Text round-trip failed: stored {len(text)} chars, "
                f"got back {len(feedback.original_text)} chars"
            )
            assert feedback.sentiment == sentiment, (
                f"Sentiment mismatch: expected {sentiment!r}, got {feedback.sentiment!r}"
            )
            assert feedback.score == score, (
                f"Score mismatch: expected {score}, got {feedback.score}"
            )
        finally:
            session.close()


# ---------------------------------------------------------------------------
# Property 13: Batch history ordering
# ---------------------------------------------------------------------------


class TestBatchHistoryOrdering:
    """
    Property 13: Batch history ordering

    For any set of completed batches belonging to a user, querying the history
    SHALL return them sorted by completion date in descending order (most recent first).

    **Validates: Requirements 5.6**
    """

    @given(
        num_batches=st.integers(min_value=2, max_value=10),
    )
    @settings(
        max_examples=100,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_batches_returned_ordered_by_completed_at_desc(
        self, num_batches: int
    ):
        """
        Property 13: Batch history ordering

        Creating multiple batches and completing them in a known sequence,
        then querying history returns them sorted by completed_at descending.

        **Validates: Requirements 5.6**
        """
        import time

        engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(bind=engine)
        session_factory = sessionmaker(bind=engine)
        storage = SQLiteStorageProvider(session_factory)

        # Create a user
        user_id = storage.create_user(
            "history_test@test.com", "hashed_pw", "Test Corp"
        )

        # Create and complete batches with slight time gaps to ensure distinct timestamps
        batch_ids = []
        for i in range(num_batches):
            batch_id = storage.create_batch(user_id, f"file_{i}.csv")
            batch_ids.append(batch_id)

        # Complete batches in order (first batch completed first, last batch completed last)
        for batch_id in batch_ids:
            storage.update_batch_status(batch_id, "completed")
            # Small sleep to ensure distinct completed_at timestamps
            time.sleep(0.01)

        # Query history
        result = storage.get_user_batches(user_id, page=1, page_size=num_batches + 10)

        items = result["items"]
        assert len(items) == num_batches, (
            f"Expected {num_batches} batches, got {len(items)}"
        )

        # Verify ordering: completed_at should be descending (most recent first)
        completed_dates = [item["completed_at"] for item in items]
        for i in range(len(completed_dates) - 1):
            assert completed_dates[i] >= completed_dates[i + 1], (
                f"Batch history not sorted by completed_at desc: "
                f"{completed_dates[i]} should be >= {completed_dates[i + 1]}"
            )
