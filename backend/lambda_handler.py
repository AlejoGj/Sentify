"""AWS Lambda entry point for the Sentify API.

This module adapts the FastAPI ASGI application for AWS Lambda + API Gateway
using the Mangum adapter. API Gateway HTTP events are translated into ASGI
requests and routed through the existing FastAPI app, preserving all routes
under the /api/v1/ prefix with zero changes to application code.

Lifespan is disabled (`lifespan="off"`) because Lambda manages its own
lifecycle; the lifespan context manager (which calls init_db) is intentionally
not invoked in production — DynamoDB is used instead of SQLite on Lambda.

Unhandled exceptions bubble up through Mangum and are caught by the Lambda
runtime; the full stack trace is emitted via the Python `logging` module and
visible in CloudWatch Logs, while API Gateway returns a generic HTTP 500.
"""

import logging

from mangum import Mangum

from app.main import app

# Configure module-level logger so unhandled exceptions appear in CloudWatch
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# handler is the symbol that AWS Lambda invokes for every incoming request.
# Mangum translates API Gateway v1 (REST) and v2 (HTTP) proxy events into
# ASGI scope/receive/send calls and forwards them to the FastAPI app.
handler = Mangum(app, lifespan="off")
