"""Unit tests for DynamoDBStorageProvider batch operations.

Validates: Requirements 6.3, 6.12, 7.1, 7.2, 7.3
"""

import math
import uuid
from datetime import datetime, timezone

import pytest

from app.infrastructure.storage.dynamodb_storage_provider import (
    DynamoDBStorageProvider,
    PK_BATCH_PTR,
    PK_USER_ID,
    SK_BATCH,
)


# ---------------------------------------------------------------------------
# Fixture: DynamoDB table backed by moto
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
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        provider = DynamoDBStorageProvider(
            table_name="sentify-test", region="us-east-1"
        )
        yield provider


# ---------------------------------------------------------------------------
# create_batch (Requirement 6.3, 6.10)
# ---------------------------------------------------------------------------


class TestCreateBatch:
    """create_batch stores a batch item and returns a valid batch_id."""

    def test_returns_uuid_v4_string(self, dynamodb_provider):
        """create_batch returns a valid UUID v4 string."""
        batch_id = dynamodb_provider.create_batch("user-001", "reviews.csv")
        assert isinstance(batch_id, str)
        parsed = uuid.UUID(batch_id, version=4)
        assert str(parsed) == batch_id

    def test_batch_item_stored_with_correct_pk_sk(self, dynamodb_provider):
        """Primary item is stored at PK=USER#{user_id}, SK=BATCH#{batch_id}."""
        batch_id = dynamodb_provider.create_batch("user-001", "reviews.csv")

        pk = PK_USER_ID.format("user-001")
        sk = SK_BATCH.format(batch_id)
        response = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": sk})
        item = response.get("Item")

        assert item is not None

    def test_batch_item_has_pending_status(self, dynamodb_provider):
        """Newly created batch has status='pending'."""
        batch_id = dynamodb_provider.create_batch("user-001", "reviews.csv")

        pk = PK_USER_ID.format("user-001")
        sk = SK_BATCH.format(batch_id)
        response = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": sk})
        item = response["Item"]

        assert item["status"] == "pending"

    def test_batch_item_fields(self, dynamodb_provider):
        """Batch item stores id, user_id, filename, and zero counters."""
        batch_id = dynamodb_provider.create_batch("user-001", "reviews.csv")

        pk = PK_USER_ID.format("user-001")
        sk = SK_BATCH.format(batch_id)
        response = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": sk})
        item = response["Item"]

        assert item["id"] == batch_id
        assert item["user_id"] == "user-001"
        assert item["filename"] == "reviews.csv"
        assert int(item["total_rows"]) == 0
        assert int(item["processed_rows"]) == 0
        assert int(item["error_rows"]) == 0
        assert item["completed_at"] is None

    def test_uploaded_at_is_utc_iso8601(self, dynamodb_provider):
        """uploaded_at field is a valid timezone-aware UTC ISO-8601 timestamp."""
        batch_id = dynamodb_provider.create_batch("user-001", "reviews.csv")

        pk = PK_USER_ID.format("user-001")
        sk = SK_BATCH.format(batch_id)
        response = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": sk})
        uploaded_at = response["Item"]["uploaded_at"]

        parsed = datetime.fromisoformat(uploaded_at)
        assert parsed.tzinfo is not None

    def test_pointer_item_written(self, dynamodb_provider):
        """A pointer item BATCH#{batch_id} storing user_id is also written."""
        batch_id = dynamodb_provider.create_batch("user-001", "reviews.csv")

        ptr_pk = PK_BATCH_PTR.format(batch_id)
        response = dynamodb_provider._table.get_item(
            Key={"PK": ptr_pk, "SK": ptr_pk}
        )
        item = response.get("Item")

        assert item is not None
        assert item["user_id"] == "user-001"

    def test_each_call_returns_unique_batch_id(self, dynamodb_provider):
        """Two calls with the same user_id return different batch_ids."""
        b1 = dynamodb_provider.create_batch("user-001", "file1.csv")
        b2 = dynamodb_provider.create_batch("user-001", "file2.csv")
        assert b1 != b2


# ---------------------------------------------------------------------------
# update_batch_status (Requirements 6.12, 7.1)
# ---------------------------------------------------------------------------


class TestUpdateBatchStatus:
    """update_batch_status updates status and sets completed_at when 'completed'."""

    def test_status_updated_to_processing(self, dynamodb_provider):
        """Status can be updated from 'pending' to 'processing'."""
        batch_id = dynamodb_provider.create_batch("user-002", "data.csv")
        dynamodb_provider.update_batch_status(batch_id, "processing")

        pk = PK_USER_ID.format("user-002")
        sk = SK_BATCH.format(batch_id)
        response = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": sk})

        assert response["Item"]["status"] == "processing"

    def test_completed_at_set_when_status_completed(self, dynamodb_provider):
        """completed_at is set to a UTC ISO-8601 string when status='completed'."""
        batch_id = dynamodb_provider.create_batch("user-002", "data.csv")
        dynamodb_provider.update_batch_status(batch_id, "completed")

        pk = PK_USER_ID.format("user-002")
        sk = SK_BATCH.format(batch_id)
        response = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": sk})
        item = response["Item"]

        assert item["status"] == "completed"
        assert item.get("completed_at") is not None
        parsed = datetime.fromisoformat(item["completed_at"])
        assert parsed.tzinfo is not None

    def test_completed_at_not_set_for_processing_status(self, dynamodb_provider):
        """completed_at is NOT set when status is 'processing' (not 'completed')."""
        batch_id = dynamodb_provider.create_batch("user-002", "data.csv")
        dynamodb_provider.update_batch_status(batch_id, "processing")

        pk = PK_USER_ID.format("user-002")
        sk = SK_BATCH.format(batch_id)
        response = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": sk})
        item = response["Item"]

        completed_at = item.get("completed_at")
        assert not completed_at  # None or empty string

    def test_completed_at_not_set_for_failed_status(self, dynamodb_provider):
        """completed_at is NOT set when status is 'failed'."""
        batch_id = dynamodb_provider.create_batch("user-002", "data.csv")
        dynamodb_provider.update_batch_status(batch_id, "failed")

        pk = PK_USER_ID.format("user-002")
        sk = SK_BATCH.format(batch_id)
        response = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": sk})
        item = response["Item"]

        completed_at = item.get("completed_at")
        assert not completed_at

    def test_nonexistent_batch_does_not_raise(self, dynamodb_provider):
        """update_batch_status on a nonexistent batch_id does not raise."""
        dynamodb_provider.update_batch_status("nonexistent-batch", "completed")


# ---------------------------------------------------------------------------
# update_batch_counts (Requirement 7.2)
# ---------------------------------------------------------------------------


class TestUpdateBatchCounts:
    """update_batch_counts atomically adds to the row counters."""

    def test_adds_counts_from_initial_zero(self, dynamodb_provider):
        """First call adds its values to the initial zero counters."""
        batch_id = dynamodb_provider.create_batch("user-003", "rows.csv")
        dynamodb_provider.update_batch_counts(batch_id, 100, 90, 10)

        pk = PK_USER_ID.format("user-003")
        sk = SK_BATCH.format(batch_id)
        response = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": sk})
        item = response["Item"]

        assert int(item["total_rows"]) == 100
        assert int(item["processed_rows"]) == 90
        assert int(item["error_rows"]) == 10

    def test_counts_accumulate_across_calls(self, dynamodb_provider):
        """Multiple calls ADD to the existing counters (atomic ADD semantics)."""
        batch_id = dynamodb_provider.create_batch("user-003", "rows.csv")
        dynamodb_provider.update_batch_counts(batch_id, 50, 45, 5)
        dynamodb_provider.update_batch_counts(batch_id, 50, 40, 10)

        pk = PK_USER_ID.format("user-003")
        sk = SK_BATCH.format(batch_id)
        response = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": sk})
        item = response["Item"]

        assert int(item["total_rows"]) == 100
        assert int(item["processed_rows"]) == 85
        assert int(item["error_rows"]) == 15

    def test_zero_increments_leave_counts_unchanged(self, dynamodb_provider):
        """Calling with zeros does not change existing counts."""
        batch_id = dynamodb_provider.create_batch("user-003", "rows.csv")
        dynamodb_provider.update_batch_counts(batch_id, 10, 10, 0)
        dynamodb_provider.update_batch_counts(batch_id, 0, 0, 0)

        pk = PK_USER_ID.format("user-003")
        sk = SK_BATCH.format(batch_id)
        response = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": sk})
        item = response["Item"]

        assert int(item["total_rows"]) == 10
        assert int(item["processed_rows"]) == 10
        assert int(item["error_rows"]) == 0

    def test_nonexistent_batch_does_not_raise(self, dynamodb_provider):
        """update_batch_counts on a nonexistent batch_id does not raise."""
        dynamodb_provider.update_batch_counts("nonexistent-batch", 10, 8, 2)


# ---------------------------------------------------------------------------
# get_user_batches (Requirement 7.3)
# ---------------------------------------------------------------------------


class TestGetUserBatches:
    """get_user_batches returns paginated batches ordered by uploaded_at desc."""

    def test_returns_empty_for_new_user(self, dynamodb_provider):
        """A user with no batches gets an empty result."""
        result = dynamodb_provider.get_user_batches("user-empty", page=1)

        assert result["items"] == []
        assert result["total"] == 0
        assert result["total_pages"] == 0

    def test_returns_correct_pagination_structure(self, dynamodb_provider):
        """Result dict has keys: items, total, page, page_size, total_pages."""
        dynamodb_provider.create_batch("user-004", "f1.csv")
        result = dynamodb_provider.get_user_batches("user-004", page=1, page_size=10)

        assert "items" in result
        assert "total" in result
        assert "page" in result
        assert "page_size" in result
        assert "total_pages" in result

    def test_page_and_page_size_echoed_in_result(self, dynamodb_provider):
        """page and page_size in the result match what was requested."""
        dynamodb_provider.create_batch("user-004b", "f1.csv")
        result = dynamodb_provider.get_user_batches("user-004b", page=1, page_size=5)

        assert result["page"] == 1
        assert result["page_size"] == 5

    def test_single_batch_all_fields_present(self, dynamodb_provider):
        """Each item dict has all required fields."""
        batch_id = dynamodb_provider.create_batch("user-005", "report.csv")
        result = dynamodb_provider.get_user_batches("user-005", page=1)
        item = result["items"][0]

        assert item["id"] == batch_id
        assert item["user_id"] == "user-005"
        assert item["filename"] == "report.csv"
        assert item["status"] == "pending"
        assert isinstance(item["total_rows"], int)
        assert isinstance(item["processed_rows"], int)
        assert isinstance(item["error_rows"], int)
        assert "uploaded_at" in item
        assert "completed_at" in item

    def test_total_reflects_number_of_batches(self, dynamodb_provider):
        """total in the result equals the number of batches for the user."""
        for i in range(3):
            dynamodb_provider.create_batch("user-006", f"file{i}.csv")

        result = dynamodb_provider.get_user_batches("user-006", page=1, page_size=10)
        assert result["total"] == 3

    def test_total_pages_calculation(self, dynamodb_provider):
        """total_pages = ceil(total / page_size)."""
        for i in range(7):
            dynamodb_provider.create_batch("user-007", f"file{i}.csv")

        result = dynamodb_provider.get_user_batches("user-007", page=1, page_size=3)
        assert result["total_pages"] == math.ceil(7 / 3)

    def test_pagination_second_page(self, dynamodb_provider):
        """Page 2 returns the next slice of results."""
        for i in range(5):
            dynamodb_provider.create_batch("user-008", f"file{i}.csv")

        p1 = dynamodb_provider.get_user_batches("user-008", page=1, page_size=3)
        p2 = dynamodb_provider.get_user_batches("user-008", page=2, page_size=3)

        assert len(p1["items"]) == 3
        assert len(p2["items"]) == 2

        # No overlap between pages
        ids_p1 = {it["id"] for it in p1["items"]}
        ids_p2 = {it["id"] for it in p2["items"]}
        assert ids_p1.isdisjoint(ids_p2)

    def test_batches_ordered_by_uploaded_at_descending(self, dynamodb_provider):
        """Batches are returned in descending uploaded_at order."""
        for i in range(3):
            dynamodb_provider.create_batch("user-009", f"file{i}.csv")

        result = dynamodb_provider.get_user_batches("user-009", page=1, page_size=10)
        timestamps = [it["uploaded_at"] for it in result["items"]]

        # Each timestamp should be >= the next (descending order)
        for a, b in zip(timestamps, timestamps[1:]):
            assert a >= b

    def test_does_not_return_other_users_batches(self, dynamodb_provider):
        """Batches from other users are not included in the result."""
        dynamodb_provider.create_batch("user-A", "mine.csv")
        dynamodb_provider.create_batch("user-B", "theirs.csv")

        result = dynamodb_provider.get_user_batches("user-A", page=1)
        assert result["total"] == 1
        assert result["items"][0]["user_id"] == "user-A"

    def test_decimal_counters_returned_as_int(self, dynamodb_provider):
        """Row counter fields are returned as native Python ints, not Decimal."""
        batch_id = dynamodb_provider.create_batch("user-010", "data.csv")
        dynamodb_provider.update_batch_counts(batch_id, 42, 40, 2)

        result = dynamodb_provider.get_user_batches("user-010", page=1)
        item = result["items"][0]

        assert isinstance(item["total_rows"], int)
        assert isinstance(item["processed_rows"], int)
        assert isinstance(item["error_rows"], int)
        assert item["total_rows"] == 42
        assert item["processed_rows"] == 40
        assert item["error_rows"] == 2

    def test_completed_at_present_after_status_completed(self, dynamodb_provider):
        """completed_at is populated in get_user_batches after status='completed'."""
        batch_id = dynamodb_provider.create_batch("user-011", "done.csv")
        dynamodb_provider.update_batch_status(batch_id, "completed")

        result = dynamodb_provider.get_user_batches("user-011", page=1)
        item = result["items"][0]

        assert item["completed_at"] is not None
        parsed = datetime.fromisoformat(item["completed_at"])
        assert parsed.tzinfo is not None

    def test_total_pages_is_one_when_items_fit_in_one_page(self, dynamodb_provider):
        """total_pages == 1 when total <= page_size."""
        dynamodb_provider.create_batch("user-012", "a.csv")
        dynamodb_provider.create_batch("user-012", "b.csv")

        result = dynamodb_provider.get_user_batches("user-012", page=1, page_size=10)
        assert result["total_pages"] == 1
