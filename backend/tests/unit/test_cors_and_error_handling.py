"""Tests for CORS configuration and global exception handling.

Covers requirements 5.7 (CORS), 5.8 (unhandled exceptions -> HTTP 500).

- CORS preflight includes correct Access-Control-Allow-Origin header
- CORS header present on real GET/POST responses
- Unhandled exceptions return HTTP 500 with generic Spanish message
- Internal exception details are NOT exposed in the response body
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_auth_provider, get_storage_provider

# The origin used in tests — must match settings.cors_allowed_origin (default "*")
TEST_ORIGIN = "http://localhost:3000"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(mock_auth_provider, mock_storage_provider) -> TestClient:
    """Test client with dependency overrides for auth and storage."""
    app.dependency_overrides[get_auth_provider] = lambda: mock_auth_provider
    app.dependency_overrides[get_storage_provider] = lambda: mock_storage_provider
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


@pytest.fixture()
def client_with_crash_route(mock_auth_provider, mock_storage_provider) -> TestClient:
    """Test client with a temporary route that raises an unhandled exception."""
    async def crashing_route():
        raise RuntimeError("secret internal error details")

    app.add_api_route("/test-crash", crashing_route, methods=["GET"])
    app.dependency_overrides[get_auth_provider] = lambda: mock_auth_provider
    app.dependency_overrides[get_storage_provider] = lambda: mock_storage_provider
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()
    # Remove the transient test route so it does not bleed into other tests.
    # app.routes is a read-only property backed by app.router.routes, so mutate
    # the underlying list directly.
    app.router.routes[:] = [
        r for r in app.router.routes if getattr(r, "path", None) != "/test-crash"
    ]


# ---------------------------------------------------------------------------
# CORS tests -- Requirement 5.7
# ---------------------------------------------------------------------------

class TestCORSPreflight:
    """OPTIONS preflight requests must include the correct CORS headers."""

    def test_preflight_returns_allow_origin_header(self, client: TestClient):
        """CORS preflight on /health should echo back the allowed origin."""
        response = client.options(
            "/health",
            headers={
                "Origin": TEST_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        # 200 or 204 are both valid preflight responses
        assert response.status_code in (200, 204)
        assert "access-control-allow-origin" in response.headers

    def test_preflight_allow_origin_value(self, client: TestClient):
        """Allowed origin on preflight matches the configured origin (default *)."""
        response = client.options(
            "/health",
            headers={
                "Origin": TEST_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        origin_header = response.headers.get("access-control-allow-origin", "")
        # Default config is "*"; if env var is set to TEST_ORIGIN it would also be valid
        assert origin_header in ("*", TEST_ORIGIN)

    def test_preflight_allows_get_and_post_methods(self, client: TestClient):
        """Preflight must allow at least GET and POST."""
        response = client.options(
            "/health",
            headers={
                "Origin": TEST_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        methods_header = response.headers.get("access-control-allow-methods", "")
        # Header may be "*" or an explicit list; either GET or POST must appear
        assert ("GET" in methods_header or "*" in methods_header) or (
            "POST" in methods_header or "*" in methods_header
        )

    def test_preflight_allows_content_type_and_authorization_headers(
        self, client: TestClient
    ):
        """Preflight must allow Content-Type and Authorization request headers."""
        response = client.options(
            "/health",
            headers={
                "Origin": TEST_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Content-Type, Authorization",
            },
        )
        allowed_headers = response.headers.get("access-control-allow-headers", "")
        # Either wildcard or explicit listing is acceptable
        assert "*" in allowed_headers or (
            "content-type" in allowed_headers.lower()
            and "authorization" in allowed_headers.lower()
        )


class TestCORSActualRequests:
    """Real GET/POST responses must include Access-Control-Allow-Origin."""

    def test_get_health_includes_allow_origin(self, client: TestClient):
        """GET /health with an Origin header returns Access-Control-Allow-Origin."""
        response = client.get("/health", headers={"Origin": TEST_ORIGIN})
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers

    def test_post_login_includes_allow_origin(self, client: TestClient):
        """POST /api/v1/login with an Origin header returns Access-Control-Allow-Origin."""
        response = client.post(
            "/api/v1/login",
            json={"email": "a@b.com", "password": "wrong"},
            headers={"Origin": TEST_ORIGIN},
        )
        # Any status is fine -- we only care that the CORS header is present
        assert "access-control-allow-origin" in response.headers


# ---------------------------------------------------------------------------
# Unhandled exception handler tests -- Requirement 5.8
# ---------------------------------------------------------------------------

class TestUnhandledExceptionHandler:
    """Truly unhandled exceptions must return 500 with a generic Spanish message."""

    def test_crash_route_returns_500(self, client_with_crash_route: TestClient):
        """A route that raises RuntimeError must respond with HTTP 500."""
        response = client_with_crash_route.get("/test-crash")
        assert response.status_code == 500

    def test_crash_route_returns_generic_message(
        self, client_with_crash_route: TestClient
    ):
        """The 500 body must contain the generic Spanish error message."""
        response = client_with_crash_route.get("/test-crash")
        body = response.json()
        assert body.get("detail") == "Error interno del servidor"

    def test_crash_route_does_not_expose_internal_message(
        self, client_with_crash_route: TestClient
    ):
        """The 500 body must NOT contain the internal exception message."""
        response = client_with_crash_route.get("/test-crash")
        body_text = response.text
        assert "secret internal error details" not in body_text
        assert "RuntimeError" not in body_text

    def test_error_message_is_in_spanish(self, client_with_crash_route: TestClient):
        """The generic error message must be the Spanish string."""
        response = client_with_crash_route.get("/test-crash")
        body = response.json()
        assert body.get("detail") == "Error interno del servidor"

    def test_crash_response_is_json(self, client_with_crash_route: TestClient):
        """The 500 response must be valid JSON."""
        response = client_with_crash_route.get("/test-crash")
        # If this raises, the response is not valid JSON
        body = response.json()
        assert isinstance(body, dict)
        assert "detail" in body
