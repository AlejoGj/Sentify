"""CSV validation and parsing logic."""

import csv
import io
from dataclasses import dataclass


@dataclass
class CSVValidationResult:
    """Result of CSV file validation."""

    valid: bool
    text_column: str | None = None  # Nombre de la columna de texto detectada
    encoding: str | None = None  # UTF-8 o Latin-1
    row_count: int = 0
    error: str | None = None  # Motivo de rechazo si inválido


# Recognized text column headers (case-insensitive matching)
RECOGNIZED_COLUMNS: set[str] = {"texto", "comentario", "review", "comment", "feedback"}

# Constraints
MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10 MB
MAX_ROWS: int = 50_000

# Error codes (matching design ErrorCodes class)
CSV_INVALID_EXTENSION = "csv_invalid_extension"
CSV_INVALID_ENCODING = "csv_invalid_encoding"
CSV_NO_TEXT_COLUMN = "csv_no_text_column"
CSV_SIZE_EXCEEDED = "csv_size_exceeded"
CSV_ROW_LIMIT_EXCEEDED = "csv_row_limit_exceeded"


def validate_csv(file_content: bytes, filename: str) -> CSVValidationResult:
    """Valida un archivo CSV según las reglas de negocio.

    Validation order:
    1. Extension check (.csv)
    2. File size (≤ 10 MB)
    3. Encoding detection (UTF-8 first, then Latin-1)
    4. Parse CSV headers and detect text column
    5. Row count (≤ 50,000)

    Args:
        file_content: Raw bytes of the uploaded file.
        filename: Original filename including extension.

    Returns:
        CSVValidationResult with validation outcome.
    """
    # 1. Check filename extension
    if not filename.lower().endswith(".csv"):
        return CSVValidationResult(valid=False, error=CSV_INVALID_EXTENSION)

    # 2. Check file size
    if len(file_content) > MAX_FILE_SIZE:
        return CSVValidationResult(valid=False, error=CSV_SIZE_EXCEEDED)

    # 3. Detect encoding (try UTF-8 first, then Latin-1)
    decoded_content: str | None = None
    detected_encoding: str | None = None

    try:
        decoded_content = file_content.decode("utf-8")
        detected_encoding = "utf-8"
    except (UnicodeDecodeError, ValueError):
        try:
            decoded_content = file_content.decode("latin-1")
            detected_encoding = "latin-1"
        except (UnicodeDecodeError, ValueError):
            decoded_content = None

    if decoded_content is None:
        return CSVValidationResult(valid=False, error=CSV_INVALID_ENCODING)

    # 4. Parse CSV headers and detect text column
    try:
        reader = csv.reader(io.StringIO(decoded_content))
        headers = next(reader, None)
    except csv.Error:
        return CSVValidationResult(valid=False, error=CSV_NO_TEXT_COLUMN)

    if headers is None:
        return CSVValidationResult(
            valid=False, encoding=detected_encoding, error=CSV_NO_TEXT_COLUMN
        )

    # Normalize headers and find recognized column
    text_column: str | None = None
    for header in headers:
        normalized = header.strip().lower()
        if normalized in RECOGNIZED_COLUMNS:
            text_column = normalized
            break

    if text_column is None:
        return CSVValidationResult(
            valid=False, encoding=detected_encoding, error=CSV_NO_TEXT_COLUMN
        )

    # 5. Count data rows (≤ 50,000)
    row_count = 0
    try:
        for _ in reader:
            row_count += 1
            if row_count > MAX_ROWS:
                return CSVValidationResult(
                    valid=False,
                    text_column=text_column,
                    encoding=detected_encoding,
                    row_count=row_count,
                    error=CSV_ROW_LIMIT_EXCEEDED,
                )
    except csv.Error:
        # If CSV parsing fails during row counting, still report column issue
        return CSVValidationResult(
            valid=False, encoding=detected_encoding, error=CSV_NO_TEXT_COLUMN
        )

    # All validations passed
    return CSVValidationResult(
        valid=True,
        text_column=text_column,
        encoding=detected_encoding,
        row_count=row_count,
    )
