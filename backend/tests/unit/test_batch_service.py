"""Unit tests for BatchService orchestrator."""

import pytest

from app.core.services.batch_service import BatchService, BatchProcessingResult
from app.core.interfaces.nlp_provider import INLPProvider, SentimentResult, NLPError


def _make_csv(rows: list[str], column: str = "texto") -> bytes:
    """Helper to build CSV bytes from a list of text rows.
    
    Wraps each value in quotes to ensure empty strings are preserved as rows.
    """
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([column])
    for row in rows:
        writer.writerow([row])
    return output.getvalue().encode("utf-8")


class TestBatchServiceProcessBatch:
    """Tests for BatchService.process_batch."""

    def test_successful_processing_all_rows(
        self, mock_nlp_provider, mock_storage_provider
    ):
        """All valid rows should be processed successfully."""
        service = BatchService(mock_nlp_provider, mock_storage_provider)
        csv_content = _make_csv([
            "El producto es bueno y funcional",
            "La atención fue excelente en todo momento",
            "El servicio fue normal y adecuado",
        ])

        result = service.process_batch("user-1", "test.csv", csv_content)

        assert result.total_feedbacks == 3
        assert result.successful == 3
        assert result.failed == 0
        assert result.errors == []
        assert result.batch_id is not None

    def test_csv_validation_failure_raises_value_error(
        self, mock_nlp_provider, mock_storage_provider
    ):
        """Invalid CSV should raise ValueError before creating a batch."""
        service = BatchService(mock_nlp_provider, mock_storage_provider)
        # Wrong extension
        with pytest.raises(ValueError, match="csv_invalid_extension"):
            service.process_batch("user-1", "data.txt", b"texto\nhola mundo")

    def test_partial_failure_with_empty_text(
        self, mock_nlp_provider, mock_storage_provider
    ):
        """Empty text rows should be marked as errors; valid rows succeed."""
        service = BatchService(mock_nlp_provider, mock_storage_provider)
        csv_content = _make_csv([
            "El producto es bueno y funcional",
            "",  # Empty — should fail NLP validation
            "El servicio fue excelente realmente",
        ])

        result = service.process_batch("user-1", "feedback.csv", csv_content)

        assert result.total_feedbacks == 3
        assert result.successful == 2
        assert result.failed == 1
        assert len(result.errors) == 1
        assert result.errors[0]["reason"] == "texto_vacio"
        assert result.errors[0]["feedback_index"] == 1

    def test_partial_failure_with_short_text(
        self, mock_nlp_provider, mock_storage_provider
    ):
        """Texts with too few significant words should be errors."""
        service = BatchService(mock_nlp_provider, mock_storage_provider)
        csv_content = _make_csv([
            "ok",  # Too short — pocas_palabras
            "El producto fue bueno y satisfactorio",
        ])

        result = service.process_batch("user-1", "reviews.csv", csv_content)

        assert result.total_feedbacks == 2
        assert result.successful == 1
        assert result.failed == 1
        assert result.errors[0]["reason"] == "pocas_palabras"

    def test_invariant_processed_plus_errors_equals_total(
        self, mock_nlp_provider, mock_storage_provider
    ):
        """processed + failed must always equal total_feedbacks."""
        service = BatchService(mock_nlp_provider, mock_storage_provider)
        csv_content = _make_csv([
            "Buen producto en general me gusta",
            "",
            "Terrible experiencia con el servicio",
            "x",  # pocas_palabras
            "Servicio regular pero cumple bien",
        ])

        result = service.process_batch("user-1", "mixed.csv", csv_content)

        assert result.successful + result.failed == result.total_feedbacks

    def test_batch_status_transitions(
        self, mock_nlp_provider, mock_storage_provider
    ):
        """Batch should end with 'completed' status after processing."""
        service = BatchService(mock_nlp_provider, mock_storage_provider)
        csv_content = _make_csv(["El producto funciona bien en general"])

        result = service.process_batch("user-1", "simple.csv", csv_content)

        batch = mock_storage_provider._batches[result.batch_id]
        assert batch["status"] == "completed"

    def test_batch_counts_updated_correctly(
        self, mock_nlp_provider, mock_storage_provider
    ):
        """Batch total_rows, processed_count, error_count should be updated."""
        service = BatchService(mock_nlp_provider, mock_storage_provider)
        csv_content = _make_csv([
            "Excelente calidad del producto recibido",
            "",  # error
            "Malo el servicio de atención al cliente",
        ])

        result = service.process_batch("user-1", "counts.csv", csv_content)

        batch = mock_storage_provider._batches[result.batch_id]
        assert batch["total_rows"] == 3
        assert batch["processed_count"] == 2
        assert batch["error_count"] == 1

    def test_text_truncation_to_5000_chars(
        self, mock_nlp_provider, mock_storage_provider
    ):
        """Texts longer than 5000 chars should be truncated before storage."""
        service = BatchService(mock_nlp_provider, mock_storage_provider)
        long_text = "palabra larga " * 1000  # Well over 5000 chars
        csv_content = _make_csv([long_text])

        result = service.process_batch("user-1", "long.csv", csv_content)

        assert result.successful == 1
        # Check stored feedback text is truncated
        stored = list(mock_storage_provider._feedbacks.values())[0]
        assert len(stored["text"]) <= 5000

    def test_recognized_column_names(
        self, mock_nlp_provider, mock_storage_provider
    ):
        """Should work with any recognized column name."""
        for col_name in ["texto", "comentario", "review", "comment", "feedback"]:
            service = BatchService(mock_nlp_provider, mock_storage_provider)
            csv_content = _make_csv(
                ["El producto es bueno y funcional"], column=col_name
            )
            result = service.process_batch("user-1", f"{col_name}.csv", csv_content)
            assert result.successful == 1

    def test_nlp_exception_handled_gracefully(
        self, mock_storage_provider
    ):
        """If NLP provider raises an exception, the row is marked as error."""

        class FailingNLPProvider(INLPProvider):
            def analyze_sentiment(self, text: str) -> SentimentResult:
                raise RuntimeError("NLP engine crash")

            def extract_keywords(self, text: str, max_keywords: int = 10) -> list[str]:
                return []

            def validate_text(self, text: str) -> NLPError | None:
                return None  # Passes validation, but analyze_sentiment will crash

        service = BatchService(FailingNLPProvider(), mock_storage_provider)
        csv_content = _make_csv(["El producto es bueno y funcional"])

        result = service.process_batch("user-1", "crash.csv", csv_content)

        assert result.total_feedbacks == 1
        assert result.failed == 1
        assert result.successful == 0
        assert "unexpected_error" in result.errors[0]["reason"]

    def test_empty_csv_no_data_rows(
        self, mock_nlp_provider, mock_storage_provider
    ):
        """A CSV with only headers and no data rows should result in 0 feedbacks."""
        service = BatchService(mock_nlp_provider, mock_storage_provider)
        csv_content = b"texto\n"

        result = service.process_batch("user-1", "empty.csv", csv_content)

        assert result.total_feedbacks == 0
        assert result.successful == 0
        assert result.failed == 0

    def test_feedbacks_stored_with_correct_sentiment(
        self, mock_nlp_provider, mock_storage_provider
    ):
        """Each feedback should be stored with the NLP-determined sentiment."""
        service = BatchService(mock_nlp_provider, mock_storage_provider)
        csv_content = _make_csv([
            "El producto es bueno y funcional",
            "Terrible experiencia con el servicio",
            "El servicio fue normal y cumple bien",
        ])

        service.process_batch("user-1", "sentiments.csv", csv_content)

        feedbacks = list(mock_storage_provider._feedbacks.values())
        sentiments = [f["sentiment"] for f in feedbacks]
        assert "positivo" in sentiments
        assert "negativo" in sentiments
