"""Unit tests for DynamoDBStorageProvider user operations.

Validates: Requirements 6.8, 6.9, 6.11
"""

import pytest
from datetime import datetime, timezone, timedelta

from app.infrastructure.storage.dynamodb_storage_provider import (
    DynamoDBStorageProvider,
    PK_USER,
    PK_USERID,
)


# ---------------------------------------------------------------------------
# Fixture: DynamoDB table backed by moto
# ---------------------------------------------------------------------------

@pytest.fixture
def dynamodb_provider():
    """
    Create a DynamoDBStorageProvider backed by a moto-mocked DynamoDB table.
    """
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
# create_user (Requirement 6.8)
# ---------------------------------------------------------------------------

class TestCreateUser:
    """Requirement 6.8: create_user stores user and returns generated user_id."""

    def test_returns_uuid_string(self, dynamodb_provider):
        """create_user returns a valid UUID v4 string."""
        import uuid

        user_id = dynamodb_provider.create_user(
            "alice@example.com", "hashed_password", "ACME Corp"
        )
        assert isinstance(user_id, str)
        parsed = uuid.UUID(user_id, version=4)
        assert str(parsed) == user_id

    def test_user_item_stored_with_correct_fields(self, dynamodb_provider):
        """create_user stores all required fields on the USER# item."""
        user_id = dynamodb_provider.create_user(
            "bob@example.com", "pw_hash_value", "Bob Business"
        )

        pk = PK_USER.format("bob@example.com")
        response = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": pk})
        item = response["Item"]

        assert item["id"] == user_id
        assert item["email"] == "bob@example.com"
        assert item["password_hash"] == "pw_hash_value"
        assert item["company_name"] == "Bob Business"
        assert int(item["failed_attempts"]) == 0
        assert item["locked_until"] is None
        assert "created_at" in item

    def test_userid_pointer_item_stored(self, dynamodb_provider):
        """create_user also writes the USERID# pointer item with the email."""
        user_id = dynamodb_provider.create_user(
            "carol@example.com", "hashed", "Carol Co"
        )

        pk = PK_USERID.format(user_id)
        response = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": pk})
        item = response["Item"]

        assert item["email"] == "carol@example.com"

    def test_created_at_is_utc_iso8601(self, dynamodb_provider):
        """created_at field is a valid timezone-aware UTC ISO-8601 timestamp."""
        dynamodb_provider.create_user("dave@example.com", "hashed", "Dave Inc")

        pk = PK_USER.format("dave@example.com")
        response = dynamodb_provider._table.get_item(Key={"PK": pk, "SK": pk})
        created_at = response["Item"]["created_at"]

        parsed = datetime.fromisoformat(created_at)
        assert parsed.tzinfo is not None

    def test_failed_attempts_initialized_to_zero(self, dynamodb_provider):
        """create_user initializes failed_attempts to 0."""
        dynamodb_provider.create_user("eve@example.com", "hashed", "Eve LLC")
        user = dynamodb_provider.get_user_by_email("eve@example.com")

        assert user["failed_attempts"] == 0

    def test_locked_until_initialized_to_none(self, dynamodb_provider):
        """create_user initializes locked_until to None."""
        dynamodb_provider.create_user("frank@example.com", "hashed", "Frank Co")
        user = dynamodb_provider.get_user_by_email("frank@example.com")

        assert user["locked_until"] is None


# ---------------------------------------------------------------------------
# create_user — duplicate email (Requirement 6.11)
# ---------------------------------------------------------------------------

class TestCreateUserDuplicate:
    """Requirement 6.11: create_user with duplicate email raises ValueError."""

    def test_duplicate_email_raises_value_error(self, dynamodb_provider):
        """Second create_user with same email raises ValueError('duplicate email')."""
        dynamodb_provider.create_user("grace@example.com", "hash1", "Grace Corp")

        with pytest.raises(ValueError, match="duplicate email"):
            dynamodb_provider.create_user("grace@example.com", "hash2", "Other Corp")

    def test_original_record_not_overwritten(self, dynamodb_provider):
        """The first record remains intact after a duplicate attempt."""
        dynamodb_provider.create_user("henry@example.com", "original_hash", "Henry Co")

        try:
            dynamodb_provider.create_user("henry@example.com", "new_hash", "Other")
        except ValueError:
            pass

        user = dynamodb_provider.get_user_by_email("henry@example.com")
        assert user["password_hash"] == "original_hash"
        assert user["company_name"] == "Henry Co"


# ---------------------------------------------------------------------------
# get_user_by_email (Requirement 6.9)
# ---------------------------------------------------------------------------

class TestGetUserByEmail:
    """Requirement 6.9: get_user_by_email returns None or full user dict."""

    def test_returns_none_when_not_found(self, dynamodb_provider):
        """Returns None when no user exists with the given email."""
        result = dynamodb_provider.get_user_by_email("nonexistent@example.com")
        assert result is None

    def test_returns_dict_with_all_required_fields(self, dynamodb_provider):
        """Returns dict with id, email, password_hash, company_name,
        failed_attempts, locked_until, created_at."""
        user_id = dynamodb_provider.create_user(
            "iris@example.com", "hashed_pw", "Iris Ltd"
        )

        result = dynamodb_provider.get_user_by_email("iris@example.com")

        assert result is not None
        assert result["id"] == user_id
        assert result["email"] == "iris@example.com"
        assert result["password_hash"] == "hashed_pw"
        assert result["company_name"] == "Iris Ltd"
        assert result["failed_attempts"] == 0
        assert result["locked_until"] is None
        assert "created_at" in result

    def test_failed_attempts_returned_as_int(self, dynamodb_provider):
        """failed_attempts is returned as a native Python int (not Decimal)."""
        dynamodb_provider.create_user("jack@example.com", "hashed", "Jack Co")
        result = dynamodb_provider.get_user_by_email("jack@example.com")

        assert isinstance(result["failed_attempts"], int)


# ---------------------------------------------------------------------------
# increment_failed_attempts
# ---------------------------------------------------------------------------

class TestIncrementFailedAttempts:
    """increment_failed_attempts atomically increments and returns the new count."""

    def test_increments_from_zero(self, dynamodb_provider):
        """First increment returns 1."""
        user_id = dynamodb_provider.create_user(
            "kate@example.com", "hashed", "Kate Corp"
        )
        result = dynamodb_provider.increment_failed_attempts(user_id)
        assert result == 1

    def test_increments_multiple_times(self, dynamodb_provider):
        """Multiple increments accumulate correctly."""
        user_id = dynamodb_provider.create_user(
            "leo@example.com", "hashed", "Leo Inc"
        )
        for expected in range(1, 6):
            result = dynamodb_provider.increment_failed_attempts(user_id)
            assert result == expected

    def test_persisted_value_matches_returned(self, dynamodb_provider):
        """The stored value matches the returned value."""
        user_id = dynamodb_provider.create_user(
            "mia@example.com", "hashed", "Mia LLC"
        )
        dynamodb_provider.increment_failed_attempts(user_id)
        dynamodb_provider.increment_failed_attempts(user_id)

        user = dynamodb_provider.get_user_by_email("mia@example.com")
        assert user["failed_attempts"] == 2

    def test_returns_zero_for_unknown_user(self, dynamodb_provider):
        """Returns 0 gracefully for a user_id that does not exist."""
        result = dynamodb_provider.increment_failed_attempts("nonexistent-id")
        assert result == 0


# ---------------------------------------------------------------------------
# reset_failed_attempts
# ---------------------------------------------------------------------------

class TestResetFailedAttempts:
    """reset_failed_attempts sets failed_attempts back to 0."""

    def test_reset_clears_count(self, dynamodb_provider):
        """After incrementing, reset brings count back to 0."""
        user_id = dynamodb_provider.create_user(
            "nina@example.com", "hashed", "Nina Co"
        )
        dynamodb_provider.increment_failed_attempts(user_id)
        dynamodb_provider.increment_failed_attempts(user_id)

        dynamodb_provider.reset_failed_attempts(user_id)

        user = dynamodb_provider.get_user_by_email("nina@example.com")
        assert user["failed_attempts"] == 0

    def test_reset_unknown_user_no_error(self, dynamodb_provider):
        """reset_failed_attempts on a nonexistent user_id does not raise."""
        dynamodb_provider.reset_failed_attempts("nonexistent-id")


# ---------------------------------------------------------------------------
# lock_account
# ---------------------------------------------------------------------------

class TestLockAccount:
    """lock_account sets locked_until to the provided datetime as ISO-8601 string."""

    def test_sets_locked_until(self, dynamodb_provider):
        """lock_account stores locked_until as an ISO-8601 parseable string."""
        user_id = dynamodb_provider.create_user(
            "oscar@example.com", "hashed", "Oscar Corp"
        )
        until = datetime.now(timezone.utc) + timedelta(minutes=15)

        dynamodb_provider.lock_account(user_id, until)

        user = dynamodb_provider.get_user_by_email("oscar@example.com")
        assert user["locked_until"] is not None
        parsed = datetime.fromisoformat(user["locked_until"])
        assert parsed is not None

    def test_lock_unknown_user_no_error(self, dynamodb_provider):
        """lock_account on a nonexistent user_id does not raise."""
        until = datetime.now(timezone.utc) + timedelta(minutes=15)
        dynamodb_provider.lock_account("nonexistent-id", until)
