# Implementation Plan: Cloud Migration

## Overview

Migrate Sentify's backend infrastructure from local/self-hosted components to AWS managed services (Comprehend, Cognito, DynamoDB, Lambda) while preserving the existing interface-driven architecture. Each task implements a concrete provider behind an existing ABC, updates configuration/DI, and includes corresponding tests.

## Tasks

- [x] 1. Update configuration and dependency injection
  - [x] 1.1 Extend Settings class with AWS configuration fields
    - Add `use_local_providers`, `aws_region`, `cognito_user_pool_id`, `cognito_app_client_id`, `dynamodb_table_name` fields to the Settings class in `backend/app/config.py`
    - All fields use the `SENTIFY_` environment variable prefix
    - `use_local_providers` defaults to `True`
    - _Requirements: 8.3, 8.4_

  - [x] 1.2 Add startup validation for AWS environment variables
    - When `use_local_providers` is `False`, validate that all required AWS env vars are set and non-empty
    - Raise a configuration error at startup indicating which variable is missing
    - When `use_local_providers` is `True`, skip AWS validation entirely
    - _Requirements: 8.5, 8.6_

  - [x] 1.3 Update dependencies.py with provider factory switching
    - Update `get_storage_provider()`, `get_auth_provider()`, and `get_nlp_provider()` factory functions
    - When `use_local_providers` is `True`, return existing local providers
    - When `use_local_providers` is `False`, return AWS provider instances with config from Settings
    - Preserve existing function signatures
    - _Requirements: 8.1, 8.2, 8.6_

  - [x] 1.4 Write unit tests for configuration validation
    - **Property 17: AWS startup configuration validation**
    - **Validates: Requirements 8.5**
    - Test that missing AWS vars raise errors when `use_local_providers=False`
    - Test that local mode works without AWS vars

- [x] 2. Implement ComprehendNLPProvider
  - [x] 2.1 Create ComprehendNLPProvider class implementing INLPProvider
    - Create file `backend/app/infrastructure/nlp/comprehend_nlp_provider.py`
    - Implement `validate_text` with local validation: empty/whitespace → "texto_vacio", <2 significant words → "pocas_palabras", >5000 UTF-8 bytes → "texto_muy_largo"
    - Initialize boto3 comprehend client with configurable region
    - _Requirements: 1.1, 1.9, 1.10, 1.12_

  - [x] 2.2 Implement analyze_sentiment method
    - Call `comprehend.detect_sentiment(Text=text, LanguageCode="es")`
    - Compute polarity score: `round(max(-1.0, min(1.0, Positive - Negative)), 2)`
    - Classify: >0.2 → "positivo", <-0.2 → "negativo", else → "neutro"
    - Return SentimentResult with score, classification, and confidence
    - Raise exception with AWS error code on service errors
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 1.11_

  - [x] 2.3 Implement extract_keywords method
    - Call `comprehend.detect_key_phrases(Text=text, LanguageCode="es")`
    - Filter phrases to >2 characters, sort by confidence descending, normalize to lowercase
    - Clamp max_keywords parameter to range 1-10
    - Return empty list for empty/whitespace input without calling AWS
    - Raise exception on AWS service errors
    - _Requirements: 1.7, 1.8, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [ ]* 2.4 Write property tests for sentiment score computation
    - **Property 1: Sentiment score computation and classification consistency**
    - **Validates: Requirements 1.3, 1.4, 1.5, 1.6**
    - Use Hypothesis to generate Positive/Negative floats in [0,1]
    - Verify score formula and classification thresholds

  - [ ]* 2.5 Write property tests for keyword extraction invariants
    - **Property 2: Keyword extraction invariants**
    - **Validates: Requirements 1.7, 1.8, 2.1, 2.2, 2.3**
    - Verify filtering, ordering, lowercase normalization, and max_keywords clamping

  - [ ]* 2.6 Write property tests for text validation
    - **Property 3: Empty/whitespace input validation**
    - **Property 4: Insufficient significant words validation**
    - **Property 5: Oversized text rejection**
    - **Validates: Requirements 1.9, 1.10, 1.12, 2.5**
    - Generate edge-case strings with Hypothesis

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Implement CognitoAuthProvider
  - [x] 4.1 Create CognitoAuthProvider class implementing IAuthProvider
    - Create file `backend/app/infrastructure/auth/cognito_auth_provider.py`
    - Initialize boto3 cognito-idp client with configurable region, user_pool_id, client_id
    - Implement `hash_password` as no-op returning empty string
    - Implement `verify_password` as no-op returning False
    - _Requirements: 10.1, 10.2, 3.1_

  - [x] 4.2 Implement register method
    - Call `cognito.sign_up()` with email as username and company_name as custom attribute
    - Validate email (max 128 chars), password (8-128 chars), company_name (1-255 chars)
    - Handle UsernameExistsException, InvalidPasswordException, and service errors
    - Return appropriate AuthResult for each case
    - _Requirements: 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

  - [ ] 4.3 Implement authenticate method
    - Call `cognito.initiate_auth(AuthFlow="USER_PASSWORD_AUTH", ...)`
    - Extract tokens and map "sub" → user_id, "custom:company_name" → company_name, "exp" → expiration
    - Return generic error message on invalid credentials (not revealing which field)
    - Handle account locked/disabled, service unreachable
    - _Requirements: 4.1, 4.2, 4.3, 10.3, 10.5_

  - [ ] 4.4 Implement validate_token with JWKS caching
    - Fetch JWKS from Cognito well-known endpoint
    - Cache JWKS keys for up to 24 hours
    - Validate JWT signature (RS256), expiration, and claims
    - Return AuthToken on success, None on failure
    - _Requirements: 4.4, 4.5, 10.4_

  - [ ] 4.5 Implement refresh_token method
    - Call `cognito.initiate_auth(AuthFlow="REFRESH_TOKEN_AUTH", ...)`
    - Return updated AuthResult with new AuthToken
    - _Requirements: 4.7_

  - [ ]* 4.6 Write property tests for Cognito token claim mapping
    - **Property 6: Cognito token claim mapping**
    - **Validates: Requirements 4.1, 4.4**
    - Generate JWT payloads with Hypothesis, verify AuthToken field mapping

  - [ ]* 4.7 Write property tests for token validation rejection
    - **Property 7: Token validation rejects invalid tokens**
    - **Validates: Requirements 4.5**
    - Generate expired/invalid JWTs, verify None return

  - [ ]* 4.8 Write property tests for no-op password methods
    - **Property 8: Cognito no-op password methods**
    - **Validates: Requirements 10.1, 10.2**
    - Generate arbitrary strings, verify hash_password returns "" and verify_password returns False

- [ ] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Implement DynamoDBStorageProvider
  - [ ] 6.1 Create DynamoDBStorageProvider class implementing IStorageProvider
    - Create file `backend/app/infrastructure/storage/dynamodb_storage_provider.py`
    - Initialize boto3 DynamoDB resource with table name and region
    - Define single-table key schema constants (PK/SK patterns for User, Batch, Feedback, Keyword)
    - Implement UUID v4 generation for all IDs
    - _Requirements: 6.1, 6.2, 6.10_

  - [ ] 6.2 Implement user operations (create_user, get_user_by_email)
    - `create_user`: Store with PK=`USER#{email}`, SK=`USER#{email}`, plus USERID pointer item
    - Initialize failed_attempts=0, locked_until=None, created_at as UTC ISO-8601
    - Use conditional put to prevent duplicate emails
    - `get_user_by_email`: Query by PK/SK, return None if not found
    - Implement `increment_failed_attempts`, `reset_failed_attempts`, `lock_account`
    - _Requirements: 6.8, 6.9, 6.11_

  - [ ] 6.3 Implement batch operations (create_batch, update_batch_status, update_batch_counts, get_user_batches)
    - `create_batch`: Store with PK=`USER#{user_id}`, SK=`BATCH#{batch_id}`, status="pending", uploaded_at UTC ISO-8601
    - `update_batch_status`: Update status, set completed_at when status is "completed"
    - `update_batch_counts`: Use atomic ADD expressions for total_rows, processed_rows, error_rows
    - `get_user_batches`: Query PK with SK begins_with "BATCH#", paginate, order by uploaded_at descending
    - _Requirements: 6.3, 6.12, 7.1, 7.2, 7.3_

  - [ ] 6.4 Implement feedback operations (store_feedback, store_feedback_error, get_batch_feedbacks, get_urgent_feedbacks)
    - `store_feedback`: Store with PK=`BATCH#{batch_id}`, SK=`FEEDBACK#{feedback_id}`, truncate original_text to 5000 chars
    - `store_feedback_error`: Store with status "error" and error_reason
    - Write keyword index items (PK=`BATCH#{batch_id}`, SK=`KW#{word}#FEEDBACK#{feedback_id}`)
    - `get_batch_feedbacks`: Query GSI1, filter status="success", paginate
    - `get_urgent_feedbacks`: Query GSI1, filter score < threshold and status="success", order by score ascending
    - _Requirements: 6.4, 6.5, 6.7, 7.4_

  - [ ] 6.5 Implement keyword operations (get_top_keywords, get_feedbacks_by_keyword)
    - `get_top_keywords`: Query PK=`BATCH#{batch_id}`, SK begins_with `KW#`, aggregate frequencies in-memory, sort descending
    - `get_feedbacks_by_keyword`: Query GSI2 with PK=`BATCH#{batch_id}#KW#{word}`
    - _Requirements: 6.6_

  - [ ] 6.6 Implement batch write operations with retry logic
    - Use DynamoDB `batch_write_item` with chunks of 25 items
    - Retry unprocessed items with exponential backoff up to 3 attempts
    - _Requirements: 7.5_

  - [ ]* 6.7 Write property tests for feedback text truncation
    - **Property 9: Feedback text truncation invariant**
    - **Validates: Requirements 6.4, 7.4**
    - Generate texts of varying length, verify stored text is at most 5000 chars

  - [ ]* 6.8 Write property tests for batch creation
    - **Property 10: Batch creation produces valid structure**
    - **Validates: Requirements 6.3, 6.10**
    - Verify UUID v4 format, status "pending", and ISO-8601 timestamp

  - [ ]* 6.9 Write property tests for pagination math
    - **Property 11: Pagination math invariant**
    - **Validates: Requirements 6.5, 6.7, 7.3**
    - Generate item counts and page sizes, verify total_pages calculation

  - [ ]* 6.10 Write property tests for keyword frequency aggregation
    - **Property 12: Keyword frequency aggregation correctness**
    - **Validates: Requirements 6.6**
    - Generate feedback sets with keyword lists, verify frequency counts

  - [ ]* 6.11 Write property tests for urgent feedback filtering
    - **Property 13: Urgent feedback filtering and ordering**
    - **Validates: Requirements 6.7**
    - Generate feedbacks with various scores, verify threshold filtering and ordering

  - [ ]* 6.12 Write property tests for user round-trip persistence
    - **Property 14: User round-trip persistence**
    - **Validates: Requirements 6.8, 6.9**
    - Create user then retrieve, verify all fields match

  - [ ]* 6.13 Write property tests for batch status update
    - **Property 15: Batch status update with completed_at**
    - **Validates: Requirements 6.12, 7.1**
    - Verify completed_at is set only when status is "completed"

- [ ] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Implement Lambda handler and API Gateway integration
  - [ ] 8.1 Create Lambda handler entry point
    - Create file `backend/lambda_handler.py` at project root
    - Install and import Mangum adapter
    - Create handler: `handler = Mangum(app, lifespan="off")`
    - Ensure all existing routes are preserved under /api/v1/ prefix
    - _Requirements: 5.1, 5.2, 5.3_

  - [ ] 8.2 Configure authentication middleware for Lambda context
    - Verify JWT validation from Authorization header in "Bearer {token}" format works via Cognito_Provider
    - Return HTTP 401 with WWW-Authenticate: Bearer header for invalid/missing tokens on protected endpoints
    - Public endpoints (POST /login, POST /register) bypass auth
    - _Requirements: 5.4, 5.5_

  - [ ] 8.3 Configure CORS and error handling for API Gateway
    - Set CORS: allowed origin from env var, methods GET/POST, headers Content-Type/Authorization, credentials enabled
    - Unhandled exceptions return HTTP 500 with generic message
    - Log full stack traces via Python logging (for CloudWatch)
    - _Requirements: 5.7, 5.8, 5.9_

  - [ ]* 8.4 Write integration tests for Lambda handler
    - Test all routes via Mangum with mocked AWS services (moto)
    - Test auth middleware behavior, CORS headers, error responses
    - Test multipart file upload handling
    - _Requirements: 5.1, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.10_

- [ ] 9. Implement data migration script
  - [ ] 9.1 Create SQLite to DynamoDB migration script
    - Create file `backend/scripts/migrate_sqlite_to_dynamodb.py`
    - Read all users, batches, feedbacks, and keywords from SQLite
    - Transform each record into DynamoDB single-table schema format (PK/SK patterns)
    - Preserve all field values including null fields
    - _Requirements: 9.1, 9.2_

  - [ ] 9.2 Implement batch write with retry and reporting
    - Write in batches of 25 items using `batch_write_item`
    - Exponential backoff on throttled requests up to 5 retries per batch
    - Log failed records (entity type + record ID) and continue processing
    - Output summary report: total read, successfully written, failed per entity type
    - Compare DynamoDB counts vs SQLite source counts and report discrepancies
    - _Requirements: 9.3, 9.4, 9.5, 9.6_

  - [ ]* 9.3 Write property tests for migration data transformation
    - **Property 16: Migration record transformation preserves data**
    - **Validates: Requirements 9.2**
    - Generate sample records, verify PK/SK patterns and field preservation

  - [ ]* 9.4 Write integration tests for migration script
    - Test full migration flow with moto (mock DynamoDB and real SQLite)
    - Verify summary report accuracy
    - Test retry behavior on throttled writes
    - _Requirements: 9.3, 9.4, 9.5, 9.6_

- [ ] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- All AWS calls in tests are mocked using `moto` — no real AWS credentials needed
- The Mangum adapter preserves all existing FastAPI routes, middleware, and validation with zero API code changes
- The `use_local_providers` flag enables gradual rollout and easy local development

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["1.4", "2.1", "4.1", "6.1"] },
    { "id": 3, "tasks": ["2.2", "2.3", "4.2", "4.3", "6.2", "6.3"] },
    { "id": 4, "tasks": ["2.4", "2.5", "2.6", "4.4", "4.5", "6.4", "6.5"] },
    { "id": 5, "tasks": ["4.6", "4.7", "4.8", "6.6", "6.7", "6.8"] },
    { "id": 6, "tasks": ["6.9", "6.10", "6.11", "6.12", "6.13"] },
    { "id": 7, "tasks": ["8.1"] },
    { "id": 8, "tasks": ["8.2", "8.3", "9.1"] },
    { "id": 9, "tasks": ["8.4", "9.2"] },
    { "id": 10, "tasks": ["9.3", "9.4"] }
  ]
}
```
