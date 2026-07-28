"""Property-based tests for DynamoDBStorageProvider feedback operations.

Feature: cloud-migration
Properties 9, 11, 13
"""

import math

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Strategy helpers
# Scores are constrained to avoid subnormal floats that DynamoDB Decimal rejects.
# ---------------------------------------------------------------------------


# Scores use a Decimal-safe strategy:
# DynamoDB Decimal requires numbers within a strict precision range.
# We build scores as 2-decimal-point fractions via integer division to guarantee
# no subnormal or extremely small numbers that DynamoDB cannot serialize.
_score_integers = st.integers(min_value=-100, max_value=100)
valid_scores = st.builds(lambda x: round(x / 100.0, 2), _score_integers)
valid_threshold = st.builds(lambda x: round(x / 100.0, 2), _score_integers)
valid_sentiments = st.sampled_from(["positivo", "neutro", "negativo"])
feedback_text = st.text(min_size=0, max_size=8000)


# ---------------------------------------------------------------------------
# Fixture factory (creates a fresh moto-backed provider per test invocation)
# ---------------------------------------------------------------------------


def _make_provider():
    """Create a fresh DynamoDBStorageProvider backed by a moto-mocked table."""
    try:
        from moto import mock_aws
    except ImportError:
        pytest.skip("moto not installed - skipping DynamoDB property tests")

    from app.infrastructure.storage.dynamodb_storage_provider import (
        DynamoDBStorageProvider,
        GSI1_NAME,
        GSI1_PK,
        GSI1_SK,
        GSI2_PK,
        GSI2_SK,
    )
    import boto3

    mock = mock_aws()
    mock.start()

    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        TableName="sentify-prop-test",
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": GSI1_PK, "AttributeType": "S"},
            {"AttributeName": GSI1_SK, "AttributeType": "S"},
            {"AttributeName": GSI2_PK, "AttributeType": "S"},
            {"AttributeName": GSI2_SK, "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": GSI1_NAME,
                "KeySchema": [
                    {"AttributeName": GSI1_PK, "KeyType": "HASH"},
                    {"AttributeName": GSI1_SK, "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "GSI2",
                "KeySchema": [
                    {"AttributeName": GSI2_PK, "KeyType": "HASH"},
                    {"AttributeName": GSI2_SK, "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    provider = DynamoDBStorageProvider(
        table_name="sentify-prop-test", region="us-east-1"
    )
    return provider, mock


# ---------------------------------------------------------------------------
# Property 9: Feedback text truncation invariant
# ---------------------------------------------------------------------------


class TestProperty9FeedbackTextTruncation:
    """
    Property 9: Feedback text truncation invariant

    For any text string of any length, when store_feedback or store_feedback_error
    is called, the stored original_text SHALL have length at most 5000 characters
    and SHALL equal the first 5000 characters of the input text.

    **Validates: Requirements 6.4, 7.4**
    """

    @given(text=feedback_text, sentiment=valid_sentiments, score=valid_scores)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    def test_store_feedback_truncates_to_5000(
        self, text: str, sentiment: str, score: float
    ):
        """
        Feature: cloud-migration, Property 9: Feedback text truncation invariant

        store_feedback stores at most 5000 chars of original_text, equal to text[:5000].

        **Validates: Requirements 6.4**
        """
        from app.infrastructure.storage.dynamodb_storage_provider import PK_BATCH, SK_FEEDBACK

        provider, mock = _make_provider()
        try:
            fid = provider.store_feedback(
                "batch-prop9a", text, sentiment, score, [], "success"
            )
            pk = PK_BATCH.format("batch-prop9a")
            sk = SK_FEEDBACK.format(fid)
            item = provider._table.get_item(Key={"PK": pk, "SK": sk})["Item"]
            stored_text = item["original_text"]

            assert len(stored_text) <= 5000, (
                f"Stored text length {len(stored_text)} exceeds 5000"
            )
            assert stored_text == text[:5000], (
                "Stored text does not equal first 5000 chars of input"
            )
        finally:
            mock.stop()

    @given(text=feedback_text)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    def test_store_feedback_error_truncates_to_5000(self, text: str):
        """
        Feature: cloud-migration, Property 9: Feedback text truncation invariant

        store_feedback_error stores at most 5000 chars of original_text, equal to text[:5000].

        **Validates: Requirements 7.4**
        """
        from app.infrastructure.storage.dynamodb_storage_provider import PK_BATCH, SK_FEEDBACK

        provider, mock = _make_provider()
        try:
            fid = provider.store_feedback_error(
                "batch-prop9b", text, "test_reason"
            )
            pk = PK_BATCH.format("batch-prop9b")
            sk = SK_FEEDBACK.format(fid)
            item = provider._table.get_item(Key={"PK": pk, "SK": sk})["Item"]
            stored_text = item["original_text"]

            assert len(stored_text) <= 5000, (
                f"Stored text length {len(stored_text)} exceeds 5000"
            )
            assert stored_text == text[:5000], (
                "Stored text does not equal first 5000 chars of input"
            )
        finally:
            mock.stop()


# ---------------------------------------------------------------------------
# Property 11: Pagination math invariant
# ---------------------------------------------------------------------------


class TestProperty11PaginationMath:
    """
    Property 11: Pagination math invariant

    **Validates: Requirements 6.5, 6.7**
    """

    @given(
        num_items=st.integers(min_value=0, max_value=30),
        page=st.integers(min_value=1, max_value=10),
        page_size=st.integers(min_value=1, max_value=20),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    def test_get_batch_feedbacks_pagination_math(
        self, num_items: int, page: int, page_size: int
    ):
        """
        Feature: cloud-migration, Property 11: Pagination math invariant

        get_batch_feedbacks: total_pages == ceil(total / page_size),
        items returned <= page_size, total == eligible item count.

        **Validates: Requirements 6.5**
        """
        provider, mock = _make_provider()
        try:
            batch_id = "batch-pag11a"
            for i in range(num_items):
                provider.store_feedback(
                    batch_id, f"text {i}", "neutro", 0.0, [], "success"
                )

            result = provider.get_batch_feedbacks(batch_id, page=page, page_size=page_size)

            total = result["total"]
            total_pages = result["total_pages"]
            items = result["items"]

            assert total == num_items, f"Expected total={num_items}, got {total}"
            expected_pages = math.ceil(total / page_size) if page_size > 0 else 0
            assert total_pages == expected_pages, (
                f"Expected total_pages={expected_pages}, got {total_pages}"
            )
            assert len(items) <= page_size, (
                f"Items count {len(items)} exceeds page_size {page_size}"
            )
        finally:
            mock.stop()

    @given(
        num_items=st.integers(min_value=0, max_value=30),
        page=st.integers(min_value=1, max_value=10),
        page_size=st.integers(min_value=1, max_value=20),
        threshold=valid_threshold,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    def test_get_urgent_feedbacks_pagination_math(
        self, num_items: int, page: int, page_size: int, threshold: float
    ):
        """
        Feature: cloud-migration, Property 11: Pagination math invariant

        get_urgent_feedbacks: total_pages == ceil(total / page_size),
        items returned <= page_size, total == count of items with score < threshold.

        **Validates: Requirements 6.7**
        """
        provider, mock = _make_provider()
        try:
            batch_id = "batch-pag11b"
            scores = [
                round(-1.0 + i * (2.0 / max(num_items, 1)), 4)
                for i in range(num_items)
            ]
            for s in scores:
                provider.store_feedback(batch_id, "text", "negativo", s, [], "success")

            result = provider.get_urgent_feedbacks(
                batch_id, threshold=threshold, page=page, page_size=page_size
            )

            total = result["total"]
            total_pages = result["total_pages"]
            items = result["items"]

            expected_total = sum(1 for s in scores if s < threshold)
            assert total == expected_total, (
                f"Expected total={expected_total}, got {total} (threshold={threshold})"
            )
            expected_pages = math.ceil(total / page_size) if page_size > 0 else 0
            assert total_pages == expected_pages, (
                f"Expected total_pages={expected_pages}, got {total_pages}"
            )
            assert len(items) <= page_size, (
                f"Items count {len(items)} exceeds page_size {page_size}"
            )
        finally:
            mock.stop()


# ---------------------------------------------------------------------------
# Property 13: Urgent feedback filtering and ordering
# ---------------------------------------------------------------------------


class TestProperty13UrgentFeedbackFilteringAndOrdering:
    """
    Property 13: Urgent feedback filtering and ordering

    For any set of feedbacks with various scores and statuses, and any threshold
    float, get_urgent_feedbacks SHALL return only feedbacks where status is
    "success" AND score is strictly less than the threshold, ordered by score
    ascending.

    **Validates: Requirements 6.7**
    """

    @given(
        feedbacks=st.lists(
            st.fixed_dictionaries({
                "score": valid_scores,
                "status": st.sampled_from(["success", "error"]),
            }),
            min_size=0,
            max_size=20,
        ),
        threshold=valid_threshold,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    def test_urgent_feedbacks_correct_filtering_and_order(
        self, feedbacks: list, threshold: float
    ):
        """
        Feature: cloud-migration, Property 13: Urgent feedback filtering and ordering

        get_urgent_feedbacks returns only status='success' AND score < threshold,
        ordered by score ascending.

        **Validates: Requirements 6.7**
        """
        provider, mock = _make_provider()
        try:
            batch_id = "batch-prop13"
            for fb in feedbacks:
                if fb["status"] == "success":
                    provider.store_feedback(
                        batch_id, "text", "neutro", fb["score"], [], "success"
                    )
                else:
                    provider.store_feedback_error(batch_id, "text", "some_error")

            result = provider.get_urgent_feedbacks(
                batch_id, threshold=threshold, page=1, page_size=100
            )
            items = result["items"]

            # All returned items must be status='success' and score < threshold
            for item in items:
                assert item["status"] == "success", (
                    f"Item with status={item['status']} should not be returned"
                )
                assert item["score"] < threshold, (
                    f"Item with score={item['score']} >= threshold={threshold}"
                )

            # Scores must be in ascending order
            scores = [item["score"] for item in items]
            assert scores == sorted(scores), (
                f"Scores are not in ascending order: {scores}"
            )

            # Total should equal count of eligible feedbacks
            expected_total = sum(
                1 for fb in feedbacks
                if fb["status"] == "success" and fb["score"] < threshold
            )
            assert result["total"] == expected_total, (
                f"Expected total={expected_total}, got {result['total']}"
            )
        finally:
            mock.stop()
