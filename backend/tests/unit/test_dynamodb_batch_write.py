"""Unit tests for DynamoDBStorageProvider batch write operations.

Tests cover:
- _batch_write with no unprocessed items
- _batch_write retries unprocessed items
- _batch_write raises RuntimeError after 3 failed retries
- store_feedbacks_batch stores all feedbacks and returns correct feedback_ids
- Chunks of exactly 25 are respected
"""

import uuid
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# _batch_write — unit tests using unittest.mock (no moto)
# ---------------------------------------------------------------------------


def _make_mock_provider(table_name: str = "tbl"):
    """Create a DynamoDBStorageProvider instance with a mocked boto3 table."""
    from app.infrastructure.storage.dynamodb_storage_provider import (
        DynamoDBStorageProvider,
    )

    provider = object.__new__(DynamoDBStorageProvider)
    provider._table_name = table_name

    mock_client = MagicMock()
    mock_table = MagicMock()
    mock_table.meta.client = mock_client
    provider._table = mock_table

    return provider, mock_client


class TestBatchWriteNoUnprocessed:
    """_batch_write succeeds when batch_write_item returns no unprocessed items."""

    def test_single_chunk_no_retries(self):
        """A small batch with no unprocessed items completes without sleeping."""
        provider, mock_client = _make_mock_provider()
        mock_client.batch_write_item.return_value = {"UnprocessedItems": {}}

        items = [{"PutRequest": {"Item": {"PK": f"pk{i}", "SK": f"sk{i}"}}} for i in range(5)]

        with patch("time.sleep") as mock_sleep:
            provider._batch_write(items)

        mock_client.batch_write_item.assert_called_once_with(
            RequestItems={"tbl": items}
        )
        mock_sleep.assert_not_called()

    def test_empty_items_list_makes_no_calls(self):
        """_batch_write with an empty list makes zero API calls."""
        provider, mock_client = _make_mock_provider()

        provider._batch_write([])

        mock_client.batch_write_item.assert_not_called()


class TestBatchWriteRetries:
    """_batch_write retries unprocessed items with exponential backoff."""

    def test_retries_on_first_call_then_succeeds(self):
        """First call returns 2 unprocessed items; second call succeeds."""
        provider, mock_client = _make_mock_provider()

        unprocessed_items = [
            {"PutRequest": {"Item": {"PK": "pk0", "SK": "sk0"}}},
            {"PutRequest": {"Item": {"PK": "pk1", "SK": "sk1"}}},
        ]

        mock_client.batch_write_item.side_effect = [
            # First call: two items unprocessed
            {"UnprocessedItems": {"tbl": unprocessed_items}},
            # Retry: all succeed
            {"UnprocessedItems": {}},
        ]

        all_items = [
            {"PutRequest": {"Item": {"PK": "pk0", "SK": "sk0"}}},
            {"PutRequest": {"Item": {"PK": "pk1", "SK": "sk1"}}},
            {"PutRequest": {"Item": {"PK": "pk2", "SK": "sk2"}}},
        ]

        with patch("time.sleep") as mock_sleep:
            provider._batch_write(all_items)

        assert mock_client.batch_write_item.call_count == 2
        # Second call retries only the unprocessed items
        second_call_args = mock_client.batch_write_item.call_args_list[1]
        assert second_call_args == call(RequestItems={"tbl": unprocessed_items})
        # Slept once with 0.1 seconds (attempt 0 backoff)
        mock_sleep.assert_called_once_with(0.1)

    def test_exponential_backoff_timing(self):
        """Sleep durations follow 2^attempt * 0.1 pattern (0.1, 0.2, 0.4)."""
        provider, mock_client = _make_mock_provider()

        one_item = [{"PutRequest": {"Item": {"PK": "pk0", "SK": "sk0"}}}]

        # Always unprocessed: original + 3 retries (all fail)
        mock_client.batch_write_item.return_value = {
            "UnprocessedItems": {"tbl": one_item}
        }

        with patch("time.sleep") as mock_sleep:
            with pytest.raises(RuntimeError):
                provider._batch_write(one_item)

        # Should have slept 3 times: 0.1, 0.2, 0.4
        expected_calls = [call(0.1), call(0.2), call(0.4)]
        mock_sleep.assert_has_calls(expected_calls)
        assert mock_sleep.call_count == 3


class TestBatchWriteRaisesAfterMaxRetries:
    """_batch_write raises RuntimeError when items remain after 3 retries."""

    def test_raises_runtime_error_after_three_retries(self):
        """RuntimeError is raised after 3 retry attempts (4 total API calls)."""
        provider, mock_client = _make_mock_provider()

        one_item = [{"PutRequest": {"Item": {"PK": "pk0", "SK": "sk0"}}}]

        mock_client.batch_write_item.return_value = {
            "UnprocessedItems": {"tbl": one_item}
        }

        with patch("time.sleep"):
            with pytest.raises(RuntimeError) as exc_info:
                provider._batch_write(one_item)

        assert "unprocessed" in str(exc_info.value).lower()
        # 1 initial attempt + 3 retries = 4 total calls
        assert mock_client.batch_write_item.call_count == 4

    def test_raises_with_message_containing_count(self):
        """RuntimeError message mentions the number of unprocessed items."""
        provider, mock_client = _make_mock_provider()

        stuck_items = [
            {"PutRequest": {"Item": {"PK": f"pk{i}", "SK": f"sk{i}"}}} for i in range(3)
        ]

        mock_client.batch_write_item.return_value = {
            "UnprocessedItems": {"tbl": stuck_items}
        }

        with patch("time.sleep"):
            with pytest.raises(RuntimeError) as exc_info:
                provider._batch_write(stuck_items)

        assert "3" in str(exc_info.value)


# ---------------------------------------------------------------------------
# _batch_write — chunk boundary tests
# ---------------------------------------------------------------------------


class TestBatchWriteChunking:
    """_batch_write splits items into chunks of exactly 25."""

    def test_26_items_makes_two_api_calls(self):
        """26 items are split into a chunk of 25 and a chunk of 1."""
        provider, mock_client = _make_mock_provider()
        mock_client.batch_write_item.return_value = {"UnprocessedItems": {}}

        items = [
            {"PutRequest": {"Item": {"PK": f"pk{i}", "SK": f"sk{i}"}}} for i in range(26)
        ]

        provider._batch_write(items)

        assert mock_client.batch_write_item.call_count == 2

        first_chunk = mock_client.batch_write_item.call_args_list[0][1][
            "RequestItems"
        ]["tbl"]
        second_chunk = mock_client.batch_write_item.call_args_list[1][1][
            "RequestItems"
        ]["tbl"]

        assert len(first_chunk) == 25
        assert len(second_chunk) == 1

    def test_50_items_makes_two_api_calls_of_25(self):
        """50 items are split into two equal chunks of 25."""
        provider, mock_client = _make_mock_provider()
        mock_client.batch_write_item.return_value = {"UnprocessedItems": {}}

        items = [
            {"PutRequest": {"Item": {"PK": f"pk{i}", "SK": f"sk{i}"}}} for i in range(50)
        ]

        provider._batch_write(items)

        assert mock_client.batch_write_item.call_count == 2
        for api_call in mock_client.batch_write_item.call_args_list:
            chunk = api_call[1]["RequestItems"]["tbl"]
            assert len(chunk) == 25

    def test_25_items_makes_exactly_one_api_call(self):
        """Exactly 25 items fit in a single chunk -> one API call."""
        provider, mock_client = _make_mock_provider()
        mock_client.batch_write_item.return_value = {"UnprocessedItems": {}}

        items = [
            {"PutRequest": {"Item": {"PK": f"pk{i}", "SK": f"sk{i}"}}} for i in range(25)
        ]

        provider._batch_write(items)

        assert mock_client.batch_write_item.call_count == 1


# ---------------------------------------------------------------------------
# store_feedbacks_batch — integration tests using moto
# ---------------------------------------------------------------------------


@pytest.fixture
def moto_provider():
    """DynamoDBStorageProvider backed by moto for integration-level tests."""
    try:
        from moto import mock_aws
    except ImportError:
        pytest.skip("moto not installed")

    import boto3

    from app.infrastructure.storage.dynamodb_storage_provider import (
        DynamoDBStorageProvider,
    )

    with mock_aws():
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
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
                {"AttributeName": "GSI2PK", "AttributeType": "S"},
                {"AttributeName": "GSI2SK", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "GSI2",
                    "KeySchema": [
                        {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
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


class TestStoreFeedbacksBatch:
    """store_feedbacks_batch stores all feedbacks and returns feedback_ids."""

    def test_returns_one_id_per_feedback(self, moto_provider):
        """Returns a list of the same length as the input feedbacks list."""
        feedbacks = [
            {
                "text": f"Review number {i}",
                "sentiment": "positivo",
                "score": 0.5,
                "keywords": ["bueno"],
                "status": "success",
            }
            for i in range(5)
        ]
        ids = moto_provider.store_feedbacks_batch("batch-001", feedbacks)
        assert len(ids) == 5

    def test_returned_ids_are_unique_uuids(self, moto_provider):
        """Every returned feedback_id is a unique UUID v4."""
        feedbacks = [
            {
                "text": "texto",
                "sentiment": "neutro",
                "score": 0.0,
                "keywords": [],
                "status": "success",
            }
            for _ in range(3)
        ]
        ids = moto_provider.store_feedbacks_batch("batch-002", feedbacks)

        assert len(set(ids)) == 3
        for fid in ids:
            parsed = uuid.UUID(fid, version=4)
            assert str(parsed) == fid

    def test_empty_feedbacks_returns_empty_list(self, moto_provider):
        """store_feedbacks_batch([]) returns [] without making any API calls."""
        ids = moto_provider.store_feedbacks_batch("batch-empty", [])
        assert ids == []

    def test_all_items_queryable_after_batch_write(self, moto_provider):
        """Items written via batch are retrievable by GSI1 query."""
        from boto3.dynamodb.conditions import Key

        from app.infrastructure.storage.dynamodb_storage_provider import (
            GSI1_NAME,
            GSI1_PK,
            PK_BATCH,
        )

        feedbacks = [
            {
                "text": f"texto {i}",
                "sentiment": "negativo",
                "score": -0.3,
                "keywords": [],
                "status": "success",
            }
            for i in range(4)
        ]
        moto_provider.store_feedbacks_batch("batch-003", feedbacks)

        gsi1_pk_value = PK_BATCH.format("batch-003")
        response = moto_provider._table.query(
            IndexName=GSI1_NAME,
            KeyConditionExpression=Key(GSI1_PK).eq(gsi1_pk_value),
        )
        stored_items = response.get("Items", [])
        assert len(stored_items) == 4

    def test_feedback_fields_stored_correctly(self, moto_provider):
        """Stored feedback item has correct field values."""
        from app.infrastructure.storage.dynamodb_storage_provider import (
            PK_BATCH,
            SK_FEEDBACK,
        )

        feedbacks = [
            {
                "text": "Excelente producto",
                "sentiment": "positivo",
                "score": 0.9,
                "keywords": ["excelente"],
                "status": "success",
            }
        ]
        ids = moto_provider.store_feedbacks_batch("batch-004", feedbacks)
        feedback_id = ids[0]

        pk = PK_BATCH.format("batch-004")
        sk = SK_FEEDBACK.format(feedback_id)
        response = moto_provider._table.get_item(Key={"PK": pk, "SK": sk})
        item = response.get("Item")

        assert item is not None
        assert item["id"] == feedback_id
        assert item["batch_id"] == "batch-004"
        assert item["original_text"] == "Excelente producto"
        assert item["sentiment"] == "positivo"
        assert float(item["score"]) == pytest.approx(0.9, abs=1e-9)
        assert item["status"] == "success"

    def test_text_truncated_to_5000_chars(self, moto_provider):
        """Texts longer than 5000 chars are truncated before storage."""
        from app.infrastructure.storage.dynamodb_storage_provider import (
            PK_BATCH,
            SK_FEEDBACK,
        )

        long_text = "x" * 6000
        feedbacks = [
            {
                "text": long_text,
                "sentiment": "neutro",
                "score": 0.0,
                "keywords": [],
                "status": "success",
            }
        ]
        ids = moto_provider.store_feedbacks_batch("batch-005", feedbacks)
        feedback_id = ids[0]

        pk = PK_BATCH.format("batch-005")
        sk = SK_FEEDBACK.format(feedback_id)
        item = moto_provider._table.get_item(Key={"PK": pk, "SK": sk})["Item"]

        assert len(item["original_text"]) == 5000

    def test_keyword_index_items_created(self, moto_provider):
        """Keyword index items (SK begins with KW#) are created for each valid keyword."""
        from boto3.dynamodb.conditions import Key

        from app.infrastructure.storage.dynamodb_storage_provider import (
            PK_BATCH,
            SK_KW_PREFIX,
        )

        feedbacks = [
            {
                "text": "buen servicio rapido",
                "sentiment": "positivo",
                "score": 0.7,
                "keywords": ["servicio", "rapido"],
                "status": "success",
            }
        ]
        moto_provider.store_feedbacks_batch("batch-006", feedbacks)

        pk = PK_BATCH.format("batch-006")
        response = moto_provider._table.query(
            KeyConditionExpression=(
                Key("PK").eq(pk) & Key("SK").begins_with(SK_KW_PREFIX)
            )
        )
        kw_items = response.get("Items", [])
        # 2 keywords -> 2 keyword index items
        assert len(kw_items) == 2
        stored_words = {item["word"] for item in kw_items}
        assert stored_words == {"servicio", "rapido"}

    def test_keywords_shorter_than_3_chars_not_indexed(self, moto_provider):
        """Keywords with 2 or fewer characters are NOT stored as index items."""
        from boto3.dynamodb.conditions import Key

        from app.infrastructure.storage.dynamodb_storage_provider import (
            PK_BATCH,
            SK_KW_PREFIX,
        )

        feedbacks = [
            {
                "text": "ok si bien",
                "sentiment": "neutro",
                "score": 0.0,
                "keywords": ["ok", "si", "bien"],  # "ok" and "si" are <=2 chars
                "status": "success",
            }
        ]
        moto_provider.store_feedbacks_batch("batch-007", feedbacks)

        pk = PK_BATCH.format("batch-007")
        response = moto_provider._table.query(
            KeyConditionExpression=(
                Key("PK").eq(pk) & Key("SK").begins_with(SK_KW_PREFIX)
            )
        )
        kw_items = response.get("Items", [])
        # Only "bien" (4 chars) qualifies
        assert len(kw_items) == 1
        assert kw_items[0]["word"] == "bien"

    def test_each_returned_id_corresponds_to_a_stored_item(self, moto_provider):
        """Every returned ID corresponds to a real item in DynamoDB."""
        from app.infrastructure.storage.dynamodb_storage_provider import (
            PK_BATCH,
            SK_FEEDBACK,
        )

        feedbacks = [
            {
                "text": f"item {i}",
                "sentiment": "neutro",
                "score": 0.0,
                "keywords": [],
                "status": "success",
            }
            for i in range(10)
        ]
        ids = moto_provider.store_feedbacks_batch("batch-008", feedbacks)

        pk = PK_BATCH.format("batch-008")
        for fid in ids:
            sk = SK_FEEDBACK.format(fid)
            item = moto_provider._table.get_item(Key={"PK": pk, "SK": sk}).get("Item")
            assert item is not None, f"Feedback {fid} not found in DynamoDB"

    def test_store_feedbacks_batch_compatible_with_get_batch_feedbacks(self, moto_provider):
        """Feedbacks stored via batch are returned by get_batch_feedbacks."""
        feedbacks = [
            {
                "text": f"comentario {i}",
                "sentiment": "positivo",
                "score": 0.6,
                "keywords": ["bueno"],
                "status": "success",
            }
            for i in range(3)
        ]
        moto_provider.store_feedbacks_batch("batch-009", feedbacks)

        result = moto_provider.get_batch_feedbacks("batch-009", page=1, page_size=10)
        assert result["total"] == 3
        assert len(result["items"]) == 3
