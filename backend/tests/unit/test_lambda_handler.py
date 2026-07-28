"""Smoke tests for the Lambda handler entry point.

Verifies that:
- The handler is a Mangum instance (correct adapter wrapping the FastAPI app)
- The handler can process a minimal API Gateway v2 proxy event and reach
  the /health endpoint, returning HTTP 200.

Requirements: 5.1, 5.2, 5.3
"""

from mangum import Mangum


def test_handler_is_mangum_instance() -> None:
    """The handler exported from lambda_handler must be a Mangum adapter."""
    from lambda_handler import handler  # noqa: PLC0415

    assert isinstance(handler, Mangum), (
        f"Expected handler to be a Mangum instance, got {type(handler)}"
    )


def test_handler_routes_health_endpoint() -> None:
    """Handler processes a minimal API Gateway v2 proxy event to /health and returns 200."""
    from lambda_handler import handler  # noqa: PLC0415

    # Minimal API Gateway HTTP API (v2) proxy event
    event = {
        "version": "2.0",
        "routeKey": "GET /health",
        "rawPath": "/health",
        "rawQueryString": "",
        "headers": {"content-type": "application/json"},
        "requestContext": {
            "http": {
                "method": "GET",
                "path": "/health",
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
                "userAgent": "test",
            },
            "requestId": "test-req-id",
        },
        "body": None,
        "isBase64Encoded": False,
    }
    context = {}

    response = handler(event, context)

    assert response["statusCode"] == 200, (
        f"Expected HTTP 200 from /health, got {response['statusCode']}. "
        f"Full response: {response}"
    )
