"""
Property-based tests for CSV validation logic.

Feature: sentiment-analysis-platform
"""

import csv
import io
import string

from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from app.utils.csv_parser import (
    validate_csv,
    CSVValidationResult,
    RECOGNIZED_COLUMNS,
    MAX_FILE_SIZE,
    MAX_ROWS,
    CSV_INVALID_EXTENSION,
    CSV_INVALID_ENCODING,
    CSV_NO_TEXT_COLUMN,
    CSV_SIZE_EXCEEDED,
    CSV_ROW_LIMIT_EXCEEDED,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid recognized column names (drawn from the set)
recognized_columns = st.sampled_from(sorted(RECOGNIZED_COLUMNS))

# Valid CSV filenames ending in .csv
valid_csv_filenames = st.from_regex(r"[a-z][a-z0-9_]{0,20}\.csv", fullmatch=True)

# Encodings supported by the validator
valid_encodings = st.sampled_from(["utf-8", "latin-1"])

# Number of extra columns (besides the text column)
extra_column_count = st.integers(min_value=0, max_value=5)

# Number of data rows (at least 1, kept small for performance)
row_count_strategy = st.integers(min_value=1, max_value=20)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_csv_bytes(
    text_column: str,
    extra_headers: list[str],
    num_rows: int,
    row_data: list[list[str]],
    encoding: str = "utf-8",
) -> bytes:
    """Build a CSV file as bytes with the given structure."""
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header row
    headers = [text_column] + extra_headers
    writer.writerow(headers)

    # Write data rows
    for row in row_data[:num_rows]:
        writer.writerow(row)

    return output.getvalue().encode(encoding)


# ---------------------------------------------------------------------------
# Property 5: CSV validation accepts recognized column names
# ---------------------------------------------------------------------------


class TestCSVValidationAcceptsRecognizedColumns:
    """
    Property 5: CSV validation accepts recognized column names

    For any CSV file with a valid extension (.csv), valid encoding (UTF-8 or
    Latin-1), at least one data row, size <= 10 MB, row count <= 50,000, and a
    text column with a header in the set {"texto", "comentario", "review",
    "comment", "feedback"}, the validator SHALL accept the file and return the
    detected column name.

    Feature: sentiment-analysis-platform, Property 5: CSV validation accepts recognized column names

    **Validates: Requirements 2.1, 2.2**
    """

    @given(
        text_column=recognized_columns,
        num_extra_cols=extra_column_count,
        num_rows=row_count_strategy,
        encoding=valid_encodings,
        filename=valid_csv_filenames,
    )
    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
        deadline=None,
    )
    def test_valid_csv_is_accepted(
        self,
        text_column: str,
        num_extra_cols: int,
        num_rows: int,
        encoding: str,
        filename: str,
    ):
        """
        A CSV file meeting all constraints is accepted and the detected text
        column name matches the recognized header used.

        **Validates: Requirements 2.1, 2.2**
        """
        # Build extra headers that are NOT recognized columns
        extra_headers = [f"col_{i}" for i in range(num_extra_cols)]

        # Build row data - each row has text_column value + extra column values
        row_data = [
            [f"sample text {r}"] + [f"val_{r}_{c}" for c in range(num_extra_cols)]
            for r in range(num_rows)
        ]

        file_content = build_csv_bytes(
            text_column=text_column,
            extra_headers=extra_headers,
            num_rows=num_rows,
            row_data=row_data,
            encoding=encoding,
        )

        # Ensure file is within size limits
        assume(len(file_content) <= MAX_FILE_SIZE)

        result = validate_csv(file_content, filename)

        assert result.valid is True
        assert result.text_column == text_column
        assert result.encoding is not None
        assert result.encoding in ("utf-8", "latin-1")
        assert result.row_count == num_rows

    @given(
        text_column=recognized_columns,
        num_rows=row_count_strategy,
        filename=valid_csv_filenames,
    )
    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
        deadline=None,
    )
    def test_case_insensitive_column_detection(
        self,
        text_column: str,
        num_rows: int,
        filename: str,
    ):
        """
        Column detection is case-insensitive: upper/mixed case headers are
        still recognized and returned in lowercase.

        **Validates: Requirements 2.1, 2.2**
        """
        # Use uppercase version of the recognized column
        upper_column = text_column.upper()

        row_data = [[f"text row {r}"] for r in range(num_rows)]

        file_content = build_csv_bytes(
            text_column=upper_column,
            extra_headers=[],
            num_rows=num_rows,
            row_data=row_data,
            encoding="utf-8",
        )

        result = validate_csv(file_content, filename)

        assert result.valid is True
        assert result.text_column == text_column  # lowercase normalized


# ---------------------------------------------------------------------------
# Property 6: CSV validation rejects invalid files with specific reason
# ---------------------------------------------------------------------------


class TestCSVValidationRejectsInvalidFiles:
    """
    Property 6: CSV validation rejects invalid files with specific reason

    For any file that violates at least one constraint (wrong extension,
    unsupported encoding, missing recognized column, size > 10 MB, or row
    count > 50,000), the validator SHALL reject the file and return an error
    message that identifies the specific violation.

    Feature: sentiment-analysis-platform, Property 6: CSV validation rejects invalid files with specific reason

    **Validates: Requirements 2.3, 2.4**
    """

    @given(
        filename=st.from_regex(
            r"[a-z][a-z0-9_]{0,15}\.(txt|xlsx|json|xml|tsv|pdf|doc)",
            fullmatch=True,
        ),
    )
    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
        deadline=None,
    )
    def test_rejects_wrong_extension(self, filename: str):
        """
        Files without .csv extension are rejected with CSV_INVALID_EXTENSION.

        **Validates: Requirements 2.3, 2.4**
        """
        # Build valid CSV content but with wrong filename
        content = b"texto,other\nHello,World\n"

        result = validate_csv(content, filename)

        assert result.valid is False
        assert result.error == CSV_INVALID_EXTENSION

    @given(
        num_rows=st.integers(min_value=1, max_value=5),
    )
    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
        deadline=None,
    )
    def test_rejects_size_exceeded(self, num_rows: int):
        """
        Files exceeding 10 MB are rejected with CSV_SIZE_EXCEEDED.

        **Validates: Requirements 2.3, 2.4**
        """
        # Create content that exceeds MAX_FILE_SIZE
        header = "texto,data\n"
        # Each row has large padding to push over the limit
        padding_per_row = "x" * (MAX_FILE_SIZE // num_rows + 1)
        rows = "".join(f"hello,{padding_per_row}\n" for _ in range(num_rows))
        content = (header + rows).encode("utf-8")

        # Ensure it actually exceeds the limit
        assume(len(content) > MAX_FILE_SIZE)

        result = validate_csv(content, "data.csv")

        assert result.valid is False
        assert result.error == CSV_SIZE_EXCEEDED

    @given(
        headers=st.lists(
            st.from_regex(r"[a-z]{3,10}_col", fullmatch=True),
            min_size=1,
            max_size=5,
        ),
        num_rows=row_count_strategy,
    )
    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
        deadline=None,
    )
    def test_rejects_no_recognized_column(self, headers: list[str], num_rows: int):
        """
        Files without any recognized text column header are rejected with
        CSV_NO_TEXT_COLUMN.

        **Validates: Requirements 2.3, 2.4**
        """
        # Ensure no generated header is a recognized column
        for h in headers:
            assume(h.strip().lower() not in RECOGNIZED_COLUMNS)

        # Build CSV content with unrecognized headers
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        for r in range(num_rows):
            writer.writerow([f"val_{r}_{c}" for c in range(len(headers))])

        content = output.getvalue().encode("utf-8")

        result = validate_csv(content, "data.csv")

        assert result.valid is False
        assert result.error == CSV_NO_TEXT_COLUMN

    @given(
        extra_rows=st.integers(min_value=1, max_value=100),
    )
    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
        deadline=None,
        max_examples=5,  # Limited due to large file generation
    )
    def test_rejects_row_limit_exceeded(self, extra_rows: int):
        """
        Files with more than 50,000 data rows are rejected with
        CSV_ROW_LIMIT_EXCEEDED.

        **Validates: Requirements 2.3, 2.4**
        """
        # Build a CSV with exactly MAX_ROWS + extra_rows data rows
        total_rows = MAX_ROWS + extra_rows

        # Build efficiently using string concatenation
        header = "texto\n"
        row_line = "sample text\n"
        content = (header + row_line * total_rows).encode("utf-8")

        # Ensure within size limit (so we test row limit, not size limit)
        assume(len(content) <= MAX_FILE_SIZE)

        result = validate_csv(content, "big_file.csv")

        assert result.valid is False
        assert result.error == CSV_ROW_LIMIT_EXCEEDED
        assert result.text_column == "texto"
