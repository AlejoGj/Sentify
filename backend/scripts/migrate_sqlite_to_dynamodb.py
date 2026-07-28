"""SQLite to DynamoDB migration script.

Reads all data from an existing Sentify SQLite database and writes it to a
DynamoDB table using the single-table design schema.

Usage:
    python scripts/migrate_sqlite_to_dynamodb.py \\
        --sqlite-url sqlite:///./sentify.db \\
        --table-name <TABLE_NAME> \\
        --region <AWS_REGION> \\
        [--dry-run]

Validates: Requirements 9.1, 9.2
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from decimal import Decimal
from typing import Any

import boto3
import botocore.exceptions
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DynamoDB single-table key patterns (mirrors dynamodb_storage_provider.py)
# ---------------------------------------------------------------------------

PK_USER = "USER#{}"           # USER#{email}
PK_USERID = "USERID#{}"       # USERID#{user_id}
PK_USER_BATCH = "USER#{}"     # USER#{user_id}  (batch item PK)
SK_BATCH = "BATCH#{}"         # BATCH#{batch_id}
PK_BATCH = "BATCH#{}"         # BATCH#{batch_id}
SK_FEEDBACK = "FEEDBACK#{}"   # FEEDBACK#{feedback_id}
SK_KW = "KW#{}#FEEDBACK#{}"   # KW#{word}#FEEDBACK#{feedback_id}

GSI1_PK = "GSI1PK"
GSI1_SK = "GSI1SK"
GSI2_PK = "GSI2PK"
GSI2_SK = "GSI2SK"

# ---------------------------------------------------------------------------
# DynamoDB low-level format helpers
# ---------------------------------------------------------------------------


def _to_dynamo(value: Any) -> dict:
    """Convert a Python value to DynamoDB low-level attribute format."""
    if value is None:
        return {"NULL": True}
    if isinstance(value, bool):
        return {"BOOL": value}
    if isinstance(value, int):
        return {"N": str(value)}
    if isinstance(value, float):
        return {"N": str(Decimal(str(value)))}
    if isinstance(value, Decimal):
        return {"N": str(value)}
    if isinstance(value, str):
        return {"S": value}
    if isinstance(value, list):
        return {"L": [_to_dynamo(item) for item in value]}
    if isinstance(value, dict):
        return {"M": {k: _to_dynamo(v) for k, v in value.items()}}
    # Fallback: coerce to string
    return {"S": str(value)}


def _build_put_request(item: dict[str, Any]) -> dict:
    """Wrap a plain dict into a DynamoDB low-level PutRequest."""
    dynamo_item = {k: _to_dynamo(v) for k, v in item.items()}
    return {"PutRequest": {"Item": dynamo_item}}


# ---------------------------------------------------------------------------
# Batch writer with exponential backoff (Req 9.2 — 5 retries, 2^n * 0.5s)
# ---------------------------------------------------------------------------

_CHUNK_SIZE = 25
_MAX_RETRIES = 5
_BACKOFF_BASE = 0.5  # seconds


def _batch_write_with_retry(
    client: Any,
    table_name: str,
    put_requests: list[dict],
    dry_run: bool = False,
) -> tuple[int, int]:
    """Write put_requests to DynamoDB in chunks of 25 with exponential backoff.

    Returns:
        Tuple of (written_count, failed_count).

    Raises:
        botocore.exceptions.ClientError: For ResourceNotFoundException (abort).
    """
    if dry_run:
        return len(put_requests), 0

    chunks: list[list[dict]] = [
        put_requests[i: i + _CHUNK_SIZE]
        for i in range(0, len(put_requests), _CHUNK_SIZE)
    ]

    written = 0
    failed = 0

    for chunk in chunks:
        pending = chunk

        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = client.batch_write_item(
                    RequestItems={table_name: pending}
                )
            except botocore.exceptions.ClientError as exc:
                code = exc.response["Error"]["Code"]
                if code == "ResourceNotFoundException":
                    logger.error(
                        "DynamoDB table '%s' not found. Aborting.", table_name
                    )
                    raise
                raise

            unprocessed = (
                response.get("UnprocessedItems", {}).get(table_name, [])
            )

            succeeded_this_pass = len(pending) - len(unprocessed)
            written += succeeded_this_pass

            if not unprocessed:
                break

            if attempt < _MAX_RETRIES:
                wait = (2 ** attempt) * _BACKOFF_BASE
                logger.warning(
                    "Batch write: %d unprocessed items on attempt %d/%d, "
                    "retrying in %.2fs",
                    len(unprocessed),
                    attempt + 1,
                    _MAX_RETRIES,
                    wait,
                )
                time.sleep(wait)
                pending = unprocessed
            else:
                # Retries exhausted — record failures
                failed += len(unprocessed)
                logger.warning(
                    "Batch write: %d items remain unprocessed after %d retries.",
                    len(unprocessed),
                    _MAX_RETRIES,
                )
                break

    return written, failed


# ---------------------------------------------------------------------------
# SQLite readers
# ---------------------------------------------------------------------------


def _read_users(session: Session) -> list[dict]:
    """Read all rows from the users table."""
    rows = session.execute(text(
        "SELECT id, email, password_hash, company_name, "
        "failed_attempts, locked_until, created_at FROM users"
    )).fetchall()
    result = []
    for row in rows:
        result.append({
            "id": row[0],
            "email": row[1],
            "password_hash": row[2],
            "company_name": row[3],
            "failed_attempts": row[4],
            "locked_until": row[5],
            "created_at": row[6],
        })
    return result


def _read_batches(session: Session) -> list[dict]:
    """Read all rows from the batches table."""
    rows = session.execute(text(
        "SELECT id, user_id, filename, status, total_rows, processed_rows, "
        "error_rows, uploaded_at, completed_at FROM batches"
    )).fetchall()
    result = []
    for row in rows:
        result.append({
            "id": row[0],
            "user_id": row[1],
            "filename": row[2],
            "status": row[3],
            "total_rows": row[4],
            "processed_rows": row[5],
            "error_rows": row[6],
            "uploaded_at": row[7],
            "completed_at": row[8],
        })
    return result


def _read_feedbacks(session: Session) -> list[dict]:
    """Read all rows from the feedbacks table."""
    rows = session.execute(text(
        "SELECT id, batch_id, original_text, sentiment, score, status, "
        "error_reason, analyzed_at FROM feedbacks"
    )).fetchall()
    result = []
    for row in rows:
        result.append({
            "id": row[0],
            "batch_id": row[1],
            "original_text": row[2],
            "sentiment": row[3],
            "score": row[4],
            "status": row[5],
            "error_reason": row[6],
            "analyzed_at": row[7],
        })
    return result


def _read_keywords_by_feedback(session: Session) -> dict[str, list[str]]:
    """Read all keywords grouped by feedback_id."""
    rows = session.execute(text(
        "SELECT feedback_id, word FROM keywords"
    )).fetchall()
    mapping: dict[str, list[str]] = {}
    for feedback_id, word in rows:
        mapping.setdefault(feedback_id, []).append(word)
    return mapping


# ---------------------------------------------------------------------------
# Record transformers  ->  DynamoDB low-level PutRequest items
# ---------------------------------------------------------------------------


def _datetime_str(value: Any) -> str | None:
    """Convert a SQLite datetime value to an ISO-8601 string, or None."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _transform_user(user: dict) -> list[dict]:
    """Return PutRequest items for a user record (main item + USERID pointer)."""
    email = user["email"]
    user_id = user["id"]

    pk_email = PK_USER.format(email)
    pk_userid = PK_USERID.format(user_id)

    main: dict[str, Any] = {
        "PK": pk_email,
        "SK": pk_email,
        "id": user_id,
        "email": email,
        "password_hash": user["password_hash"],
        "company_name": user["company_name"],
        "failed_attempts": user["failed_attempts"] if user["failed_attempts"] is not None else 0,
        "created_at": _datetime_str(user["created_at"]),
    }
    locked_until = _datetime_str(user["locked_until"])
    if locked_until is not None:
        main["locked_until"] = locked_until

    pointer: dict[str, Any] = {
        "PK": pk_userid,
        "SK": pk_userid,
        "email": email,
    }

    return [_build_put_request(main), _build_put_request(pointer)]


def _transform_batch(batch: dict) -> list[dict]:
    """Return PutRequest items for a batch record (main item + BATCH pointer)."""
    batch_id = batch["id"]
    user_id = batch["user_id"]

    pk_main = PK_USER_BATCH.format(user_id)
    sk_main = SK_BATCH.format(batch_id)
    pk_ptr = PK_BATCH.format(batch_id)

    main: dict[str, Any] = {
        "PK": pk_main,
        "SK": sk_main,
        "id": batch_id,
        "user_id": user_id,
        "filename": batch["filename"],
        "status": batch["status"],
        "total_rows": batch["total_rows"] if batch["total_rows"] is not None else 0,
        "processed_rows": batch["processed_rows"] if batch["processed_rows"] is not None else 0,
        "error_rows": batch["error_rows"] if batch["error_rows"] is not None else 0,
        "uploaded_at": _datetime_str(batch["uploaded_at"]),
    }
    completed_at = _datetime_str(batch["completed_at"])
    if completed_at is not None:
        main["completed_at"] = completed_at

    pointer: dict[str, Any] = {
        "PK": pk_ptr,
        "SK": pk_ptr,
        "user_id": user_id,
    }

    return [_build_put_request(main), _build_put_request(pointer)]


def _transform_feedback(
    feedback: dict, keywords: list[str]
) -> list[dict]:
    """Return PutRequest items for a feedback + its keyword index items."""
    feedback_id = feedback["id"]
    batch_id = feedback["batch_id"]

    pk = PK_BATCH.format(batch_id)
    sk = SK_FEEDBACK.format(feedback_id)
    analyzed_at = _datetime_str(feedback["analyzed_at"])

    main: dict[str, Any] = {
        "PK": pk,
        "SK": sk,
        "id": feedback_id,
        "batch_id": batch_id,
        "original_text": feedback["original_text"][:5000],
        "status": feedback["status"],
        "keywords": keywords,
        # GSI1 attributes for date-sorted queries
        GSI1_PK: pk,
        GSI1_SK: "FEEDBACK#{}".format(analyzed_at or ""),
    }

    if feedback["sentiment"] is not None:
        main["sentiment"] = feedback["sentiment"]
    if feedback["score"] is not None:
        main["score"] = Decimal(str(feedback["score"]))
    if feedback["error_reason"] is not None:
        main["error_reason"] = feedback["error_reason"]
    if analyzed_at is not None:
        main["analyzed_at"] = analyzed_at

    put_requests = [_build_put_request(main)]

    # One keyword index item per keyword word
    for word in keywords:
        kw_sk = SK_KW.format(word, feedback_id)
        kw_item: dict[str, Any] = {
            "PK": pk,
            "SK": kw_sk,
            "word": word,
            "feedback_id": feedback_id,
            GSI2_PK: "{}#KW#{}".format(pk, word),
            GSI2_SK: SK_FEEDBACK.format(feedback_id),
        }
        put_requests.append(_build_put_request(kw_item))

    return put_requests


# ---------------------------------------------------------------------------
# DynamoDB count helpers for summary report (Req 9.6)
# ---------------------------------------------------------------------------


def _count_dynamo_by_sk_prefix(
    client: Any, table_name: str, sk_prefix: str
) -> int:
    """Count items in DynamoDB whose SK starts with the given prefix."""
    count = 0
    kwargs: dict = {
        "TableName": table_name,
        "Select": "COUNT",
        "FilterExpression": "begins_with(SK, :prefix)",
        "ExpressionAttributeValues": {":prefix": {"S": sk_prefix}},
    }
    while True:
        response = client.scan(**kwargs)
        count += response.get("Count", 0)
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        kwargs["ExclusiveStartKey"] = last_key
    return count


def _get_dynamo_entity_counts(
    client: Any, table_name: str, dry_run: bool
) -> dict[str, int]:
    """Return per-entity item counts from DynamoDB. Returns zeros in dry-run."""
    if dry_run:
        return {"users": 0, "batches": 0, "feedbacks": 0, "keywords": 0}

    logger.info("Querying DynamoDB for post-migration record counts...")
    return {
        # USER#{email} items have SK starting with "USER#"
        "users": _count_dynamo_by_sk_prefix(client, table_name, "USER#"),
        # BATCH#{batch_id} items (main batch items) have SK starting with "BATCH#"
        "batches": _count_dynamo_by_sk_prefix(client, table_name, "BATCH#"),
        # Feedback items have SK starting with "FEEDBACK#"
        "feedbacks": _count_dynamo_by_sk_prefix(client, table_name, "FEEDBACK#"),
        # Keyword index items have SK starting with "KW#"
        "keywords": _count_dynamo_by_sk_prefix(client, table_name, "KW#"),
    }


# ---------------------------------------------------------------------------
# Main migration logic
# ---------------------------------------------------------------------------


def migrate(
    sqlite_url: str,
    table_name: str,
    region: str,
    dry_run: bool,
) -> None:
    """Execute the full SQLite -> DynamoDB migration."""

    # ---- 1. Connect to SQLite ----
    logger.info("Connecting to SQLite: %s", sqlite_url)
    try:
        engine = create_engine(sqlite_url, echo=False)
        SessionFactory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        session = SessionFactory()
    except Exception as exc:
        logger.error("Failed to connect to SQLite: %s", exc)
        sys.exit(1)

    # ---- 2. Read all entities in order ----
    logger.info("Reading data from SQLite...")
    try:
        users = _read_users(session)
        logger.info("  Users:     %d", len(users))
        batches = _read_batches(session)
        logger.info("  Batches:   %d", len(batches))
        feedbacks = _read_feedbacks(session)
        logger.info("  Feedbacks: %d", len(feedbacks))
        keywords_by_feedback = _read_keywords_by_feedback(session)
        total_kw = sum(len(v) for v in keywords_by_feedback.values())
        logger.info("  Keywords:  %d", total_kw)
    except Exception as exc:
        logger.error("SQLite read error -- aborting migration: %s", exc)
        session.close()
        sys.exit(1)
    finally:
        session.close()

    # ---- 3. Verify DynamoDB table exists ----
    if not dry_run:
        try:
            dynamo_client = boto3.client("dynamodb", region_name=region)
            dynamo_client.describe_table(TableName=table_name)
            logger.info(
                "DynamoDB table '%s' found in region '%s'.", table_name, region
            )
        except botocore.exceptions.ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("ResourceNotFoundException", "TableNotFoundException"):
                logger.error(
                    "DynamoDB table '%s' not found in region '%s'. Aborting.",
                    table_name,
                    region,
                )
                sys.exit(1)
            raise
    else:
        dynamo_client = None
        logger.info("[DRY RUN] Skipping DynamoDB connection — no writes will occur.")

    # Counters per entity type
    counts: dict[str, dict[str, int]] = {
        "users":     {"read": len(users),     "written": 0, "failed": 0},
        "batches":   {"read": len(batches),   "written": 0, "failed": 0},
        "feedbacks": {"read": len(feedbacks), "written": 0, "failed": 0},
        "keywords":  {"read": total_kw,       "written": 0, "failed": 0},
    }


    # ---- 4a. Migrate users ----
    logger.info("Migrating %d users...", len(users))
    for user in users:
        record_id = user.get("id", "<unknown>")
        try:
            put_requests = _transform_user(user)
        except Exception as exc:
            logger.error("TRANSFORM FAILED [user id=%s]: %s", record_id, exc)
            counts["users"]["failed"] += 1
            continue

        if dry_run:
            counts["users"]["written"] += 1
            continue

        try:
            _written, failed = _batch_write_with_retry(
                dynamo_client, table_name, put_requests
            )
            if failed == 0:
                counts["users"]["written"] += 1
            else:
                counts["users"]["failed"] += 1
                logger.error(
                    "WRITE FAILED [user id=%s]: %d item(s) unprocessed after retries",
                    record_id, failed,
                )
        except botocore.exceptions.ClientError:
            sys.exit(1)

    # ---- 4b. Migrate batches ----
    logger.info("Migrating %d batches...", len(batches))
    for batch in batches:
        record_id = batch.get("id", "<unknown>")
        try:
            put_requests = _transform_batch(batch)
        except Exception as exc:
            logger.error("TRANSFORM FAILED [batch id=%s]: %s", record_id, exc)
            counts["batches"]["failed"] += 1
            continue

        if dry_run:
            counts["batches"]["written"] += 1
            continue

        try:
            _written, failed = _batch_write_with_retry(
                dynamo_client, table_name, put_requests
            )
            if failed == 0:
                counts["batches"]["written"] += 1
            else:
                counts["batches"]["failed"] += 1
                logger.error(
                    "WRITE FAILED [batch id=%s]: %d item(s) unprocessed after retries",
                    record_id, failed,
                )
        except botocore.exceptions.ClientError:
            sys.exit(1)


    # ---- 4c. Migrate feedbacks (including keyword index items) ----
    logger.info("Migrating %d feedbacks...", len(feedbacks))
    for feedback in feedbacks:
        record_id = feedback.get("id", "<unknown>")
        fb_keywords = keywords_by_feedback.get(record_id, [])

        try:
            put_requests = _transform_feedback(feedback, fb_keywords)
        except Exception as exc:
            logger.error("TRANSFORM FAILED [feedback id=%s]: %s", record_id, exc)
            counts["feedbacks"]["failed"] += 1
            continue

        # First item is the feedback itself; remaining are keyword index items
        kw_item_count = len(put_requests) - 1

        if dry_run:
            counts["feedbacks"]["written"] += 1
            counts["keywords"]["written"] += kw_item_count
            continue

        try:
            _written, failed = _batch_write_with_retry(
                dynamo_client, table_name, put_requests
            )
            if failed == 0:
                counts["feedbacks"]["written"] += 1
                counts["keywords"]["written"] += kw_item_count
            else:
                counts["feedbacks"]["failed"] += 1
                logger.error(
                    "WRITE FAILED [feedback id=%s]: %d item(s) unprocessed after retries",
                    record_id, failed,
                )
        except botocore.exceptions.ClientError:
            sys.exit(1)

    # ---- 5. Print summary report (Req 9.5, 9.6) ----
    _print_summary(counts, dynamo_client, table_name, dry_run)


def _print_summary(
    counts: dict[str, dict[str, int]],
    dynamo_client: Any,
    table_name: str,
    dry_run: bool,
) -> None:
    """Print migration summary and DynamoDB vs SQLite comparison."""
    print("\n" + "=" * 60)
    print("MIGRATION SUMMARY REPORT")
    if dry_run:
        print("(DRY RUN -- no data was written to DynamoDB)")
    print("=" * 60)

    header = f"{'Entity':<12} {'Read':>8} {'Written':>10} {'Failed':>8}"
    print(header)
    print("-" * len(header))

    for entity, c in counts.items():
        print(f"{entity:<12} {c['read']:>8} {c['written']:>10} {c['failed']:>8}")

    total_read = sum(c["read"] for c in counts.values())
    total_written = sum(c["written"] for c in counts.values())
    total_failed = sum(c["failed"] for c in counts.values())
    print("-" * len(header))
    print(f"{'TOTAL':<12} {total_read:>8} {total_written:>10} {total_failed:>8}")

    if not dry_run and dynamo_client is not None:
        print()
        print("DynamoDB vs SQLite record comparison:")
        dynamo_counts = _get_dynamo_entity_counts(dynamo_client, table_name, dry_run)
        print(f"  {'Entity':<12} {'SQLite':>8} {'DynamoDB':>10} {'Match?':>8}")
        print(f"  {'-' * 42}")
        for entity in ("users", "batches", "feedbacks", "keywords"):
            sqlite_n = counts[entity]["read"]
            dynamo_n = dynamo_counts.get(entity, 0)
            match = "OK" if dynamo_n >= sqlite_n else "MISMATCH"
            print(f"  {entity:<12} {sqlite_n:>8} {dynamo_n:>10} {match:>8}")
            if match == "MISMATCH":
                logger.warning(
                    "Count mismatch for %s: SQLite=%d DynamoDB=%d",
                    entity, sqlite_n, dynamo_n,
                )
    elif dry_run:
        print("\n[DRY RUN] DynamoDB comparison skipped.")

    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate Sentify SQLite data to DynamoDB single-table schema."
    )
    parser.add_argument(
        "--sqlite-url",
        default="sqlite:///./sentify.db",
        help="SQLAlchemy URL for the source SQLite database "
             "(default: sqlite:///./sentify.db)",
    )
    parser.add_argument(
        "--table-name",
        default="",
        help="Target DynamoDB table name.",
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region for the DynamoDB table (default: us-east-1).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Read and transform records but skip all DynamoDB writes.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    if not args.dry_run and not args.table_name:
        logger.error("--table-name is required unless --dry-run is specified.")
        sys.exit(1)

    migrate(
        sqlite_url=args.sqlite_url,
        table_name=args.table_name,
        region=args.region,
        dry_run=args.dry_run,
    )
