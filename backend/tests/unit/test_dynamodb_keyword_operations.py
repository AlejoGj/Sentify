"""Unit tests for DynamoDBStorageProvider keyword operations.

Validates: Requirements 6.6
"""

import math
import uuid

import pytest

from app.infrastructure.storage.dynamodb_storage_provider import (
    DynamoDBStorageProvider,
    GSI1_NAME,
    GSI1_PK,
    GSI1_SK,
    GSI2_NAME,
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
                    "IndexName": GSI2_NAME,
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
# Helpers
# ---------------------------------------------------------------------------


def _store(provider: DynamoDBStorageProvider, batch_id: str, keywords: list) -> str:
    """Store a success feedback with the given keywords and return its id."""
    return provider.store_feedback(
        batch_id=batch_id,
        text="Sample feedback text",
        sentiment="positivo",
        score=0.5,
        keywords=keywords,
        status="success",
    )


# ---------------------------------------------------------------------------
# get_top_keywords (Requirement 6.6)
# ---------------------------------------------------------------------------


class TestGetTopKeywords:
    """get_top_keywords aggregates keyword frequencies and returns them sorted."""

    def test_returns_empty_list_for_batch_with_no_keywords(self, dynamodb_provider):
        """Returns an empty list when the batch has no keyword index items."""
        result = dynamodb_provider.get_top_keywords("empty-batch")
        assert result == []

    def test_returns_empty_list_for_feedbacks_with_no_valid_keywords(
        self, dynamodb_provider
    ):
        """Returns empty list when all keywords are too short (<=2 chars)."""
        _store(dynamodb_provider, "batch-001", ["ok", "a"])
        result = dynamodb_provider.get_top_keywords("batch-001")
        assert result == []

    def test_correct_frequency_single_feedback(self, dynamodb_provider):
        """Each keyword appears once when there is only one feedback."""
        _store(dynamodb_provider, "batch-002", ["calidad", "servicio"])
        result = dynamodb_provider.get_top_keywords("batch-002")
        words = {r["word"] for r in result}
        assert "calidad" in words
        assert "servicio" in words
        for r in result:
            assert r["frequency"] == 1

    def test_frequency_counts_distinct_feedbacks_per_keyword(
        self, dynamodb_provider
    ):
        """Frequency equals the number of distinct feedbacks containing that keyword."""
        _store(dynamodb_provider, "batch-003", ["calidad", "precio"])
        _store(dynamodb_provider, "batch-003", ["calidad"])
        _store(dynamodb_provider, "batch-003", ["precio"])

        result = dynamodb_provider.get_top_keywords("batch-003")
        freq_map = {r["word"]: r["frequency"] for r in result}

        assert freq_map["calidad"] == 2
        assert freq_map["precio"] == 2

    def test_sorted_by_frequency_descending(self, dynamodb_provider):
        """Keywords are returned sorted by frequency, highest first."""
        _store(dynamodb_provider, "batch-004", ["popular", "raro"])
        _store(dynamodb_provider, "batch-004", ["popular"])
        _store(dynamodb_provider, "batch-004", ["popular"])

        result = dynamodb_provider.get_top_keywords("batch-004")
        frequencies = [r["frequency"] for r in result]
        assert frequencies == sorted(frequencies, reverse=True)

    def test_top_keyword_has_highest_frequency(self, dynamodb_provider):
        """The first entry has the highest frequency."""
        _store(dynamodb_provider, "batch-004b", ["top", "low"])
        _store(dynamodb_provider, "batch-004b", ["top"])
        _store(dynamodb_provider, "batch-004b", ["top"])

        result = dynamodb_provider.get_top_keywords("batch-004b")
        assert result[0]["word"] == "top"
        assert result[0]["frequency"] == 3

    def test_respects_limit_parameter(self, dynamodb_provider):
        """Result is limited to the `limit` most frequent keywords."""
        keywords = [f"word{i:02d}" for i in range(10)]
        _store(dynamodb_provider, "batch-005", keywords)

        result = dynamodb_provider.get_top_keywords("batch-005", limit=5)
        assert len(result) <= 5

    def test_limit_default_is_20(self, dynamodb_provider):
        """Default limit is 20: returns at most 20 entries."""
        for i in range(25):
            _store(dynamodb_provider, "batch-006", [f"kwd{i:03d}"])

        result = dynamodb_provider.get_top_keywords("batch-006")
        assert len(result) <= 20

    def test_result_items_have_word_and_frequency_keys(self, dynamodb_provider):
        """Each result dict has exactly the keys 'word' and 'frequency'."""
        _store(dynamodb_provider, "batch-007", ["calidad"])
        result = dynamodb_provider.get_top_keywords("batch-007")
        for item in result:
            assert set(item.keys()) == {"word", "frequency"}
            assert isinstance(item["word"], str)
            assert isinstance(item["frequency"], int)

    def test_does_not_include_keywords_from_other_batches(
        self, dynamodb_provider
    ):
        """Keywords from other batches are not counted."""
        _store(dynamodb_provider, "batch-A", ["exclusive"])
        _store(dynamodb_provider, "batch-B", ["exclusive"])

        result_a = dynamodb_provider.get_top_keywords("batch-A")
        freq_map = {r["word"]: r["frequency"] for r in result_a}
        assert freq_map.get("exclusive") == 1

    def test_keywords_stored_lowercase(self, dynamodb_provider):
        """Keywords are stored and returned in lowercase."""
        _store(dynamodb_provider, "batch-008", ["Calidad", "SERVICIO"])
        result = dynamodb_provider.get_top_keywords("batch-008")
        words = {r["word"] for r in result}
        assert "calidad" in words
        assert "servicio" in words
        assert "Calidad" not in words
        assert "SERVICIO" not in words


# ---------------------------------------------------------------------------
# get_feedbacks_by_keyword (Requirement 6.6)
# ---------------------------------------------------------------------------


class TestGetFeedbacksByKeyword:
    """get_feedbacks_by_keyword returns paginated feedbacks for a keyword."""

    def test_returns_empty_for_unknown_keyword(self, dynamodb_provider):
        """Returns empty result when no feedbacks contain the keyword."""
        result = dynamodb_provider.get_feedbacks_by_keyword(
            "batch-100", "nonexistent", page=1
        )
        assert result["items"] == []
        assert result["total"] == 0
        assert result["total_pages"] == 0

    def test_returns_feedbacks_containing_keyword(self, dynamodb_provider):
        """Returns feedbacks that were stored with the target keyword."""
        fid = _store(dynamodb_provider, "batch-101", ["calidad", "precio"])
        _store(dynamodb_provider, "batch-101", ["entrega"])

        result = dynamodb_provider.get_feedbacks_by_keyword(
            "batch-101", "calidad", page=1
        )
        assert result["total"] == 1
        assert result["items"][0]["id"] == fid

    def test_returns_correct_structure(self, dynamodb_provider):
        """Result dict has keys: items, total, page, page_size, total_pages."""
        result = dynamodb_provider.get_feedbacks_by_keyword(
            "batch-102", "word", page=1
        )
        for key in ("items", "total", "page", "page_size", "total_pages"):
            assert key in result

    def test_page_and_page_size_reflected_in_result(self, dynamodb_provider):
        """page and page_size are echoed back in the result."""
        _store(dynamodb_provider, "batch-103", ["test"])
        result = dynamodb_provider.get_feedbacks_by_keyword(
            "batch-103", "test", page=2, page_size=5
        )
        assert result["page"] == 2
        assert result["page_size"] == 5

    def test_pagination_paginates_correctly(self, dynamodb_provider):
        """Different pages return non-overlapping sets of feedbacks."""
        for _ in range(5):
            _store(dynamodb_provider, "batch-104", ["comun"])

        p1 = dynamodb_provider.get_feedbacks_by_keyword(
            "batch-104", "comun", page=1, page_size=2
        )
        p2 = dynamodb_provider.get_feedbacks_by_keyword(
            "batch-104", "comun", page=2, page_size=2
        )

        assert len(p1["items"]) == 2
        assert len(p2["items"]) == 2
        ids_p1 = {i["id"] for i in p1["items"]}
        ids_p2 = {i["id"] for i in p2["items"]}
        assert ids_p1.isdisjoint(ids_p2)

    def test_pagination_total_pages_computed_correctly(self, dynamodb_provider):
        """total_pages = ceil(total / page_size)."""
        for _ in range(7):
            _store(dynamodb_provider, "batch-105", ["paginar"])

        result = dynamodb_provider.get_feedbacks_by_keyword(
            "batch-105", "paginar", page=1, page_size=3
        )
        assert result["total"] == 7
        assert result["total_pages"] == math.ceil(7 / 3)

    def test_item_fields_present(self, dynamodb_provider):
        """Each returned item has the expected feedback fields."""
        fid = _store(dynamodb_provider, "batch-106", ["campo"])
        result = dynamodb_provider.get_feedbacks_by_keyword(
            "batch-106", "campo", page=1
        )
        item = result["items"][0]
        assert item["id"] == fid
        assert item["original_text"] == "Sample feedback text"
        assert item["sentiment"] == "positivo"
        assert isinstance(item["score"], (int, float))
        assert "analyzed_at" in item

    def test_does_not_return_feedbacks_from_other_batches(self, dynamodb_provider):
        """Feedbacks from other batches are not included."""
        _store(dynamodb_provider, "batch-X2", ["shared"])
        _store(dynamodb_provider, "batch-Y2", ["shared"])

        result = dynamodb_provider.get_feedbacks_by_keyword(
            "batch-X2", "shared", page=1
        )
        assert result["total"] == 1
        assert result["items"][0]["batch_id"] == "batch-X2"

    def test_keyword_lookup_is_case_insensitive(self, dynamodb_provider):
        """Keyword matching works regardless of input case."""
        _store(dynamodb_provider, "batch-107", ["calidad"])

        result = dynamodb_provider.get_feedbacks_by_keyword(
            "batch-107", "CALIDAD", page=1
        )
        assert result["total"] == 1

    def test_multiple_feedbacks_returned_for_common_keyword(self, dynamodb_provider):
        """All feedbacks that share a keyword are returned."""
        fids = set()
        for _ in range(4):
            fids.add(_store(dynamodb_provider, "batch-108", ["comun"]))

        result = dynamodb_provider.get_feedbacks_by_keyword(
            "batch-108", "comun", page=1, page_size=10
        )
        assert result["total"] == 4
        returned_ids = {i["id"] for i in result["items"]}
        assert returned_ids == fids
