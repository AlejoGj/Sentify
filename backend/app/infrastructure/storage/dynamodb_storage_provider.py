"""DynamoDB storage provider implementation using single-table design."""

import logging
import math
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import boto3
import botocore.exceptions
from boto3.dynamodb.conditions import Key

from app.core.interfaces.storage_provider import IStorageProvider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Single-table key prefix constants
# ---------------------------------------------------------------------------

# Partition/sort key prefixes
PK_USER = "USER#{}"           # PK and SK: USER#{email}
PK_USERID = "USERID#{}"       # PK and SK: USERID#{user_id} — pointer for ID lookups
PK_USER_ID = "USER#{}"        # PK for batch items: USER#{user_id}
SK_BATCH = "BATCH#{}"         # SK for batch items: BATCH#{batch_id}
PK_BATCH = "BATCH#{}"         # PK for feedback/keyword items: BATCH#{batch_id}
SK_FEEDBACK = "FEEDBACK#{}"   # SK prefix for feedback items: FEEDBACK#{feedback_id}
SK_KW = "KW#{}#FEEDBACK#{}"   # SK for keyword index items: KW#{word}#FEEDBACK#{feedback_id}
SK_KW_PREFIX = "KW#"          # Prefix used in begins_with queries for keywords
SK_BATCH_PREFIX = "BATCH#"    # Prefix used in begins_with queries for batches

# GSI1 — feedbacks sorted by analyzed_at within a batch
GSI1_NAME = "GSI1"
GSI1_PK = "GSI1PK"            # Value: BATCH#{batch_id}
GSI1_SK = "GSI1SK"            # Value: FEEDBACK#{analyzed_at}

# GSI2 — feedbacks by keyword within a batch
GSI2_NAME = "GSI2"
GSI2_PK = "GSI2PK"            # Value: BATCH#{batch_id}#KW#{word}
GSI2_SK = "GSI2SK"            # Value: FEEDBACK#{feedback_id}

# Pointer item type for batch-only updates (stores user_id so we can locate batch)
PK_BATCH_PTR = "BATCH#{}"     # PK and SK: BATCH#{batch_id} — pointer storing user_id
SK_BATCH_PTR = "BATCH#{}"


class DynamoDBStorageProvider(IStorageProvider):
    """Concrete storage implementation using AWS DynamoDB (single-table design)."""

    def __init__(self, table_name: str, region: str) -> None:
        """Initialise the DynamoDB resource and bind to the configured table.

        Args:
            table_name: Name of the DynamoDB table to use for all operations.
            region: AWS region where the table resides (e.g. "us-east-1").
        """
        self._table_name = table_name
        self._region = region
        dynamodb = boto3.resource("dynamodb", region_name=region)
        self._table = dynamodb.Table(table_name)
        logger.info(
            "DynamoDBStorageProvider initialised: table=%s region=%s",
            table_name,
            region,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_id() -> str:
        """Return a new UUID v4 string."""
        return str(uuid.uuid4())

    @staticmethod
    def _utcnow_iso() -> str:
        """Return current UTC time as ISO-8601 string (timezone-aware)."""
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _decimal_to_python(value):
        """Convert DynamoDB Decimal types to native Python int or float."""
        if isinstance(value, Decimal):
            if value == value.to_integral_value():
                return int(value)
            return float(value)
        return value

    def _deserialize_user(self, item: dict) -> dict:
        """Convert a raw DynamoDB user item to the canonical dict format."""
        return {
            "id": item.get("id"),
            "email": item.get("email"),
            "password_hash": item.get("password_hash"),
            "company_name": item.get("company_name"),
            "failed_attempts": self._decimal_to_python(
                item.get("failed_attempts", 0)
            ),
            "locked_until": item.get("locked_until") or None,
            "created_at": item.get("created_at"),
        }

    def _get_email_by_user_id(self, user_id: str) -> Optional[str]:
        """Look up the user's email via the USERID pointer item."""
        pk = PK_USERID.format(user_id)
        response = self._table.get_item(Key={"PK": pk, "SK": pk})
        item = response.get("Item")
        if item is None:
            return None
        return item.get("email")

    def _deserialize_feedback(self, item: dict) -> dict:
        """Convert a raw DynamoDB feedback item to the canonical dict format."""
        score = item.get("score")
        return {
            "id": item.get("id"),
            "batch_id": item.get("batch_id"),
            "original_text": item.get("original_text"),
            "sentiment": item.get("sentiment"),
            "score": self._decimal_to_python(score) if score is not None else None,
            "keywords": list(item.get("keywords", [])),
            "status": item.get("status"),
            "error_reason": item.get("error_reason"),
            "analyzed_at": item.get("analyzed_at"),
        }

    # ------------------------------------------------------------------
    # Internal helpers — batch write with retry
    # ------------------------------------------------------------------

    def _batch_write(self, items: list[dict]) -> None:
        """Write a list of PutRequest items to DynamoDB using batch_write_item.

        Splits *items* into chunks of 25 (DynamoDB limit per request) and
        calls ``batch_write_item`` for each chunk.  When DynamoDB returns
        ``UnprocessedItems``, the unprocessed subset is retried with
        exponential backoff:

        * Attempt 0 -> wait 0.1 s
        * Attempt 1 -> wait 0.2 s
        * Attempt 2 -> wait 0.4 s

        After 3 retry attempts any items that remain unprocessed are
        collected and a ``RuntimeError`` is raised listing the count.

        ``ResourceNotFoundException`` propagates immediately without retrying.

        Args:
            items: List of DynamoDB PutRequest dicts, each of the form
                {"PutRequest": {"Item": {...}}}.

        Raises:
            RuntimeError: If unprocessed items remain after 3 retry attempts.
            botocore.exceptions.ClientError: For non-retryable AWS errors
                (e.g. ResourceNotFoundException).
        """
        _CHUNK_SIZE = 25
        _MAX_RETRIES = 3

        client = self._table.meta.client

        # Split into 25-item chunks
        chunks: list[list[dict]] = [
            items[i: i + _CHUNK_SIZE] for i in range(0, len(items), _CHUNK_SIZE)
        ]

        for chunk in chunks:
            pending: list[dict] = chunk

            for attempt in range(_MAX_RETRIES + 1):
                try:
                    response = client.batch_write_item(
                        RequestItems={self._table_name: pending}
                    )
                except botocore.exceptions.ClientError as exc:
                    code = exc.response["Error"]["Code"]
                    if code == "ResourceNotFoundException":
                        raise
                    raise

                unprocessed = (
                    response.get("UnprocessedItems", {}).get(self._table_name, [])
                )

                if not unprocessed:
                    break  # All items in this chunk succeeded

                if attempt < _MAX_RETRIES:
                    wait = 2 ** attempt * 0.1  # 0.1, 0.2, 0.4 seconds
                    logger.warning(
                        "_batch_write: %d unprocessed items on attempt %d, "
                        "retrying in %.2fs",
                        len(unprocessed),
                        attempt,
                        wait,
                    )
                    time.sleep(wait)
                    pending = unprocessed
                else:
                    raise RuntimeError(
                        f"_batch_write: {len(unprocessed)} items remain unprocessed "
                        f"after {_MAX_RETRIES} retry attempts"
                    )

    def store_feedbacks_batch(
        self, batch_id: str, feedbacks: list[dict]
    ) -> list[str]:
        """Bulk-store multiple feedback items for a batch using batch_write_item.

        For each feedback dict in *feedbacks* the method generates a
        feedback_id, builds the main feedback item and all keyword index
        items, then delegates to _batch_write which handles 25-item chunking
        and retry logic.

        Each feedback dict should contain:
            - text (str): original feedback text (truncated to 5000 chars)
            - sentiment (str): "positivo", "neutro", or "negativo"
            - score (float): polarity score in [-1.0, 1.0]
            - keywords (list[str]): extracted keyword strings
            - status (str): "success" or "error"
            - error_reason (str, optional): only relevant when status="error"

        Args:
            batch_id: The ID of the batch these feedbacks belong to.
            feedbacks: List of feedback dicts as described above.

        Returns:
            List of generated feedback_id strings, one per input feedback,
            in the same order as feedbacks.

        Raises:
            RuntimeError: Propagated from _batch_write if unprocessed items
                remain after all retry attempts.
        """
        now = self._utcnow_iso()
        pk = PK_BATCH.format(batch_id)

        put_requests: list[dict] = []
        feedback_ids: list[str] = []

        for fb in feedbacks:
            feedback_id = self._generate_id()
            feedback_ids.append(feedback_id)

            text = fb.get("text", "")
            truncated_text = text[:5000]
            sentiment = fb.get("sentiment")
            score = fb.get("score")
            keywords: list[str] = fb.get("keywords", [])
            status = fb.get("status", "success")
            error_reason = fb.get("error_reason")

            # Build main feedback item
            main_item: dict = {
                "PK": pk,
                "SK": SK_FEEDBACK.format(feedback_id),
                "id": feedback_id,
                "batch_id": batch_id,
                "original_text": truncated_text,
                "sentiment": sentiment,
                "score": Decimal(str(score)) if score is not None else None,
                "keywords": keywords,
                "status": status,
                "analyzed_at": now,
                # GSI1 -- feedbacks sorted by date within a batch
                GSI1_PK: pk,
                GSI1_SK: "FEEDBACK#{}".format(now),
            }
            if error_reason is not None:
                main_item["error_reason"] = error_reason

            put_requests.append({"PutRequest": {"Item": main_item}})

            # Build keyword index items
            for kw in keywords:
                word = kw.lower().strip()
                if len(word) > 2:
                    kw_sk = SK_KW.format(word, feedback_id)
                    kw_item = {
                        "PK": pk,
                        "SK": kw_sk,
                        "word": word,
                        "feedback_id": feedback_id,
                        # GSI2 -- feedbacks by keyword within a batch
                        GSI2_PK: "{}#KW#{}".format(pk, word),
                        GSI2_SK: SK_FEEDBACK.format(feedback_id),
                    }
                    put_requests.append({"PutRequest": {"Item": kw_item}})

        if put_requests:
            self._batch_write(put_requests)

        logger.debug(
            "store_feedbacks_batch: stored %d feedbacks for batch %s",
            len(feedback_ids),
            batch_id,
        )
        return feedback_ids

    # ------------------------------------------------------------------
    # IStorageProvider — batch operations
    # ------------------------------------------------------------------

    def create_batch(self, user_id: str, filename: str) -> str:
        """Crea un lote. Retorna batch_id.

        Stores batch item with PK=USER#{user_id}, SK=BATCH#{batch_id}.
        Also writes a BATCH_PTR item for batch-only key lookups.
        """
        batch_id = self._generate_id()
        now = self._utcnow_iso()

        pk = PK_USER_ID.format(user_id)
        sk = SK_BATCH.format(batch_id)

        # Primary batch item
        self._table.put_item(
            Item={
                "PK": pk,
                "SK": sk,
                "id": batch_id,
                "user_id": user_id,
                "filename": filename,
                "status": "pending",
                "total_rows": 0,
                "processed_rows": 0,
                "error_rows": 0,
                "uploaded_at": now,
                "completed_at": None,
            }
        )

        # Pointer item: BATCH#{batch_id} -> user_id (for batch-only key lookups)
        ptr_pk = PK_BATCH_PTR.format(batch_id)
        self._table.put_item(
            Item={
                "PK": ptr_pk,
                "SK": ptr_pk,
                "user_id": user_id,
            }
        )

        logger.debug("Created batch %s for user %s", batch_id, user_id)
        return batch_id

    def update_batch_status(self, batch_id: str, status: str) -> None:
        """Actualiza estado del lote.

        When status == "completed", also sets completed_at to UTC ISO-8601.
        Requires resolving user_id via BATCH_PTR item to locate the primary item.
        """
        # Resolve user_id via the pointer item
        ptr_pk = PK_BATCH_PTR.format(batch_id)
        response = self._table.get_item(Key={"PK": ptr_pk, "SK": ptr_pk})
        ptr_item = response.get("Item")
        if ptr_item is None:
            logger.warning(
                "update_batch_status: pointer not found for batch_id %s", batch_id
            )
            return
        user_id = ptr_item["user_id"]

        pk = PK_USER_ID.format(user_id)
        sk = SK_BATCH.format(batch_id)

        if status == "completed":
            now = self._utcnow_iso()
            self._table.update_item(
                Key={"PK": pk, "SK": sk},
                UpdateExpression="SET #s = :status, completed_at = :completed_at",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":status": status,
                    ":completed_at": now,
                },
            )
        else:
            self._table.update_item(
                Key={"PK": pk, "SK": sk},
                UpdateExpression="SET #s = :status",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":status": status},
            )

        logger.debug("Updated batch %s status to %s", batch_id, status)

    def update_batch_counts(
        self,
        batch_id: str,
        total_rows: int,
        processed_rows: int,
        error_rows: int,
    ) -> None:
        """Actualiza los contadores de filas del lote usando ADD atomico.

        Uses atomic ADD expressions on the batch item
        PK=USER#{user_id}, SK=BATCH#{batch_id}.
        """
        # Resolve user_id via the pointer item
        ptr_pk = PK_BATCH_PTR.format(batch_id)
        response = self._table.get_item(Key={"PK": ptr_pk, "SK": ptr_pk})
        ptr_item = response.get("Item")
        if ptr_item is None:
            logger.warning(
                "update_batch_counts: pointer not found for batch_id %s", batch_id
            )
            return
        user_id = ptr_item["user_id"]

        pk = PK_USER_ID.format(user_id)
        sk = SK_BATCH.format(batch_id)

        self._table.update_item(
            Key={"PK": pk, "SK": sk},
            UpdateExpression=(
                "ADD total_rows :t, processed_rows :p, error_rows :e"
            ),
            ExpressionAttributeValues={
                ":t": total_rows,
                ":p": processed_rows,
                ":e": error_rows,
            },
        )

        logger.debug(
            "Updated batch %s counts: +%d total, +%d processed, +%d errors",
            batch_id,
            total_rows,
            processed_rows,
            error_rows,
        )

    def get_user_batches(
        self, user_id: str, page: int, page_size: int = 10
    ) -> dict:
        """Retorna historial de lotes del usuario, paginados y ordenados.

        Queries PK=USER#{user_id} with SK begins_with "BATCH#".
        Orders by uploaded_at descending (nulls last).

        Returns:
            Dict with keys: items, total, page, page_size, total_pages.
        """
        pk = PK_USER_ID.format(user_id)

        response = self._table.query(
            KeyConditionExpression=(
                Key("PK").eq(pk) & Key("SK").begins_with(SK_BATCH_PREFIX)
            )
        )
        all_items = response.get("Items", [])

        # Handle DynamoDB pagination (LastEvaluatedKey) to fetch all results
        while "LastEvaluatedKey" in response:
            response = self._table.query(
                KeyConditionExpression=(
                    Key("PK").eq(pk) & Key("SK").begins_with(SK_BATCH_PREFIX)
                ),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            all_items.extend(response.get("Items", []))

        # Sort by uploaded_at descending (items without uploaded_at sort last)
        def _sort_key(item):
            ts = item.get("uploaded_at")
            return ts if ts is not None else ""

        all_items.sort(key=_sort_key, reverse=True)

        total = len(all_items)
        total_pages = math.ceil(total / page_size) if page_size > 0 else 0
        offset = (page - 1) * page_size
        page_items = all_items[offset: offset + page_size]

        def _deserialize_batch(item: dict) -> dict:
            return {
                "id": item.get("id"),
                "user_id": item.get("user_id"),
                "filename": item.get("filename"),
                "status": item.get("status"),
                "total_rows": self._decimal_to_python(item.get("total_rows", 0)),
                "processed_rows": self._decimal_to_python(
                    item.get("processed_rows", 0)
                ),
                "error_rows": self._decimal_to_python(item.get("error_rows", 0)),
                "uploaded_at": item.get("uploaded_at"),
                "completed_at": item.get("completed_at") or None,
            }

        return {
            "items": [_deserialize_batch(i) for i in page_items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    # ------------------------------------------------------------------
    # IStorageProvider — feedback operations
    # ------------------------------------------------------------------

    def store_feedback(
        self,
        batch_id: str,
        text: str,
        sentiment: str,
        score: float,
        keywords: list[str],
        status: str,
    ) -> str:
        """Almacena un feedback procesado. Retorna feedback_id.

        Writes the main feedback item PK=BATCH#{batch_id}, SK=FEEDBACK#{feedback_id}
        and keyword index items PK=BATCH#{batch_id}, SK=KW#{word}#FEEDBACK#{feedback_id}.
        Sets GSI1PK/GSI1SK for date-sorted queries and GSI2PK/GSI2SK per keyword.
        Truncates original_text to 5000 chars.
        """
        feedback_id = self._generate_id()
        now = self._utcnow_iso()
        truncated_text = text[:5000]

        pk = PK_BATCH.format(batch_id)
        sk = SK_FEEDBACK.format(feedback_id)

        # Main feedback item
        self._table.put_item(
            Item={
                "PK": pk,
                "SK": sk,
                "id": feedback_id,
                "batch_id": batch_id,
                "original_text": truncated_text,
                "sentiment": sentiment,
                "score": Decimal(str(score)),
                "keywords": keywords,
                "status": status,
                "analyzed_at": now,
                # GSI1 attributes: feedbacks sorted by date within a batch
                GSI1_PK: PK_BATCH.format(batch_id),
                GSI1_SK: "FEEDBACK#{}".format(now),
            }
        )

        # Keyword index items: one per keyword
        for kw in keywords:
            word = kw.lower().strip()
            if len(word) > 2:
                kw_sk = SK_KW.format(word, feedback_id)
                self._table.put_item(
                    Item={
                        "PK": pk,
                        "SK": kw_sk,
                        "word": word,
                        "feedback_id": feedback_id,
                        # GSI2 attributes: feedbacks by keyword within a batch
                        GSI2_PK: "{}#KW#{}".format(PK_BATCH.format(batch_id), word),
                        GSI2_SK: SK_FEEDBACK.format(feedback_id),
                    }
                )

        logger.debug(
            "Stored feedback %s for batch %s (status=%s, %d keywords)",
            feedback_id,
            batch_id,
            status,
            len(keywords),
        )
        return feedback_id

    def store_feedback_error(
        self, batch_id: str, text: str, error_reason: str
    ) -> str:
        """Almacena un feedback con error. Retorna feedback_id.

        Stores feedback item with status="error" and the provided error_reason.
        Truncates original_text to 5000 chars.
        """
        feedback_id = self._generate_id()
        now = self._utcnow_iso()
        truncated_text = text[:5000]

        pk = PK_BATCH.format(batch_id)
        sk = SK_FEEDBACK.format(feedback_id)

        self._table.put_item(
            Item={
                "PK": pk,
                "SK": sk,
                "id": feedback_id,
                "batch_id": batch_id,
                "original_text": truncated_text,
                "sentiment": None,
                "score": None,
                "keywords": [],
                "status": "error",
                "error_reason": error_reason,
                "analyzed_at": now,
                # GSI1 attributes so the item is queryable by batch
                GSI1_PK: PK_BATCH.format(batch_id),
                GSI1_SK: "FEEDBACK#{}".format(now),
            }
        )

        logger.debug(
            "Stored error feedback %s for batch %s (reason=%s)",
            feedback_id,
            batch_id,
            error_reason,
        )
        return feedback_id

    def get_batch_feedbacks(
        self, batch_id: str, page: int, page_size: int = 20
    ) -> dict:
        """Retorna todos los feedbacks exitosos de un lote, paginados.

        Queries GSI1 with GSI1PK=BATCH#{batch_id}, filters status="success",
        orders by analyzed_at descending.

        Returns:
            Dict with keys: items, total, page, page_size, total_pages.
        """
        from boto3.dynamodb.conditions import Attr

        gsi1_pk_value = PK_BATCH.format(batch_id)

        # Fetch all items for this batch via GSI1, descending by GSI1SK
        response = self._table.query(
            IndexName=GSI1_NAME,
            KeyConditionExpression=Key(GSI1_PK).eq(gsi1_pk_value),
            ScanIndexForward=False,  # descending by analyzed_at
            FilterExpression=Attr("status").eq("success"),
        )
        all_items = response.get("Items", [])

        # Handle DynamoDB pagination
        while "LastEvaluatedKey" in response:
            response = self._table.query(
                IndexName=GSI1_NAME,
                KeyConditionExpression=Key(GSI1_PK).eq(gsi1_pk_value),
                ScanIndexForward=False,
                FilterExpression=Attr("status").eq("success"),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            all_items.extend(response.get("Items", []))

        total = len(all_items)
        total_pages = math.ceil(total / page_size) if page_size > 0 else 0
        offset = (page - 1) * page_size
        page_items = all_items[offset: offset + page_size]

        return {
            "items": [self._deserialize_feedback(i) for i in page_items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def get_urgent_feedbacks(
        self, batch_id: str, threshold: float, page: int, page_size: int = 10
    ) -> dict:
        """Retorna feedbacks con score menor al threshold, paginados.

        Queries GSI1, filters score < threshold AND status="success",
        orders by score ascending.

        Returns:
            Dict with keys: items, total, page, page_size, total_pages.
        """
        from boto3.dynamodb.conditions import Attr

        gsi1_pk_value = PK_BATCH.format(batch_id)

        # Fetch all success items for this batch via GSI1
        response = self._table.query(
            IndexName=GSI1_NAME,
            KeyConditionExpression=Key(GSI1_PK).eq(gsi1_pk_value),
            FilterExpression=Attr("status").eq("success"),
        )
        all_items = response.get("Items", [])

        # Handle DynamoDB pagination
        while "LastEvaluatedKey" in response:
            response = self._table.query(
                IndexName=GSI1_NAME,
                KeyConditionExpression=Key(GSI1_PK).eq(gsi1_pk_value),
                FilterExpression=Attr("status").eq("success"),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            all_items.extend(response.get("Items", []))

        # Filter by score < threshold (score stored as Decimal; compare as float)
        urgent_items = [
            i for i in all_items
            if i.get("score") is not None
            and float(self._decimal_to_python(i["score"])) < threshold
        ]

        # Sort by score ascending in-memory
        urgent_items.sort(key=lambda i: float(self._decimal_to_python(i["score"])))

        total = len(urgent_items)
        total_pages = math.ceil(total / page_size) if page_size > 0 else 0
        offset = (page - 1) * page_size
        page_items = urgent_items[offset: offset + page_size]

        return {
            "items": [self._deserialize_feedback(i) for i in page_items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def get_batch_summary(self, batch_id: str) -> dict:
        """Retorna resumen con distribucion de sentimientos y urgent_count.

        Loads all feedback items for the batch and computes in-memory:
        sentiment distribution counts/percentages and urgent_count (score < -0.7).

        Returns:
            Dict with keys: batch_id, total_feedbacks, sentiment_distribution,
            sentiment_percentages, urgent_count.
        """
        gsi1_pk_value = PK_BATCH.format(batch_id)

        # Fetch all items via GSI1 (includes both success and error items)
        response = self._table.query(
            IndexName=GSI1_NAME,
            KeyConditionExpression=Key(GSI1_PK).eq(gsi1_pk_value),
        )
        all_items = response.get("Items", [])

        while "LastEvaluatedKey" in response:
            response = self._table.query(
                IndexName=GSI1_NAME,
                KeyConditionExpression=Key(GSI1_PK).eq(gsi1_pk_value),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            all_items.extend(response.get("Items", []))

        total = len(all_items)
        positivo = sum(1 for i in all_items if i.get("sentiment") == "positivo")
        neutro = sum(1 for i in all_items if i.get("sentiment") == "neutro")
        negativo = sum(1 for i in all_items if i.get("sentiment") == "negativo")

        sentiment_distribution = {
            "positivo": positivo,
            "neutro": neutro,
            "negativo": negativo,
        }

        if total > 0:
            sentiment_percentages = {
                "positivo": round((positivo / total) * 100, 2),
                "neutro": round((neutro / total) * 100, 2),
                "negativo": round((negativo / total) * 100, 2),
            }
        else:
            sentiment_percentages = {"positivo": 0.0, "neutro": 0.0, "negativo": 0.0}

        urgent_count = sum(
            1
            for i in all_items
            if i.get("score") is not None
            and float(self._decimal_to_python(i["score"])) < -0.7
        )

        return {
            "batch_id": batch_id,
            "total_feedbacks": total,
            "sentiment_distribution": sentiment_distribution,
            "sentiment_percentages": sentiment_percentages,
            "urgent_count": urgent_count,
        }

    # ------------------------------------------------------------------
    # IStorageProvider — keyword operations
    # ------------------------------------------------------------------

    def get_top_keywords(self, batch_id: str, limit: int = 20) -> list[dict]:
        """Retorna las top N palabras clave con frecuencia.

        Queries PK=BATCH#{batch_id} with SK begins_with "KW#", aggregates
        keyword frequencies in-memory, returns sorted descending.

        Returns:
            List of dicts with keys: word, frequency.
        """
        pk = PK_BATCH.format(batch_id)

        # Fetch all keyword index items for this batch
        response = self._table.query(
            KeyConditionExpression=(
                Key("PK").eq(pk) & Key("SK").begins_with(SK_KW_PREFIX)
            )
        )
        all_items = response.get("Items", [])

        # Handle DynamoDB pagination
        while "LastEvaluatedKey" in response:
            response = self._table.query(
                KeyConditionExpression=(
                    Key("PK").eq(pk) & Key("SK").begins_with(SK_KW_PREFIX)
                ),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            all_items.extend(response.get("Items", []))

        # Aggregate: count distinct feedbacks per word
        # Each keyword index item represents one (word, feedback_id) association
        freq: dict[str, int] = {}
        for item in all_items:
            word = item.get("word")
            if word:
                freq[word] = freq.get(word, 0) + 1

        # Sort by frequency descending, apply limit
        sorted_keywords = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        limited = sorted_keywords[:limit]

        logger.debug(
            "get_top_keywords batch=%s: %d unique words, returning top %d",
            batch_id,
            len(freq),
            len(limited),
        )
        return [{"word": w, "frequency": f} for w, f in limited]

    def get_feedbacks_by_keyword(
        self, batch_id: str, keyword: str, page: int, page_size: int = 20
    ) -> dict:
        """Retorna feedbacks asociados a una palabra clave, paginados.

        Queries GSI2 with GSI2PK=BATCH#{batch_id}#KW#{keyword}, extracts
        feedback_ids, fetches each feedback item, paginates in-memory.

        Returns:
            Dict with keys: items, total, page, page_size, total_pages.
        """
        keyword_lower = keyword.lower().strip()
        gsi2_pk_value = "{}#KW#{}".format(PK_BATCH.format(batch_id), keyword_lower)

        # Query GSI2 to get all keyword index items for this batch+keyword
        response = self._table.query(
            IndexName=GSI2_NAME,
            KeyConditionExpression=Key(GSI2_PK).eq(gsi2_pk_value),
        )
        kw_items = response.get("Items", [])

        # Handle DynamoDB pagination
        while "LastEvaluatedKey" in response:
            response = self._table.query(
                IndexName=GSI2_NAME,
                KeyConditionExpression=Key(GSI2_PK).eq(gsi2_pk_value),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            kw_items.extend(response.get("Items", []))

        # Extract feedback_ids (preserve order; deduplicate just in case)
        seen: set[str] = set()
        feedback_ids: list[str] = []
        for item in kw_items:
            fid = item.get("feedback_id")
            if fid and fid not in seen:
                seen.add(fid)
                feedback_ids.append(fid)

        total = len(feedback_ids)
        total_pages = math.ceil(total / page_size) if page_size > 0 else 0
        offset = (page - 1) * page_size
        page_feedback_ids = feedback_ids[offset: offset + page_size]

        # Fetch each feedback item individually
        pk = PK_BATCH.format(batch_id)
        items: list[dict] = []
        for fid in page_feedback_ids:
            sk = SK_FEEDBACK.format(fid)
            fb_response = self._table.get_item(Key={"PK": pk, "SK": sk})
            fb_item = fb_response.get("Item")
            if fb_item is not None:
                items.append(self._deserialize_feedback(fb_item))

        logger.debug(
            "get_feedbacks_by_keyword batch=%s keyword=%s: %d total, page %d/%d",
            batch_id,
            keyword_lower,
            total,
            page,
            total_pages,
        )
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    # ------------------------------------------------------------------
    # IStorageProvider — user operations
    # ------------------------------------------------------------------

    def create_user(
        self, email: str, password_hash: str, company_name: str
    ) -> str:
        """Crea un usuario. Retorna user_id.

        Writes PK=USER#{email}, SK=USER#{email} item with all fields.
        Also writes USERID#{user_id} pointer item containing email.
        Uses conditional put to prevent duplicate emails;
        raises ValueError("duplicate email") on ConditionalCheckFailedException.
        """
        user_id = self._generate_id()
        now = self._utcnow_iso()

        pk = PK_USER.format(email)
        pk_userid = PK_USERID.format(user_id)

        # Primary user item: conditional put to prevent duplicate emails
        try:
            self._table.put_item(
                Item={
                    "PK": pk,
                    "SK": pk,
                    "id": user_id,
                    "email": email,
                    "password_hash": password_hash,
                    "company_name": company_name,
                    "failed_attempts": 0,
                    "locked_until": None,
                    "created_at": now,
                },
                ConditionExpression="attribute_not_exists(PK)",
            )
        except botocore.exceptions.ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code == "ConditionalCheckFailedException":
                raise ValueError("duplicate email") from exc
            raise

        # Pointer item: USERID#{user_id} -> email (for ID-based lookups)
        self._table.put_item(
            Item={
                "PK": pk_userid,
                "SK": pk_userid,
                "email": email,
            }
        )

        logger.debug("Created user %s with email %s", user_id, email)
        return user_id

    def get_user_by_email(self, email: str) -> Optional[dict]:
        """Busca usuario por email. Retorna None si no existe.

        Gets item PK=USER#{email}, SK=USER#{email}.

        Returns:
            Dict with keys: id, email, password_hash, company_name,
            failed_attempts, locked_until, created_at -- or None.
        """
        pk = PK_USER.format(email)
        response = self._table.get_item(Key={"PK": pk, "SK": pk})
        item = response.get("Item")
        if item is None:
            return None
        return self._deserialize_user(item)

    def increment_failed_attempts(self, user_id: str) -> int:
        """Incrementa intentos fallidos. Retorna total actual.

        Resolves email via USERID pointer, then applies atomic ADD 1
        to failed_attempts on USER#{email} item.
        """
        email = self._get_email_by_user_id(user_id)
        if email is None:
            logger.warning(
                "increment_failed_attempts: user_id %s not found", user_id
            )
            return 0

        pk = PK_USER.format(email)
        response = self._table.update_item(
            Key={"PK": pk, "SK": pk},
            UpdateExpression="ADD failed_attempts :inc",
            ExpressionAttributeValues={":inc": 1},
            ReturnValues="UPDATED_NEW",
        )
        new_value = response["Attributes"].get("failed_attempts", 0)
        return self._decimal_to_python(new_value)

    def reset_failed_attempts(self, user_id: str) -> None:
        """Resetea intentos fallidos a 0.

        Resolves email via USERID pointer, then sets failed_attempts=0
        on USER#{email} item.
        """
        email = self._get_email_by_user_id(user_id)
        if email is None:
            logger.warning(
                "reset_failed_attempts: user_id %s not found", user_id
            )
            return

        pk = PK_USER.format(email)
        self._table.update_item(
            Key={"PK": pk, "SK": pk},
            UpdateExpression="SET failed_attempts = :zero",
            ExpressionAttributeValues={":zero": 0},
        )

    def lock_account(self, user_id: str, until: datetime) -> None:
        """Bloquea cuenta hasta la fecha indicada.

        Resolves email via USERID pointer, then sets locked_until
        as UTC ISO-8601 string on USER#{email} item.
        """
        email = self._get_email_by_user_id(user_id)
        if email is None:
            logger.warning("lock_account: user_id %s not found", user_id)
            return

        pk = PK_USER.format(email)
        # Ensure the datetime is stored as a UTC ISO-8601 string
        if hasattr(until, "isoformat"):
            locked_until_str = until.isoformat()
        else:
            locked_until_str = str(until)

        self._table.update_item(
            Key={"PK": pk, "SK": pk},
            UpdateExpression="SET locked_until = :until",
            ExpressionAttributeValues={":until": locked_until_str},
        )
