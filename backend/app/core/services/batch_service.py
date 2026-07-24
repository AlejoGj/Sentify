"""Batch processing service - orchestrates CSV upload and NLP analysis."""

import csv
import io
import logging
from dataclasses import dataclass, field

from app.core.interfaces.nlp_provider import INLPProvider
from app.core.interfaces.storage_provider import IStorageProvider
from app.utils.csv_parser import validate_csv, CSVValidationResult

logger = logging.getLogger(__name__)

MAX_TEXT_LENGTH: int = 5000


@dataclass
class BatchProcessingResult:
    """Result of processing a full CSV batch."""

    batch_id: str
    total_feedbacks: int
    successful: int
    failed: int
    errors: list[dict] = field(default_factory=list)  # [{feedback_index, reason}]


class BatchService:
    """Orchestrates the CSV upload → NLP analysis → storage pipeline.

    Receives INLPProvider and IStorageProvider via dependency injection.
    Handles partial failures: individual row errors don't crash the batch.
    Invariant: processed_rows + error_rows == total_rows after completion.
    """

    def __init__(
        self, nlp_provider: INLPProvider, storage_provider: IStorageProvider
    ) -> None:
        self._nlp = nlp_provider
        self._storage = storage_provider

    def process_batch(
        self, user_id: str, filename: str, file_content: bytes
    ) -> BatchProcessingResult:
        """Process a CSV file upload end-to-end.

        Flow:
        1. Validate CSV format (extension, encoding, columns, size, rows)
        2. Create batch record in storage
        3. Parse rows and extract text from the detected column
        4. For each row: validate text → analyze sentiment → store result
        5. Update batch status and counts

        Args:
            user_id: ID of the authenticated user uploading the file.
            filename: Original filename of the uploaded CSV.
            file_content: Raw bytes of the CSV file.

        Returns:
            BatchProcessingResult with summary of processing outcomes.

        Raises:
            ValueError: If CSV validation fails (invalid format/encoding/columns).
        """
        # Step 1: Validate CSV
        validation: CSVValidationResult = validate_csv(file_content, filename)
        if not validation.valid:
            raise ValueError(
                f"CSV validation failed: {validation.error}"
            )

        # Step 2: Create batch record
        batch_id: str = self._storage.create_batch(user_id, filename)

        try:
            # Update status to processing
            self._storage.update_batch_status(batch_id, "processing")

            # Step 3: Parse rows
            text_column: str = validation.text_column  # type: ignore[assignment]
            encoding: str = validation.encoding  # type: ignore[assignment]
            rows: list[str] = self._parse_csv_texts(
                file_content, encoding, text_column
            )

            total_rows: int = len(rows)
            processed_count: int = 0
            error_count: int = 0
            errors: list[dict] = []

            # Update total rows count
            self._storage.update_batch_counts(
                batch_id, total_rows=total_rows, processed_rows=0, error_rows=0
            )

            # Step 4: Process each row
            for index, text in enumerate(rows):
                try:
                    self._process_single_feedback(
                        batch_id, text, index, errors
                    )
                    # Determine if the row was an error based on errors list growth
                    if len(errors) > error_count:
                        error_count = len(errors)
                    else:
                        processed_count += 1
                except Exception as e:
                    # Unexpected exception during processing — mark as error
                    logger.error(
                        "Unexpected error processing row %d in batch %s: %s",
                        index, batch_id, e
                    )
                    error_count += 1
                    errors.append({
                        "feedback_index": index,
                        "reason": f"unexpected_error: {str(e)}"
                    })
                    # Try to store the error feedback
                    try:
                        self._storage.store_feedback_error(
                            batch_id,
                            text[:MAX_TEXT_LENGTH],
                            f"unexpected_error: {str(e)}"
                        )
                    except Exception as store_err:
                        logger.error(
                            "Failed to store error feedback for row %d: %s",
                            index, store_err
                        )

            # Step 5: Update batch counts and status
            self._storage.update_batch_counts(
                batch_id,
                total_rows=total_rows,
                processed_rows=processed_count,
                error_rows=error_count,
            )
            self._storage.update_batch_status(batch_id, "completed")

            return BatchProcessingResult(
                batch_id=batch_id,
                total_feedbacks=total_rows,
                successful=processed_count,
                failed=error_count,
                errors=errors,
            )

        except Exception as e:
            # Catastrophic failure — mark batch as error
            logger.error(
                "Catastrophic failure processing batch %s: %s", batch_id, e
            )
            try:
                self._storage.update_batch_status(batch_id, "error")
            except Exception as status_err:
                logger.error(
                    "Failed to update batch %s status to error: %s",
                    batch_id, status_err
                )
            raise

    def _process_single_feedback(
        self,
        batch_id: str,
        text: str,
        index: int,
        errors: list[dict],
    ) -> None:
        """Process a single feedback text through NLP and store the result.

        Args:
            batch_id: The batch this feedback belongs to.
            text: The raw text from the CSV row.
            index: Row index for error reporting.
            errors: Mutable list to append errors to.
        """
        # Truncate text to max length
        truncated_text: str = text[:MAX_TEXT_LENGTH]

        # Validate text with NLP provider
        nlp_error = self._nlp.validate_text(truncated_text)
        if nlp_error is not None:
            # NLP validation failed — store as error feedback
            errors.append({
                "feedback_index": index,
                "reason": nlp_error.reason,
            })
            self._storage.store_feedback_error(
                batch_id, truncated_text, nlp_error.reason
            )
            return

        # Analyze sentiment
        result = self._nlp.analyze_sentiment(truncated_text)

        # Store successful feedback
        self._storage.store_feedback(
            batch_id=batch_id,
            text=truncated_text,
            sentiment=result.sentiment,
            score=result.score,
            keywords=result.keywords,
            status="success",
        )

    def _parse_csv_texts(
        self, file_content: bytes, encoding: str, text_column: str
    ) -> list[str]:
        """Parse CSV content and extract all texts from the target column.

        Args:
            file_content: Raw bytes of the CSV file.
            encoding: Detected encoding (utf-8 or latin-1).
            text_column: Name of the column containing feedback text.

        Returns:
            List of text strings from the specified column.
        """
        decoded = file_content.decode(encoding)
        reader = csv.DictReader(io.StringIO(decoded))

        texts: list[str] = []
        for row in reader:
            # Match column name case-insensitively
            cell_value: str | None = None
            for key, value in row.items():
                if key is not None and key.strip().lower() == text_column:
                    cell_value = value
                    break

            # Use the cell value or empty string if missing
            texts.append(cell_value.strip() if cell_value else "")

        return texts
