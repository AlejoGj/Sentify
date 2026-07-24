"""Unit tests for batch API endpoints.

Tests:
- CSV upload validation errors (422)
- Batch status transitions
- Pagination on batch history
- Keyword filtering (Req 6.3)
- Triage ordering (Req 7.4)
- Token validation on protected endpoints
"""

import io
import math
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.middleware.auth_middleware import get_current_user
from app.core.interfaces.auth_provider import AuthToken
from app.dependencies import get_nlp_provider, get_storage_provider
from app.main import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_user_token() -> AuthToken:
    """Return a mock AuthToken for the authenticated user."""
    return AuthToken(
        token="mock-jwt-token-for-tests",
        expires_at=datetime.utcnow() + timedelta(minutes=30),
        user_id="user-001",
        company_name="Empresa Test",
    )


@pytest.fixture
def batch_client(mock_storage_provider, mock_nlp_provider, mock_user_token):
    """Create a test client with mocked dependencies for batch endpoints."""
    app.dependency_overrides[get_current_user] = lambda: mock_user_token
    app.dependency_overrides[get_storage_provider] = lambda: mock_storage_provider
    app.dependency_overrides[get_nlp_provider] = lambda: mock_nlp_provider
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def unauth_client(mock_storage_provider, mock_nlp_provider):
    """Create a test client WITHOUT auth override (no current user)."""
    app.dependency_overrides[get_storage_provider] = lambda: mock_storage_provider
    app.dependency_overrides[get_nlp_provider] = lambda: mock_nlp_provider
    # Do NOT override get_current_user — real middleware will require a token
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def seeded_storage(mock_storage_provider):
    """Seed the mock storage with batches and feedbacks for query tests."""
    storage = mock_storage_provider

    # Create batches for user-001
    batch_id = storage.create_batch("user-001", "test.csv")
    storage.update_batch_status(batch_id, "completed")
    storage.update_batch_counts(batch_id, total_rows=5, processed_rows=4, error_rows=1)

    # Store feedbacks with different sentiments and keywords
    storage.store_feedback(batch_id, "Producto excelente calidad", "positivo", 0.85, ["producto", "excelente", "calidad"], "success")
    storage.store_feedback(batch_id, "Servicio malo y lento", "negativo", -0.80, ["servicio", "malo", "lento"], "success")
    storage.store_feedback(batch_id, "Entrega rápida del producto", "positivo", 0.60, ["entrega", "producto"], "success")
    storage.store_feedback(batch_id, "Experiencia terrible nunca más", "negativo", -0.90, ["experiencia", "terrible"], "success")

    return storage, batch_id


# ---------------------------------------------------------------------------
# CSV Upload Validation (422 errors)
# ---------------------------------------------------------------------------


class TestCSVUploadValidation:
    """Tests for POST /api/v1/batches/upload — validation errors."""

    def test_upload_invalid_extension_returns_422(self, batch_client):
        """Uploading a non-CSV file returns 422 with extension error."""
        file_content = b"some data"
        response = batch_client.post(
            "/api/v1/batches/upload",
            files={"file": ("data.txt", io.BytesIO(file_content), "text/plain")},
        )
        assert response.status_code == 422
        assert "csv_invalid_extension" in response.json()["detail"]

    def test_upload_missing_text_column_returns_422(self, batch_client):
        """CSV without a recognized text column returns 422."""
        csv_content = b"nombre,edad\nJuan,30\nMaria,25\n"
        response = batch_client.post(
            "/api/v1/batches/upload",
            files={"file": ("data.csv", io.BytesIO(csv_content), "text/csv")},
        )
        assert response.status_code == 422
        assert "csv_no_text_column" in response.json()["detail"]

    def test_upload_empty_csv_returns_422(self, batch_client):
        """An empty CSV (no headers) returns 422."""
        csv_content = b""
        response = batch_client.post(
            "/api/v1/batches/upload",
            files={"file": ("empty.csv", io.BytesIO(csv_content), "text/csv")},
        )
        assert response.status_code == 422
        assert "csv_no_text_column" in response.json()["detail"]

    def test_upload_valid_csv_returns_202(self, batch_client):
        """A valid CSV with recognized text column returns 202 Accepted."""
        csv_content = b"texto,categoria\nProducto excelente calidad buena,electronica\nMalo servicio pesimo lento,ropa\n"
        response = batch_client.post(
            "/api/v1/batches/upload",
            files={"file": ("reviews.csv", io.BytesIO(csv_content), "text/csv")},
        )
        assert response.status_code == 202
        data = response.json()
        assert "batch_id" in data
        assert "message" in data


# ---------------------------------------------------------------------------
# Batch Status
# ---------------------------------------------------------------------------


class TestBatchStatus:
    """Tests for GET /api/v1/batches/{id}/status."""

    def test_get_batch_status_returns_correct_info(
        self, batch_client, seeded_storage
    ):
        """Status endpoint returns batch processing details."""
        storage, batch_id = seeded_storage
        # Patch batch to include required fields for the route
        batch = storage._batches[batch_id]
        batch["uploaded_at"] = batch["created_at"]
        batch["processed_rows"] = batch["processed_count"]
        batch["error_rows"] = batch["error_count"]

        # Patch get_user_batches to include total_pages
        original_get_user_batches = storage.get_user_batches

        def patched_get_user_batches(user_id, page, page_size=10):
            result = original_get_user_batches(user_id, page, page_size)
            result["total_pages"] = math.ceil(result["total"] / page_size) if result["total"] > 0 else 0
            return result

        storage.get_user_batches = patched_get_user_batches

        response = batch_client.get(f"/api/v1/batches/{batch_id}/status")
        assert response.status_code == 200
        data = response.json()
        assert data["batch_id"] == batch_id
        assert data["status"] == "completed"
        assert data["total_rows"] == 5
        assert data["processed_rows"] == 4
        assert data["error_rows"] == 1

    def test_get_batch_status_not_found_returns_404(self, batch_client):
        """Requesting status for nonexistent batch returns 404."""
        response = batch_client.get("/api/v1/batches/nonexistent-id/status")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Pagination on Batch History
# ---------------------------------------------------------------------------


class TestBatchPagination:
    """Tests for GET /api/v1/batches — paginated batch list."""

    def test_list_batches_returns_paginated_response(
        self, batch_client, mock_storage_provider
    ):
        """Batch list returns paginated structure with correct metadata."""
        storage = mock_storage_provider
        # Create multiple batches
        for i in range(15):
            storage.create_batch("user-001", f"file_{i}.csv")

        # Patch get_user_batches to include total_pages
        original_get_user_batches = storage.get_user_batches

        def patched_get_user_batches(user_id, page, page_size=10):
            result = original_get_user_batches(user_id, page, page_size)
            result["total_pages"] = math.ceil(result["total"] / page_size)
            return result

        storage.get_user_batches = patched_get_user_batches

        response = batch_client.get("/api/v1/batches?page=1&page_size=5")
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 5
        assert data["total"] == 15
        assert data["total_pages"] == 3
        assert len(data["items"]) == 5

    def test_list_batches_second_page(self, batch_client, mock_storage_provider):
        """Second page returns remaining items."""
        storage = mock_storage_provider
        for i in range(7):
            storage.create_batch("user-001", f"file_{i}.csv")

        original_get_user_batches = storage.get_user_batches

        def patched_get_user_batches(user_id, page, page_size=10):
            result = original_get_user_batches(user_id, page, page_size)
            result["total_pages"] = math.ceil(result["total"] / page_size)
            return result

        storage.get_user_batches = patched_get_user_batches

        response = batch_client.get("/api/v1/batches?page=2&page_size=5")
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 2
        assert len(data["items"]) == 2
        assert data["total"] == 7

    def test_list_batches_empty(self, batch_client, mock_storage_provider):
        """No batches returns empty items list with zero total."""
        original_get_user_batches = mock_storage_provider.get_user_batches

        def patched_get_user_batches(user_id, page, page_size=10):
            result = original_get_user_batches(user_id, page, page_size)
            result["total_pages"] = 0
            return result

        mock_storage_provider.get_user_batches = patched_get_user_batches

        response = batch_client.get("/api/v1/batches")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0


# ---------------------------------------------------------------------------
# Keyword Filtering (Req 6.3)
# ---------------------------------------------------------------------------


class TestKeywordFiltering:
    """Tests for GET /api/v1/batches/{id}/feedbacks?keyword=X."""

    def test_feedbacks_filtered_by_keyword(self, batch_client, seeded_storage):
        """Filtering by keyword returns only matching feedbacks."""
        storage, batch_id = seeded_storage
        self._patch_storage(storage, batch_id)

        response = batch_client.get(
            f"/api/v1/batches/{batch_id}/feedbacks?keyword=producto"
        )
        assert response.status_code == 200
        data = response.json()
        # "producto" appears in 2 feedbacks
        assert data["total"] == 2
        for item in data["items"]:
            assert "producto" in item["keywords"]

    def test_feedbacks_keyword_no_match_returns_empty(
        self, batch_client, seeded_storage
    ):
        """Filtering by non-existent keyword returns empty list."""
        storage, batch_id = seeded_storage
        self._patch_storage(storage, batch_id)

        response = batch_client.get(
            f"/api/v1/batches/{batch_id}/feedbacks?keyword=inexistente"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_feedbacks_without_keyword_returns_all(
        self, batch_client, seeded_storage
    ):
        """Without keyword param, returns all feedbacks paginated."""
        storage, batch_id = seeded_storage
        self._patch_storage(storage, batch_id)

        response = batch_client.get(
            f"/api/v1/batches/{batch_id}/feedbacks"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 4

    @staticmethod
    def _patch_storage(storage, batch_id):
        """Patch mock storage methods to include total_pages and batch fields."""
        batch = storage._batches[batch_id]
        batch["uploaded_at"] = batch["created_at"]
        batch["processed_rows"] = batch["processed_count"]
        batch["error_rows"] = batch["error_count"]

        # Patch get_user_batches
        original_get_user_batches = storage.get_user_batches

        def patched_get_user_batches(user_id, page, page_size=10):
            result = original_get_user_batches(user_id, page, page_size)
            result["total_pages"] = math.ceil(result["total"] / page_size) if result["total"] > 0 else 0
            return result

        storage.get_user_batches = patched_get_user_batches

        # Patch get_feedbacks_by_keyword
        original_get_feedbacks_by_keyword = storage.get_feedbacks_by_keyword

        def patched_get_feedbacks_by_keyword(batch_id, keyword, page, page_size=20):
            result = original_get_feedbacks_by_keyword(batch_id, keyword, page, page_size)
            result["total_pages"] = math.ceil(result["total"] / page_size) if result["total"] > 0 else 0
            return result

        storage.get_feedbacks_by_keyword = patched_get_feedbacks_by_keyword

        # Patch get_batch_feedbacks
        original_get_batch_feedbacks = storage.get_batch_feedbacks

        def patched_get_batch_feedbacks(batch_id, page, page_size=20):
            result = original_get_batch_feedbacks(batch_id, page, page_size)
            result["total_pages"] = math.ceil(result["total"] / page_size) if result["total"] > 0 else 0
            return result

        storage.get_batch_feedbacks = patched_get_batch_feedbacks


# ---------------------------------------------------------------------------
# Triage Ordering (Req 7.4)
# ---------------------------------------------------------------------------


class TestTriageEndpoint:
    """Tests for GET /api/v1/batches/{id}/triage — urgent feedbacks."""

    def test_triage_returns_urgent_feedbacks_sorted_ascending(
        self, batch_client, seeded_storage
    ):
        """Triage endpoint returns feedbacks with score < -0.7, sorted ascending."""
        storage, batch_id = seeded_storage
        self._patch_storage(storage, batch_id)

        response = batch_client.get(f"/api/v1/batches/{batch_id}/triage")
        assert response.status_code == 200
        data = response.json()

        # Two feedbacks have score < -0.7: -0.80 and -0.90
        assert data["total"] == 2
        items = data["items"]
        # Should be sorted by score ascending (most negative first)
        scores = [item["score"] for item in items]
        assert scores == sorted(scores)
        assert scores[0] == -0.90
        assert scores[1] == -0.80

    def test_triage_pagination(self, batch_client, seeded_storage):
        """Triage endpoint respects page_size parameter."""
        storage, batch_id = seeded_storage
        self._patch_storage(storage, batch_id)

        response = batch_client.get(
            f"/api/v1/batches/{batch_id}/triage?page=1&page_size=1"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["total"] == 2
        assert data["total_pages"] == 2

    @staticmethod
    def _patch_storage(storage, batch_id):
        """Patch mock storage methods to include total_pages and batch fields."""
        batch = storage._batches[batch_id]
        batch["uploaded_at"] = batch["created_at"]
        batch["processed_rows"] = batch["processed_count"]
        batch["error_rows"] = batch["error_count"]

        original_get_user_batches = storage.get_user_batches

        def patched_get_user_batches(user_id, page, page_size=10):
            result = original_get_user_batches(user_id, page, page_size)
            result["total_pages"] = math.ceil(result["total"] / page_size) if result["total"] > 0 else 0
            return result

        storage.get_user_batches = patched_get_user_batches

        original_get_urgent = storage.get_urgent_feedbacks

        def patched_get_urgent(batch_id, threshold, page, page_size=10):
            result = original_get_urgent(batch_id, threshold, page, page_size)
            result["total_pages"] = math.ceil(result["total"] / page_size) if result["total"] > 0 else 0
            return result

        storage.get_urgent_feedbacks = patched_get_urgent


# ---------------------------------------------------------------------------
# Token Validation (401/403 without valid token)
# ---------------------------------------------------------------------------


class TestTokenValidation:
    """Tests that protected endpoints reject requests without valid tokens."""

    def test_upload_without_token_returns_401(self, unauth_client):
        """Upload endpoint without auth header returns 401."""
        csv_content = b"texto\nHola mundo\n"
        response = unauth_client.post(
            "/api/v1/batches/upload",
            files={"file": ("test.csv", io.BytesIO(csv_content), "text/csv")},
        )
        assert response.status_code == 401

    def test_list_batches_without_token_returns_401(self, unauth_client):
        """List batches without auth header returns 401."""
        response = unauth_client.get("/api/v1/batches")
        assert response.status_code == 401

    def test_batch_status_without_token_returns_401(self, unauth_client):
        """Batch status without auth header returns 401."""
        response = unauth_client.get("/api/v1/batches/some-id/status")
        assert response.status_code == 401

    def test_triage_without_token_returns_401(self, unauth_client):
        """Triage endpoint without auth header returns 401."""
        response = unauth_client.get("/api/v1/batches/some-id/triage")
        assert response.status_code == 401

    def test_invalid_token_returns_401(self, mock_storage_provider, mock_nlp_provider, mock_auth_provider):
        """An invalid Bearer token returns 401."""
        from app.dependencies import get_auth_provider

        app.dependency_overrides[get_storage_provider] = lambda: mock_storage_provider
        app.dependency_overrides[get_nlp_provider] = lambda: mock_nlp_provider
        app.dependency_overrides[get_auth_provider] = lambda: mock_auth_provider

        client = TestClient(app)
        try:
            response = client.get(
                "/api/v1/batches",
                headers={"Authorization": "Bearer invalid-token-here"},
            )
            assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()

    def test_valid_token_passes_auth(self, mock_storage_provider, mock_nlp_provider, mock_auth_provider):
        """A valid Bearer token passes auth middleware."""
        from app.dependencies import get_auth_provider

        app.dependency_overrides[get_storage_provider] = lambda: mock_storage_provider
        app.dependency_overrides[get_nlp_provider] = lambda: mock_nlp_provider
        app.dependency_overrides[get_auth_provider] = lambda: mock_auth_provider

        # Patch storage to return total_pages
        original_get_user_batches = mock_storage_provider.get_user_batches

        def patched_get_user_batches(user_id, page, page_size=10):
            result = original_get_user_batches(user_id, page, page_size)
            result["total_pages"] = 0
            return result

        mock_storage_provider.get_user_batches = patched_get_user_batches

        client = TestClient(app)
        try:
            response = client.get(
                "/api/v1/batches",
                headers={"Authorization": "Bearer mock-jwt-token-for-tests"},
            )
            assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()
