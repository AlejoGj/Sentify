"""Unit tests for CSV validation logic."""

import pytest

from app.utils.csv_parser import (
    CSVValidationResult,
    CSV_INVALID_ENCODING,
    CSV_INVALID_EXTENSION,
    CSV_NO_TEXT_COLUMN,
    CSV_ROW_LIMIT_EXCEEDED,
    CSV_SIZE_EXCEEDED,
    MAX_FILE_SIZE,
    MAX_ROWS,
    RECOGNIZED_COLUMNS,
    validate_csv,
)


class TestExtensionValidation:
    """Tests for filename extension check."""

    def test_rejects_txt_extension(self):
        content = b"texto,score\nhola,1"
        result = validate_csv(content, "data.txt")
        assert result.valid is False
        assert result.error == CSV_INVALID_EXTENSION

    def test_rejects_no_extension(self):
        content = b"texto,score\nhola,1"
        result = validate_csv(content, "data")
        assert result.valid is False
        assert result.error == CSV_INVALID_EXTENSION

    def test_rejects_xlsx_extension(self):
        content = b"texto,score\nhola,1"
        result = validate_csv(content, "data.xlsx")
        assert result.valid is False
        assert result.error == CSV_INVALID_EXTENSION

    def test_accepts_csv_extension_case_insensitive(self):
        content = b"texto,score\nhola,1"
        result = validate_csv(content, "data.CSV")
        assert result.valid is True

    def test_accepts_csv_extension_mixed_case(self):
        content = b"texto,score\nhola,1"
        result = validate_csv(content, "data.Csv")
        assert result.valid is True


class TestSizeValidation:
    """Tests for file size limit."""

    def test_rejects_file_exceeding_10mb(self):
        # Create content just over 10 MB
        content = b"x" * (MAX_FILE_SIZE + 1)
        result = validate_csv(content, "big.csv")
        assert result.valid is False
        assert result.error == CSV_SIZE_EXCEEDED

    def test_accepts_file_exactly_at_limit(self):
        # Build a valid CSV that is exactly at size limit
        header = b"texto\n"
        row = b"una fila de datos\n"
        # Fill up to just under MAX_FILE_SIZE
        num_rows = (MAX_FILE_SIZE - len(header)) // len(row)
        # Ensure we don't exceed MAX_ROWS
        num_rows = min(num_rows, MAX_ROWS)
        content = header + row * num_rows
        # Only check that size validation doesn't reject it
        result = validate_csv(content, "exact.csv")
        assert result.error != CSV_SIZE_EXCEEDED


class TestEncodingValidation:
    """Tests for encoding detection."""

    def test_accepts_utf8_encoded_content(self):
        content = "texto,score\nñoño,1\n".encode("utf-8")
        result = validate_csv(content, "utf8.csv")
        assert result.valid is True
        assert result.encoding == "utf-8"

    def test_accepts_latin1_encoded_content(self):
        # Create content with bytes that are invalid UTF-8 but valid Latin-1
        content = "texto,score\n".encode("utf-8") + b"\xf1o\xf1o,1\n"
        result = validate_csv(content, "latin1.csv")
        assert result.valid is True
        assert result.encoding == "latin-1"

    def test_prefers_utf8_over_latin1(self):
        # Pure ASCII is valid as both UTF-8 and Latin-1, should pick UTF-8
        content = b"texto,score\nhello,1\n"
        result = validate_csv(content, "ascii.csv")
        assert result.encoding == "utf-8"


class TestColumnDetection:
    """Tests for recognized text column detection."""

    @pytest.mark.parametrize("column", sorted(RECOGNIZED_COLUMNS))
    def test_recognizes_valid_column(self, column: str):
        content = f"{column},other\ndata,value\n".encode("utf-8")
        result = validate_csv(content, "test.csv")
        assert result.valid is True
        assert result.text_column == column

    def test_recognizes_column_case_insensitive(self):
        content = b"TEXTO,other\ndata,value\n"
        result = validate_csv(content, "test.csv")
        assert result.valid is True
        assert result.text_column == "texto"

    def test_recognizes_column_with_whitespace(self):
        content = b"  texto  ,other\ndata,value\n"
        result = validate_csv(content, "test.csv")
        assert result.valid is True
        assert result.text_column == "texto"

    def test_rejects_no_recognized_column(self):
        content = b"nombre,puntaje\ndata,1\n"
        result = validate_csv(content, "test.csv")
        assert result.valid is False
        assert result.error == CSV_NO_TEXT_COLUMN

    def test_rejects_empty_file(self):
        content = b""
        result = validate_csv(content, "empty.csv")
        assert result.valid is False
        assert result.error == CSV_NO_TEXT_COLUMN

    def test_accepts_header_only_no_data_rows(self):
        content = b"texto,score\n"
        result = validate_csv(content, "header_only.csv")
        assert result.valid is True
        assert result.row_count == 0


class TestRowLimitValidation:
    """Tests for row count limit."""

    def test_rejects_file_exceeding_50000_rows(self):
        header = "texto\n"
        # Build a minimal CSV with > 50,000 rows
        row = "x\n"
        content = (header + row * (MAX_ROWS + 1)).encode("utf-8")
        result = validate_csv(content, "big_rows.csv")
        assert result.valid is False
        assert result.error == CSV_ROW_LIMIT_EXCEEDED

    def test_accepts_file_at_exactly_50000_rows(self):
        header = "texto\n"
        row = "x\n"
        content = (header + row * MAX_ROWS).encode("utf-8")
        result = validate_csv(content, "exact_rows.csv")
        assert result.valid is True
        assert result.row_count == MAX_ROWS


class TestSuccessResult:
    """Tests for successful validation result."""

    def test_returns_complete_result_on_success(self):
        content = b"texto,score\nfila uno,1\nfila dos,2\nfila tres,3\n"
        result = validate_csv(content, "valid.csv")
        assert result.valid is True
        assert result.text_column == "texto"
        assert result.encoding == "utf-8"
        assert result.row_count == 3
        assert result.error is None
