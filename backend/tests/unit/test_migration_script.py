"""Unit tests for migrate_sqlite_to_dynamodb.py.

Covers:
  - _batch_write_with_retry  (chunking, retry/backoff, exhausted retries,
                               dry_run, ResourceNotFoundException propagation)
  - _transform_user          (PK/SK patterns, None locked_until omitted)
  - _transform_batch         (PK/SK patterns)
  - _transform_feedback      (main item + keyword index items, GSI attrs)
  - _to_dynamo               (type-conversion matrix)
  - migrate                  (dry-run integration with real in-memory SQLite)

Validates: Requirements 9.3, 9.4, 9.5, 9.6
"""

from __future__ import annotations

import sys
import os
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

# ---------------------------------------------------------------------------
# Path setup — allow importing the script from backend/scripts/
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from scripts.migrate_sqlite_to_dynamodb import (  # noqa: E402
    _batch_write_with_retry,
    _transform_user,
    _transform_batch,
    _transform_feedback,
    _to_dynamo,
    migrate,
    _CHUNK_SIZE,
    _MAX_RETRIES,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_put_requests(n: int) -> list[dict]:
    """Build a list of n minimal PutRequest dicts."""
    return [{"PutRequest": {"Item": {"PK": {"S": f"ITEM#{i}"}}}} for i in range(n)]


def _make_client_error(code: str) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": code}}, "BatchWriteItem"
    )


# ---------------------------------------------------------------------------
# 1. _batch_write_with_retry — chunk size of 25
# ---------------------------------------------------------------------------

class TestBatchWriteChunking:
    def test_26_items_produces_two_calls(self):
        """26 items -> 2 calls: first with 25, second with 1."""
        client = MagicMock()
        client.batch_write_item.return_value = {"UnprocessedItems": {}}

        items = _make_put_requests(26)
        written, failed = _batch_write_with_retry(client, "table", items)

        assert client.batch_write_item.call_count == 2
        first_call_items = client.batch_write_item.call_args_list[0][1]["RequestItems"]["table"]
        second_call_items = client.batch_write_item.call_args_list[1][1]["RequestItems"]["table"]
        assert len(first_call_items) == 25
        assert len(second_call_items) == 1
        assert written == 26
        assert failed == 0

    def test_25_items_produces_one_call(self):
        """25 items -> exactly 1 call."""
        client = MagicMock()
        client.batch_write_item.return_value = {"UnprocessedItems": {}}

        items = _make_put_requests(25)
        written, failed = _batch_write_with_retry(client, "table", items)

        assert client.batch_write_item.call_count == 1
        assert written == 25
        assert failed == 0

    def test_50_items_produces_two_calls_of_25(self):
        """50 items -> 2 calls, each with 25 items."""
        client = MagicMock()
        client.batch_write_item.return_value = {"UnprocessedItems": {}}

        items = _make_put_requests(50)
        written, failed = _batch_write_with_retry(client, "table", items)

        assert client.batch_write_item.call_count == 2
        for c in client.batch_write_item.call_args_list:
            assert len(c[1]["RequestItems"]["table"]) == 25
        assert written == 50
        assert failed == 0


# ---------------------------------------------------------------------------
# 2. _batch_write_with_retry — retry on UnprocessedItems
# ---------------------------------------------------------------------------

class TestBatchWriteRetry:
    def test_first_call_has_unprocessed_second_call_succeeds(self):
        """First call returns 2 unprocessed; second call succeeds -> written = chunk size, failed = 0."""
        chunk_size = 5
        unprocessed_items = _make_put_requests(2)

        client = MagicMock()
        client.batch_write_item.side_effect = [
            {"UnprocessedItems": {"table": unprocessed_items}},
            {"UnprocessedItems": {}},
        ]

        items = _make_put_requests(chunk_size)
        written, failed = _batch_write_with_retry(client, "table", items)

        # 5 items sent; 3 succeed on first pass, 2 unprocessed re-sent, all 2 succeed on retry
        assert written == chunk_size
        assert failed == 0
        assert client.batch_write_item.call_count == 2

    def test_backoff_sleep_called_with_correct_value(self):
        """time.sleep is called with 0.5s on attempt 0 (2^0 * 0.5 = 0.5)."""
        unprocessed_items = _make_put_requests(1)

        client = MagicMock()
        client.batch_write_item.side_effect = [
            {"UnprocessedItems": {"table": unprocessed_items}},
            {"UnprocessedItems": {}},
        ]

        items = _make_put_requests(3)
        with patch("scripts.migrate_sqlite_to_dynamodb.time.sleep") as mock_sleep:
            _batch_write_with_retry(client, "table", items)

        mock_sleep.assert_called_once_with(0.5)  # 2^0 * 0.5


# ---------------------------------------------------------------------------
# 3. _batch_write_with_retry — gives up after 5 retries
# ---------------------------------------------------------------------------

class TestBatchWriteExhaustedRetries:
    def test_always_unprocessed_gives_up_after_max_retries(self):
        """Always returning 2 unprocessed -> 6 total calls (1 + 5 retries), failed = 2."""
        stuck_items = _make_put_requests(2)
        chunk_items = _make_put_requests(5)

        client = MagicMock()
        # Always returns the same 2 unprocessed items
        client.batch_write_item.return_value = {
            "UnprocessedItems": {"table": stuck_items}
        }

        with patch("scripts.migrate_sqlite_to_dynamodb.time.sleep"):
            written, failed = _batch_write_with_retry(client, "table", chunk_items)

        # 1 initial + 5 retries = 6 total calls
        assert client.batch_write_item.call_count == _MAX_RETRIES + 1
        # First pass: 5 sent, 2 unprocessed -> 3 counted as written
        # All retries: 2 sent, 2 unprocessed -> 0 new successes each time
        assert written == 3
        assert failed == 2


# ---------------------------------------------------------------------------
# 4. _batch_write_with_retry — dry_run skips all calls
# ---------------------------------------------------------------------------

class TestBatchWriteDryRun:
    def test_dry_run_returns_len_items_zero_failed_no_calls(self):
        """dry_run=True returns (n, 0) without making any batch_write_item calls."""
        client = MagicMock()
        items = _make_put_requests(10)

        written, failed = _batch_write_with_retry(client, "table", items, dry_run=True)

        assert written == 10
        assert failed == 0
        client.batch_write_item.assert_not_called()


# ---------------------------------------------------------------------------
# 5. _batch_write_with_retry — ResourceNotFoundException propagates
# ---------------------------------------------------------------------------

class TestBatchWriteResourceNotFound:
    def test_resource_not_found_propagates(self):
        """ClientError with ResourceNotFoundException must propagate out."""
        client = MagicMock()
        client.batch_write_item.side_effect = _make_client_error("ResourceNotFoundException")

        items = _make_put_requests(3)
        with pytest.raises(ClientError) as exc_info:
            _batch_write_with_retry(client, "table", items)

        assert exc_info.value.response["Error"]["Code"] == "ResourceNotFoundException"


# ---------------------------------------------------------------------------
# 6. _transform_user — correct PK/SK
# ---------------------------------------------------------------------------

class TestTransformUser:
    def _sample_user(self, **overrides) -> dict:
        base = {
            "id": "uid-123",
            "email": "user@example.com",
            "password_hash": "placeholder_hash",
            "company_name": "Acme Corp",
            "failed_attempts": 0,
            "locked_until": None,
            "created_at": "2024-01-01T00:00:00",
        }
        base.update(overrides)
        return base

    def test_returns_two_put_requests(self):
        result = _transform_user(self._sample_user())
        assert len(result) == 2

    def test_main_item_pk_sk(self):
        """Main item has PK=USER#{email}, SK=USER#{email}."""
        user = self._sample_user(email="user@example.com")
        main = _transform_user(user)[0]["PutRequest"]["Item"]
        assert main["PK"] == {"S": "USER#user@example.com"}
        assert main["SK"] == {"S": "USER#user@example.com"}

    def test_pointer_item_pk_sk(self):
        """Pointer item has PK=USERID#{user_id}, SK=USERID#{user_id}."""
        user = self._sample_user(id="uid-123")
        pointer = _transform_user(user)[1]["PutRequest"]["Item"]
        assert pointer["PK"] == {"S": "USERID#uid-123"}
        assert pointer["SK"] == {"S": "USERID#uid-123"}

    def test_none_locked_until_is_absent(self):
        """When locked_until=None, the key must not appear in the main item."""
        main = _transform_user(self._sample_user(locked_until=None))[0]["PutRequest"]["Item"]
        assert "locked_until" not in main

    def test_non_none_locked_until_is_present(self):
        """When locked_until is set, the key appears in the main item."""
        main = _transform_user(
            self._sample_user(locked_until="2024-06-01T10:00:00")
        )[0]["PutRequest"]["Item"]
        assert "locked_until" in main


# ---------------------------------------------------------------------------
# 7. _transform_user — explicit NULL-omission check
# ---------------------------------------------------------------------------

class TestTransformUserLockedUntilOmission:
    def test_null_locked_until_not_stored_as_null(self):
        """None locked_until must not be stored as {NULL: True} — key must be absent."""
        user = {
            "id": "u1",
            "email": "a@b.com",
            "password_hash": "placeholder",
            "company_name": "X",
            "failed_attempts": 0,
            "locked_until": None,
            "created_at": None,
        }
        main = _transform_user(user)[0]["PutRequest"]["Item"]
        assert "locked_until" not in main


# ---------------------------------------------------------------------------
# 8. _transform_batch — correct PK/SK
# ---------------------------------------------------------------------------

class TestTransformBatch:
    def _sample_batch(self, **overrides) -> dict:
        base = {
            "id": "batch-456",
            "user_id": "user-789",
            "filename": "data.csv",
            "status": "completed",
            "total_rows": 100,
            "processed_rows": 98,
            "error_rows": 2,
            "uploaded_at": "2024-01-01T00:00:00",
            "completed_at": None,
        }
        base.update(overrides)
        return base

    def test_returns_two_items(self):
        assert len(_transform_batch(self._sample_batch())) == 2

    def test_main_item_pk_sk(self):
        """Main item PK=USER#{user_id}, SK=BATCH#{batch_id}."""
        batch = self._sample_batch(user_id="user-789", id="batch-456")
        main = _transform_batch(batch)[0]["PutRequest"]["Item"]
        assert main["PK"] == {"S": "USER#user-789"}
        assert main["SK"] == {"S": "BATCH#batch-456"}

    def test_pointer_item_pk_sk(self):
        """Pointer item PK=BATCH#{batch_id}, SK=BATCH#{batch_id}."""
        batch = self._sample_batch(id="batch-456")
        pointer = _transform_batch(batch)[1]["PutRequest"]["Item"]
        assert pointer["PK"] == {"S": "BATCH#batch-456"}
        assert pointer["SK"] == {"S": "BATCH#batch-456"}


# ---------------------------------------------------------------------------
# 9. _transform_feedback — main item + keyword index items
# ---------------------------------------------------------------------------

class TestTransformFeedback:
    def _sample_feedback(self, **overrides) -> dict:
        base = {
            "id": "fb-001",
            "batch_id": "batch-456",
            "original_text": "Este producto es bueno",
            "sentiment": "positivo",
            "score": 0.8,
            "status": "success",
            "error_reason": None,
            "analyzed_at": "2024-01-01T12:00:00",
        }
        base.update(overrides)
        return base

    def test_two_keywords_produce_three_items(self):
        """2 keywords -> 3 PutRequest items (1 feedback + 2 keyword index)."""
        result = _transform_feedback(self._sample_feedback(), ["bueno", "producto"])
        assert len(result) == 3

    def test_zero_keywords_produce_one_item(self):
        """0 keywords -> 1 PutRequest item (only the feedback main item)."""
        result = _transform_feedback(self._sample_feedback(), [])
        assert len(result) == 1

    def test_main_item_gsi1pk_equals_batch_pk(self):
        """GSI1PK on main item equals BATCH#{batch_id}."""
        fb = self._sample_feedback(batch_id="batch-456")
        main = _transform_feedback(fb, [])[0]["PutRequest"]["Item"]
        assert main["GSI1PK"] == {"S": "BATCH#batch-456"}

    def test_keyword_item_gsi2pk(self):
        """GSI2PK on keyword item = BATCH#{batch_id}#KW#{word}."""
        fb = self._sample_feedback(batch_id="batch-456")
        result = _transform_feedback(fb, ["word1"])
        kw_item = result[1]["PutRequest"]["Item"]
        assert kw_item["GSI2PK"] == {"S": "BATCH#batch-456#KW#word1"}

    def test_keyword_item_gsi2sk(self):
        """GSI2SK on keyword item = FEEDBACK#{feedback_id}."""
        fb = self._sample_feedback(id="fb-001")
        result = _transform_feedback(fb, ["word1"])
        kw_item = result[1]["PutRequest"]["Item"]
        assert kw_item["GSI2SK"] == {"S": "FEEDBACK#fb-001"}


# ---------------------------------------------------------------------------
# 10. _transform_feedback — text truncated to 5000
# ---------------------------------------------------------------------------

class TestTransformFeedbackTruncation:
    def _fb(self, text: str) -> dict:
        return {
            "id": "fb-002",
            "batch_id": "batch-001",
            "original_text": text,
            "sentiment": None,
            "score": None,
            "status": "success",
            "error_reason": None,
            "analyzed_at": None,
        }

    def test_text_6000_chars_truncated_to_5000(self):
        """Input text of 6000 chars -> stored original_text is exactly 5000 chars."""
        main = _transform_feedback(self._fb("a" * 6000), [])[0]["PutRequest"]["Item"]
        assert len(main["original_text"]["S"]) == 5000

    def test_text_under_5000_not_truncated(self):
        """Input text of 100 chars is stored as-is."""
        text = "b" * 100
        main = _transform_feedback(self._fb(text), [])[0]["PutRequest"]["Item"]
        assert main["original_text"]["S"] == text

    def test_text_exactly_5000_not_truncated(self):
        """Input text of exactly 5000 chars is stored unchanged."""
        text = "c" * 5000
        main = _transform_feedback(self._fb(text), [])[0]["PutRequest"]["Item"]
        assert len(main["original_text"]["S"]) == 5000


# ---------------------------------------------------------------------------
# 11. _to_dynamo — type conversions
# ---------------------------------------------------------------------------

class TestToDynamo:
    def test_none_maps_to_null(self):
        assert _to_dynamo(None) == {"NULL": True}

    def test_string_maps_to_s(self):
        assert _to_dynamo("hello") == {"S": "hello"}

    def test_int_maps_to_n(self):
        assert _to_dynamo(42) == {"N": "42"}

    def test_float_maps_to_n_via_decimal(self):
        result = _to_dynamo(0.75)
        assert result == {"N": str(Decimal("0.75"))}

    def test_bool_true_maps_to_bool(self):
        assert _to_dynamo(True) == {"BOOL": True}

    def test_bool_false_maps_to_bool(self):
        assert _to_dynamo(False) == {"BOOL": False}

    def test_list_maps_to_l(self):
        assert _to_dynamo(["a", "b"]) == {"L": [{"S": "a"}, {"S": "b"}]}

    def test_bool_processed_before_int(self):
        """bool is a subclass of int in Python; True must map to BOOL, not N."""
        result = _to_dynamo(True)
        assert "BOOL" in result
        assert "N" not in result

    def test_decimal_maps_to_n(self):
        assert _to_dynamo(Decimal("1.5")) == {"N": "1.5"}

    def test_empty_string_maps_to_s(self):
        assert _to_dynamo("") == {"S": ""}

    def test_zero_int_maps_to_n(self):
        assert _to_dynamo(0) == {"N": "0"}


# ---------------------------------------------------------------------------
# 12. migrate with --dry-run on a real in-memory SQLite file
# ---------------------------------------------------------------------------

class TestMigrateDryRun:
    """Integration-style test: real SQLite, dry_run=True, no DynamoDB calls."""

    def _create_sqlite_db(self, tmp_path) -> str:
        """Create a minimal SQLite database with known data; return SQLAlchemy URL."""
        from sqlalchemy import create_engine, text

        db_path = tmp_path / "test_migrate.db"
        url = f"sqlite:///{db_path}"
        engine = create_engine(url, echo=False)

        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    company_name TEXT,
                    failed_attempts INTEGER DEFAULT 0,
                    locked_until TEXT,
                    created_at TEXT
                )
            """))
            conn.execute(text("""
                CREATE TABLE batches (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_rows INTEGER DEFAULT 0,
                    processed_rows INTEGER DEFAULT 0,
                    error_rows INTEGER DEFAULT 0,
                    uploaded_at TEXT,
                    completed_at TEXT
                )
            """))
            conn.execute(text("""
                CREATE TABLE feedbacks (
                    id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL,
                    original_text TEXT,
                    sentiment TEXT,
                    score REAL,
                    status TEXT,
                    error_reason TEXT,
                    analyzed_at TEXT
                )
            """))
            conn.execute(text("""
                CREATE TABLE keywords (
                    feedback_id TEXT NOT NULL,
                    word TEXT NOT NULL
                )
            """))
            # 2 users
            conn.execute(text(
                "INSERT INTO users VALUES "
                "('u1', 'alpha@test.com', 'placeholder1', 'Alpha', 0, NULL, '2024-01-01')"
            ))
            conn.execute(text(
                "INSERT INTO users VALUES "
                "('u2', 'beta@test.com',  'placeholder2', 'Beta',  0, NULL, '2024-01-02')"
            ))
            # 1 batch
            conn.execute(text(
                "INSERT INTO batches VALUES "
                "('b1', 'u1', 'file.csv', 'completed', 10, 10, 0, '2024-01-01', NULL)"
            ))
            # 2 feedbacks
            conn.execute(text(
                "INSERT INTO feedbacks VALUES "
                "('fb1', 'b1', 'good text', 'positivo', 0.8, 'success', NULL, '2024-01-01')"
            ))
            conn.execute(text(
                "INSERT INTO feedbacks VALUES "
                "('fb2', 'b1', 'bad text', 'negativo', -0.5, 'success', NULL, '2024-01-01')"
            ))
            # 3 keywords
            conn.execute(text("INSERT INTO keywords VALUES ('fb1', 'bueno')"))
            conn.execute(text("INSERT INTO keywords VALUES ('fb1', 'producto')"))
            conn.execute(text("INSERT INTO keywords VALUES ('fb2', 'malo')"))
            conn.commit()

        return url

    def test_no_dynamodb_calls_in_dry_run(self, tmp_path):
        """boto3.client must never be called when dry_run=True."""
        sqlite_url = self._create_sqlite_db(tmp_path)

        with patch("scripts.migrate_sqlite_to_dynamodb.boto3.client") as mock_boto3:
            migrate(
                sqlite_url=sqlite_url,
                table_name="test-table",
                region="us-east-1",
                dry_run=True,
            )
            mock_boto3.assert_not_called()

    def test_summary_contains_dry_run_marker(self, tmp_path, capsys):
        """Summary output must mention DRY RUN."""
        sqlite_url = self._create_sqlite_db(tmp_path)

        with patch("scripts.migrate_sqlite_to_dynamodb.boto3.client"):
            migrate(
                sqlite_url=sqlite_url,
                table_name="test-table",
                region="us-east-1",
                dry_run=True,
            )

        output = capsys.readouterr().out
        assert "DRY RUN" in output or "dry run" in output.lower()

    def test_summary_zero_failures_in_dry_run(self, tmp_path, capsys):
        """In dry-run mode, the summary must show 0 failures for all entities."""
        sqlite_url = self._create_sqlite_db(tmp_path)

        with patch("scripts.migrate_sqlite_to_dynamodb.boto3.client"):
            migrate(
                sqlite_url=sqlite_url,
                table_name="test-table",
                region="us-east-1",
                dry_run=True,
            )

        output = capsys.readouterr().out
        lines = output.splitlines()
        # Check entity summary rows: last numeric token must be 0 (failed column)
        entity_keywords = ("users", "batches", "feedbacks", "keywords")
        for line in lines:
            line_lower = line.lower()
            if any(kw in line_lower for kw in entity_keywords):
                tokens = line.split()
                # Find the last integer token (failed count)
                for token in reversed(tokens):
                    try:
                        failed_count = int(token)
                        assert failed_count == 0, (
                            f"Expected 0 failed in line '{line}', got {failed_count}"
                        )
                        break
                    except ValueError:
                        continue

    def test_summary_read_counts_match_inserted_data(self, tmp_path, capsys):
        """Summary must report: 2 users, 1 batch, 2 feedbacks read."""
        sqlite_url = self._create_sqlite_db(tmp_path)

        with patch("scripts.migrate_sqlite_to_dynamodb.boto3.client"):
            migrate(
                sqlite_url=sqlite_url,
                table_name="test-table",
                region="us-east-1",
                dry_run=True,
            )

        output = capsys.readouterr().out
        lines = output.splitlines()

        def _find_entity_line(name: str) -> str | None:
            for line in lines:
                if name in line.lower():
                    return line
            return None

        users_line = _find_entity_line("users")
        batches_line = _find_entity_line("batches")
        feedbacks_line = _find_entity_line("feedbacks")

        assert users_line is not None, "Expected 'users' row in summary"
        assert batches_line is not None, "Expected 'batches' row in summary"
        assert feedbacks_line is not None, "Expected 'feedbacks' row in summary"

        # First integer in each line should be the 'read' count
        def _first_int(line: str) -> int:
            for token in line.split():
                try:
                    return int(token)
                except ValueError:
                    continue
            raise ValueError(f"No integer found in line: {line!r}")

        assert _first_int(users_line) == 2
        assert _first_int(batches_line) == 1
        assert _first_int(feedbacks_line) == 2
