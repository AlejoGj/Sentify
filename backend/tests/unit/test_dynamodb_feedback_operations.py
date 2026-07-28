"""Unit tests for DynamoDBStorageProvider feedback operations.

Validates: Requirements 6.4, 6.5, 6.7, 7.4
"""

import math
import uuid
from datetime import datetime, timezone

import pytest

from app.infrastructure.storage.dynamodb_storage_provider import (
    DynamoDBStorageProvider,
    PK_BATCH,
    SK_FEEDBACK,
    SK_KW,
    GSI1_NAME,
    GSI1_PK,
    GSI1_SK,
    GSI2_PK,
    GSI2_SK,
)


# ---------------------------------------------------------------------------
# Fixture: DynamoDB table backed by moto (with GSI1 and GSI2)
# ---------------------------------------------------------------------------


@pytest.fixture
def dynamodb_provider():
    """Create a DynamoDBStorageProvider backed by a moto-mocked DynamoDB table."""
    try:
        from moto import mock_aws
    except ImportError:
        pytest.skip("moto not installed - skipping DynamoDB unit tests")

    with mock_aws():
        import boto3

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        dynamodb.create_table(
            TableName="sentify-test",
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
            table_name="sentify-test", region="us-east-1"
        )
        yield provider


# ---------------------------------------------------------------------------
# store_feedback (Requirement 6.4)
# ---------------------------------------------------------------------------


class TestStoreFeedback:
    """store_feedback stores a feedback item and returns a valid feedback_id."""

    def test_returns_uuid_v4_string(self, dynamodb_provider):
        """store_feedback returns a valid UUID v4 string."""
        fid = dynamodb_provider.store_feedback(
            "batch-001", "Great product!", "positivo", 0.85,
            ["great", "product"], "success",
        )
        assert isinstance(fid, str)
        parsed = uuid.UUID(fid, version=4)
        assert str(parsed) == fid

    def test_feedback_item_stored_with_correct_pk_sk(self, dynamodb_provider):
        """Feedback item stored at PK=BATCH#{batch_id}, SK=FEEDBACK#{feedback_id}."""
        fid = dynamodb_provider.store_feedback(
            "batch-001", "Text", "neutro", 0.0, [], "success",
        )
        pk = PK_BATCH.format("batch-001")
        sk = SK_FEEDBACK.format(fid)
        response = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": sk})
        assert response.get("Item") is not None

    def test_text_truncated_to_5000_chars(self, dynamodb_provider):
        """original_text is truncated to 5000 chars when input exceeds that."""
        long_text = "x" * 6000
        fid = dynamodb_provider.store_feedback(
            "batch-001", long_text, "neutro", 0.0, [], "success",
        )
        pk = PK_BATCH.format("batch-001")
        sk = SK_FEEDBACK.format(fid)
        item = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": sk})["Item"]
        assert len(item["original_text"]) == 5000

    def test_text_exact_5000_chars_not_truncated(self, dynamodb_provider):
        """Text of exactly 5000 chars is stored unchanged."""
        text = "a" * 5000
        fid = dynamodb_provider.store_feedback(
            "batch-001", text, "neutro", 0.0, [], "success",
        )
        pk = PK_BATCH.format("batch-001")
        sk = SK_FEEDBACK.format(fid)
        item = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": sk})["Item"]
        assert len(item["original_text"]) == 5000

    def test_feedback_fields_persisted(self, dynamodb_provider):
        """All feedback fields are persisted correctly."""
        fid = dynamodb_provider.store_feedback(
            "batch-001", "Terrible service", "negativo", -0.9,
            ["terrible", "service"], "success",
        )
        pk = PK_BATCH.format("batch-001")
        sk = SK_FEEDBACK.format(fid)
        item = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": sk})["Item"]

        assert item["id"] == fid
        assert item["batch_id"] == "batch-001"
        assert item["sentiment"] == "negativo"
        assert float(item["score"]) == pytest.approx(-0.9)
        assert item["status"] == "success"
        assert "analyzed_at" in item

    def test_gsi1_attributes_set(self, dynamodb_provider):
        """GSI1PK and GSI1SK are set on the feedback item."""
        fid = dynamodb_provider.store_feedback(
            "batch-001", "Text", "neutro", 0.0, [], "success",
        )
        pk = PK_BATCH.format("batch-001")
        sk = SK_FEEDBACK.format(fid)
        item = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": sk})["Item"]

        assert item[GSI1_PK] == PK_BATCH.format("batch-001")
        assert item[GSI1_SK].startswith("FEEDBACK#")

    def test_keyword_index_items_written(self, dynamodb_provider):
        """Keyword index items are written for each valid keyword."""
        fid = dynamodb_provider.store_feedback(
            "batch-001", "Text", "neutro", 0.0, ["quality", "service"], "success",
        )
        pk = PK_BATCH.format("batch-001")

        for word in ["quality", "service"]:
            kw_sk = SK_KW.format(word, fid)
            response = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": kw_sk})
            item = response.get("Item")
            assert item is not None, f"Keyword index item for '{word}' not found"
            assert item["word"] == word
            assert item["feedback_id"] == fid

    def test_keyword_index_skips_short_words(self, dynamodb_provider):
        """Keywords with 2 or fewer chars do not get index items."""
        fid = dynamodb_provider.store_feedback(
            "batch-001", "Text", "neutro", 0.0, ["ok", "a", "good"], "success",
        )
        pk = PK_BATCH.format("batch-001")

        for short_word in ["ok", "a"]:
            kw_sk = SK_KW.format(short_word, fid)
            response = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": kw_sk})
            assert response.get("Item") is None

        kw_sk = SK_KW.format("good", fid)
        assert dynamodb_provider._table.get_item(Key={"PK": pk, "SK": kw_sk}).get("Item") is not None

    def test_gsi2_attributes_set_on_keyword_items(self, dynamodb_provider):
        """GSI2PK and GSI2SK are set on each keyword index item."""
        fid = dynamodb_provider.store_feedback(
            "batch-001", "Text", "neutro", 0.0, ["product"], "success",
        )
        pk = PK_BATCH.format("batch-001")
        kw_sk = SK_KW.format("product", fid)
        item = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": kw_sk})["Item"]

        assert item[GSI2_PK] == "BATCH#batch-001#KW#product"
        assert item[GSI2_SK] == SK_FEEDBACK.format(fid)


# ---------------------------------------------------------------------------
# store_feedback_error (Requirement 7.4)
# ---------------------------------------------------------------------------


class TestStoreFeedbackError:
    """store_feedback_error stores an error feedback and returns a valid feedback_id."""

    def test_returns_uuid_v4_string(self, dynamodb_provider):
        """store_feedback_error returns a valid UUID v4 string."""
        fid = dynamodb_provider.store_feedback_error(
            "batch-002", "Could not parse", "invalid_format"
        )
        assert isinstance(fid, str)
        parsed = uuid.UUID(fid, version=4)
        assert str(parsed) == fid

    def test_status_is_error(self, dynamodb_provider):
        """Stored item has status='error'."""
        fid = dynamodb_provider.store_feedback_error(
            "batch-002", "Bad text", "parse_error"
        )
        pk = PK_BATCH.format("batch-002")
        sk = SK_FEEDBACK.format(fid)
        item = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": sk})["Item"]
        assert item["status"] == "error"

    def test_error_reason_persisted(self, dynamodb_provider):
        """error_reason is stored on the item."""
        fid = dynamodb_provider.store_feedback_error(
            "batch-002", "Bad text", "encoding_error"
        )
        pk = PK_BATCH.format("batch-002")
        sk = SK_FEEDBACK.format(fid)
        item = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": sk})["Item"]
        assert item["error_reason"] == "encoding_error"

    def test_text_truncated_to_5000_chars(self, dynamodb_provider):
        """original_text is truncated to 5000 chars for error feedbacks."""
        long_text = "y" * 7000
        fid = dynamodb_provider.store_feedback_error(
            "batch-002", long_text, "too_long"
        )
        pk = PK_BATCH.format("batch-002")
        sk = SK_FEEDBACK.format(fid)
        item = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": sk})["Item"]
        assert len(item["original_text"]) == 5000

    def test_sentiment_and_score_are_none(self, dynamodb_provider):
        """sentiment and score are None on error feedback items."""
        fid = dynamodb_provider.store_feedback_error(
            "batch-002", "text", "reason"
        )
        pk = PK_BATCH.format("batch-002")
        sk = SK_FEEDBACK.format(fid)
        item = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": sk})["Item"]
        assert item["sentiment"] is None
        assert item["score"] is None

    def test_gsi1_attributes_set(self, dynamodb_provider):
        """GSI1PK and GSI1SK are set on error feedback items."""
        fid = dynamodb_provider.store_feedback_error(
            "batch-002", "text", "reason"
        )
        pk = PK_BATCH.format("batch-002")
        sk = SK_FEEDBACK.format(fid)
        item = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": sk})["Item"]
        assert item[GSI1_PK] == PK_BATCH.format("batch-002")
        assert item[GSI1_SK].startswith("FEEDBACK#")


# ---------------------------------------------------------------------------
# get_batch_feedbacks (Requirement 6.5)
# ---------------------------------------------------------------------------


class TestGetBatchFeedbacks:
    """get_batch_feedbacks returns paginated success feedbacks ordered by analyzed_at desc."""

    def test_returns_empty_for_batch_with_no_feedbacks(self, dynamodb_provider):
        """Returns empty result for a batch that has no feedbacks."""
        result = dynamodb_provider.get_batch_feedbacks("empty-batch", page=1)
        assert result["items"] == []
        assert result["total"] == 0
        assert result["total_pages"] == 0

    def test_returns_correct_structure(self, dynamodb_provider):
        """Result has keys: items, total, page, page_size, total_pages."""
        dynamodb_provider.store_feedback(
            "batch-003", "text", "neutro", 0.0, [], "success"
        )
        result = dynamodb_provider.get_batch_feedbacks("batch-003", page=1)
        for key in ("items", "total", "page", "page_size", "total_pages"):
            assert key in result

    def test_filters_only_success_status(self, dynamodb_provider):
        """Only feedbacks with status='success' are returned."""
        dynamodb_provider.store_feedback(
            "batch-003", "good text", "positivo", 0.9, [], "success"
        )
        dynamodb_provider.store_feedback_error(
            "batch-003", "bad text", "parse_error"
        )
        result = dynamodb_provider.get_batch_feedbacks("batch-003", page=1)
        assert result["total"] == 1
        assert all(i["status"] == "success" for i in result["items"])

    def test_item_fields_present(self, dynamodb_provider):
        """Each item dict contains required fields."""
        fid = dynamodb_provider.store_feedback(
            "batch-003", "Amazing!", "positivo", 0.8, ["amazing"], "success"
        )
        result = dynamodb_provider.get_batch_feedbacks("batch-003", page=1)
        item = result["items"][0]
        assert item["id"] == fid
        assert item["original_text"] == "Amazing!"
        assert item["sentiment"] == "positivo"
        assert item["score"] == pytest.approx(0.8)
        assert item["status"] == "success"
        assert "analyzed_at" in item

    def test_score_returned_as_float(self, dynamodb_provider):
        """Score is returned as a native Python float, not Decimal."""
        dynamodb_provider.store_feedback(
            "batch-003", "text", "positivo", 0.75, [], "success"
        )
        result = dynamodb_provider.get_batch_feedbacks("batch-003", page=1)
        score = result["items"][0]["score"]
        assert isinstance(score, (int, float))

    def test_pagination_total_pages(self, dynamodb_provider):
        """total_pages = ceil(total / page_size)."""
        for i in range(5):
            dynamodb_provider.store_feedback(
                "batch-004", f"text {i}", "neutro", 0.0, [], "success"
            )
        result = dynamodb_provider.get_batch_feedbacks("batch-004", page=1, page_size=2)
        assert result["total"] == 5
        assert result["total_pages"] == math.ceil(5 / 2)

    def test_pagination_second_page(self, dynamodb_provider):
        """Page 2 returns a different slice of results."""
        for i in range(4):
            dynamodb_provider.store_feedback(
                "batch-004b", f"text {i}", "neutro", 0.0, [], "success"
            )
        p1 = dynamodb_provider.get_batch_feedbacks("batch-004b", page=1, page_size=2)
        p2 = dynamodb_provider.get_batch_feedbacks("batch-004b", page=2, page_size=2)

        assert len(p1["items"]) == 2
        assert len(p2["items"]) == 2
        ids_p1 = {i["id"] for i in p1["items"]}
        ids_p2 = {i["id"] for i in p2["items"]}
        assert ids_p1.isdisjoint(ids_p2)

    def test_does_not_return_other_batch_feedbacks(self, dynamodb_provider):
        """Feedbacks from other batches are not included."""
        dynamodb_provider.store_feedback(
            "batch-A", "in A", "positivo", 0.5, [], "success"
        )
        dynamodb_provider.store_feedback(
            "batch-B", "in B", "positivo", 0.5, [], "success"
        )
        result = dynamodb_provider.get_batch_feedbacks("batch-A", page=1)
        assert result["total"] == 1
        assert result["items"][0]["batch_id"] == "batch-A"

    def test_page_size_default_is_20(self, dynamodb_provider):
        """Default page_size is 20."""
        result = dynamodb_provider.get_batch_feedbacks("batch-X", page=1)
        assert result["page_size"] == 20


# ---------------------------------------------------------------------------
# get_urgent_feedbacks (Requirement 6.7)
# ---------------------------------------------------------------------------


class TestGetUrgentFeedbacks:
    """get_urgent_feedbacks returns feedbacks below threshold, ordered by score asc."""

    def test_returns_empty_when_no_feedbacks(self, dynamodb_provider):
        """Returns empty result when batch has no feedbacks."""
        result = dynamodb_provider.get_urgent_feedbacks("empty-batch", -0.5, page=1)
        assert result["items"] == []
        assert result["total"] == 0

    def test_filters_below_threshold(self, dynamodb_provider):
        """Only returns feedbacks with score strictly less than threshold."""
        dynamodb_provider.store_feedback(
            "batch-005", "Very bad", "negativo", -0.9, [], "success"
        )
        dynamodb_provider.store_feedback(
            "batch-005", "Okay", "neutro", 0.0, [], "success"
        )
        result = dynamodb_provider.get_urgent_feedbacks("batch-005", -0.5, page=1)
        assert result["total"] == 1
        assert result["items"][0]["score"] == pytest.approx(-0.9)

    def test_excludes_feedbacks_at_or_above_threshold(self, dynamodb_provider):
        """Feedbacks with score >= threshold are excluded."""
        dynamodb_provider.store_feedback(
            "batch-005b", "Exactly at threshold", "negativo", -0.5, [], "success"
        )
        result = dynamodb_provider.get_urgent_feedbacks("batch-005b", -0.5, page=1)
        assert result["total"] == 0

    def test_excludes_error_status_feedbacks(self, dynamodb_provider):
        """Error-status feedbacks (even if score < threshold) are excluded."""
        dynamodb_provider.store_feedback_error(
            "batch-005c", "bad text", "parse_error"
        )
        result = dynamodb_provider.get_urgent_feedbacks("batch-005c", 1.0, page=1)
        assert result["total"] == 0

    def test_ordered_by_score_ascending(self, dynamodb_provider):
        """Urgent feedbacks are ordered by score ascending (lowest first)."""
        scores = [-0.3, -0.9, -0.6, -0.1]
        for s in scores:
            dynamodb_provider.store_feedback(
                "batch-006", f"score {s}", "negativo", s, [], "success"
            )
        result = dynamodb_provider.get_urgent_feedbacks("batch-006", 0.0, page=1)
        returned_scores = [i["score"] for i in result["items"]]
        assert returned_scores == sorted(returned_scores)

    def test_returns_correct_structure(self, dynamodb_provider):
        """Result has keys: items, total, page, page_size, total_pages."""
        result = dynamodb_provider.get_urgent_feedbacks("batch-007", -0.5, page=1)
        for key in ("items", "total", "page", "page_size", "total_pages"):
            assert key in result

    def test_pagination_total_pages(self, dynamodb_provider):
        """total_pages = ceil(total / page_size)."""
        for i in range(6):
            dynamodb_provider.store_feedback(
                "batch-008", f"urgent {i}", "negativo", -0.8 - i * 0.01, [], "success"
            )
        result = dynamodb_provider.get_urgent_feedbacks("batch-008", 0.0, page=1, page_size=4)
        assert result["total"] == 6
        assert result["total_pages"] == math.ceil(6 / 4)

    def test_page_size_default_is_10(self, dynamodb_provider):
        """Default page_size is 10."""
        result = dynamodb_provider.get_urgent_feedbacks("batch-X", -0.5, page=1)
        assert result["page_size"] == 10

    def test_does_not_return_other_batch_feedbacks(self, dynamodb_provider):
        """Urgent feedbacks from other batches are not included."""
        dynamodb_provider.store_feedback(
            "batch-C", "urgent C", "negativo", -0.9, [], "success"
        )
        dynamodb_provider.store_feedback(
            "batch-D", "urgent D", "negativo", -0.9, [], "success"
        )
        result = dynamodb_provider.get_urgent_feedbacks("batch-C", 0.0, page=1)
        assert result["total"] == 1
        assert result["items"][0]["batch_id"] == "batch-C"
