import json
import math

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_auth_provider, get_storage_provider
from app.main import app

MOCK_TOKEN = "mock-jwt-token-for-tests"


def _patch_storage_total_pages(storage):
    original = storage.get_user_batches

    def patched(user_id, page, page_size=10):
        result = original(user_id, page, page_size)
        result["total_pages"] = (
            math.ceil(result["total"] / page_size) if result["total"] > 0 else 0
        )
        return result

    storage.get_user_batches = patched


def make_lambda_event(method, path, headers=None, body=None):
    headers = headers or {}
    return {
        "version": "2.0",
        "routeKey": f"{method} {path}",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {"content-type": "application/json", **headers},
        "requestContext": {
            "http": {
                "method": method,
                "path": path,
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
                "userAgent": "test",
            },
            "requestId": "test-req-id",
        },
        "body": body,
        "isBase64Encoded": False,
    }


@pytest.fixture
def auth_client(mock_auth_provider, mock_storage_provider):
    _patch_storage_total_pages(mock_storage_provider)
    app.dependency_overrides[get_auth_provider] = lambda: mock_auth_provider
    app.dependency_overrides[get_storage_provider] = lambda: mock_storage_provider
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()


class TestProtectedEndpoints:
    def test_missing_auth_header_returns_auth_rejection(self, auth_client):
        response = auth_client.get("/api/v1/batches")
        assert response.status_code in (401, 403)

    def test_invalid_token_returns_401_with_www_authenticate(self, auth_client):
        response = auth_client.get(
            "/api/v1/batches",
            headers={"Authorization": "Bearer totally-invalid-token"},
        )
        assert response.status_code == 401
        assert "WWW-Authenticate" in response.headers
        assert response.headers["WWW-Authenticate"] == "Bearer"

    def test_valid_token_allows_access(self, auth_client):
        token = MOCK_TOKEN
        response = auth_client.get(
            "/api/v1/batches",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

    def test_malformed_scheme_returns_auth_rejection(self, auth_client):
        response = auth_client.get(
            "/api/v1/batches",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert response.status_code in (401, 403)

    def test_bearer_keyword_only_no_token_returns_auth_rejection(self, auth_client):
        response = auth_client.get(
            "/api/v1/batches",
            headers={"Authorization": "Bearer"},
        )
        assert response.status_code in (401, 403)

    def test_invalid_token_error_body_contains_detail(self, auth_client):
        response = auth_client.get(
            "/api/v1/batches",
            headers={"Authorization": "Bearer bad-token"},
        )
        assert response.status_code == 401
        data = response.json()
        assert "detail" in data

    def test_expired_token_returns_401_with_www_authenticate_header(self, auth_client):
        response = auth_client.get(
            "/api/v1/batches",
            headers={"Authorization": "Bearer expired-or-wrong-token"},
        )
        assert response.status_code == 401
        assert response.headers.get("WWW-Authenticate") == "Bearer"


class TestPublicEndpoints:
    def test_login_no_auth_header_processes_normally(self, auth_client):
        response = auth_client.post(
            "/api/v1/auth/login",
            json={"email": "unknown@test.com", "password": "wrongpassword"},
        )
        assert response.status_code != 403

    def test_register_no_auth_header_processes_normally(self, auth_client):
        response = auth_client.post(
            "/api/v1/auth/register",
            json={
                "email": "newuser@test.com",
                "password": "securepass123",
                "company_name": "Test Corp",
            },
        )
        assert response.status_code not in (401, 403)

    def test_login_valid_credentials_returns_200(self, auth_client):
        response = auth_client.post(
            "/api/v1/auth/login",
            json={"email": "test@empresa.com", "password": "test-fixture-pass"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "token" in data

    def test_register_new_user_returns_201(self, auth_client):
        response = auth_client.post(
            "/api/v1/auth/register",
            json={
                "email": "brand-new@empresa.com",
                "password": "securepass123",
                "company_name": "Brand New Corp",
            },
        )
        assert response.status_code == 201

    def test_login_endpoint_does_not_require_authorization_header(self, auth_client):
        response = auth_client.post(
            "/api/v1/auth/login",
            json={"email": "test@empresa.com", "password": "test-fixture-pass"},
            headers={},
        )
        assert response.status_code == 200

    def test_register_endpoint_does_not_require_authorization_header(self, auth_client):
        response = auth_client.post(
            "/api/v1/auth/register",
            json={
                "email": "another@empresa.com",
                "password": "securepass123",
                "company_name": "Another Corp",
            },
            headers={},
        )
        assert response.status_code == 201


class TestLambdaMangumMiddleware:
    def test_mangum_protected_route_with_valid_token_returns_200(
        self, mock_auth_provider, mock_storage_provider
    ):
        _patch_storage_total_pages(mock_storage_provider)
        app.dependency_overrides[get_auth_provider] = lambda: mock_auth_provider
        app.dependency_overrides[get_storage_provider] = lambda: mock_storage_provider
        try:
            from lambda_handler import handler
            token = MOCK_TOKEN
            event = make_lambda_event(
                method="GET",
                path="/api/v1/batches",
                headers={"authorization": f"Bearer {token}"},
            )
            response = handler(event, {})
            assert response["statusCode"] == 200
        finally:
            app.dependency_overrides.clear()

    def test_mangum_protected_route_without_token_returns_auth_rejection(
        self, mock_auth_provider, mock_storage_provider
    ):
        _patch_storage_total_pages(mock_storage_provider)
        app.dependency_overrides[get_auth_provider] = lambda: mock_auth_provider
        app.dependency_overrides[get_storage_provider] = lambda: mock_storage_provider
        try:
            from lambda_handler import handler
            event = make_lambda_event(method="GET", path="/api/v1/batches")
            response = handler(event, {})
            assert response["statusCode"] in (401, 403)
        finally:
            app.dependency_overrides.clear()

    def test_mangum_protected_route_with_invalid_token_returns_401(
        self, mock_auth_provider, mock_storage_provider
    ):
        _patch_storage_total_pages(mock_storage_provider)
        app.dependency_overrides[get_auth_provider] = lambda: mock_auth_provider
        app.dependency_overrides[get_storage_provider] = lambda: mock_storage_provider
        try:
            from lambda_handler import handler
            event = make_lambda_event(
                method="GET",
                path="/api/v1/batches",
                headers={"authorization": "Bearer invalid-token-xyz"},
            )
            response = handler(event, {})
            assert response["statusCode"] == 401
            resp_headers = response.get("headers", {})
            assert "www-authenticate" in {k.lower() for k in resp_headers}
        finally:
            app.dependency_overrides.clear()

    def test_mangum_public_login_without_token_processes_normally(
        self, mock_auth_provider, mock_storage_provider
    ):
        app.dependency_overrides[get_auth_provider] = lambda: mock_auth_provider
        app.dependency_overrides[get_storage_provider] = lambda: mock_storage_provider
        try:
            from lambda_handler import handler
            body = json.dumps(
                {"email": "test@empresa.com", "password": "test-fixture-pass"}
            )
            event = make_lambda_event(
                method="POST",
                path="/api/v1/auth/login",
                body=body,
            )
            response = handler(event, {})
            assert response["statusCode"] == 200
        finally:
            app.dependency_overrides.clear()
