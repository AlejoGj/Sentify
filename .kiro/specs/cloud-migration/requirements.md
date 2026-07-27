# Requirements Document

## Introduction

This specification defines the requirements for migrating Sentify's backend infrastructure from local/self-hosted components to AWS managed services. The migration replaces four infrastructure providers while preserving the existing interface-driven architecture: spaCy NLP moves to AWS Comprehend, bcrypt/PyJWT auth moves to AWS Cognito, the FastAPI server moves to AWS Lambda, and SQLite storage moves to DynamoDB. All existing business logic, API contracts, and frontend behavior remain unchanged.

## Glossary

- **Comprehend_Provider**: The concrete implementation of INLPProvider that uses AWS Comprehend for Spanish-language sentiment analysis and key phrase extraction
- **Cognito_Provider**: The concrete implementation of IAuthProvider that uses AWS Cognito for user authentication, registration, and token validation
- **Lambda_Handler**: The AWS Lambda function(s) that receive API Gateway events and route them to the application's service layer
- **DynamoDB_Provider**: The concrete implementation of IStorageProvider that uses AWS DynamoDB for data persistence
- **API_Gateway**: AWS API Gateway configured as HTTP API to proxy requests to Lambda functions
- **Sentiment_Score**: A floating-point value between -1.0 and 1.0 representing text sentiment polarity, rounded to 2 decimal places
- **User_Pool**: An AWS Cognito User Pool configured for email-based authentication with password policies
- **INLPProvider**: The abstract base class defining the NLP analysis contract (analyze_sentiment, extract_keywords, validate_text)
- **IAuthProvider**: The abstract base class defining the authentication contract (authenticate, validate_token, hash_password, verify_password)
- **IStorageProvider**: The abstract base class defining the data persistence contract (create_batch, store_feedback, get_batch_summary, etc.)
- **Migration_Script**: A standalone Python script that reads all data from the existing SQLite database and writes it to DynamoDB in the single-table schema format

## Requirements

### Requirement 1: AWS Comprehend Sentiment Analysis

**User Story:** As a corporate user, I want the platform to use AWS Comprehend for sentiment analysis, so that I get reliable Spanish-language sentiment scores without maintaining local NLP models.

#### Acceptance Criteria

1. THE Comprehend_Provider SHALL implement the INLPProvider interface
2. WHEN a valid Spanish text is provided to analyze_sentiment, THE Comprehend_Provider SHALL call AWS Comprehend's detect_sentiment API with language code "es" and return a SentimentResult
3. WHEN AWS Comprehend returns a sentiment classification, THE Comprehend_Provider SHALL compute a single polarity score using the formula: (Positive - Negative) clamped to the range -1.0 to 1.0 and rounded to 2 decimal places
4. WHEN the computed polarity score is greater than 0.2, THE Comprehend_Provider SHALL classify the sentiment as "positivo"
5. WHEN the computed polarity score is less than -0.2, THE Comprehend_Provider SHALL classify the sentiment as "negativo"
6. WHEN the computed polarity score is between -0.2 and 0.2 inclusive, THE Comprehend_Provider SHALL classify the sentiment as "neutro"
7. WHEN a valid Spanish text is provided to extract_keywords, THE Comprehend_Provider SHALL call AWS Comprehend's detect_key_phrases API with language code "es" and return up to 10 key phrases sorted by confidence score descending, filtered to terms longer than 2 characters, and normalized to lowercase
8. WHEN extract_keywords returns results, THE Comprehend_Provider SHALL filter key phrases to only include terms longer than 2 characters
9. WHEN validate_text receives an empty string or whitespace-only string, THE Comprehend_Provider SHALL return an NLPError with reason "texto_vacio"
10. WHEN validate_text receives text with fewer than 2 significant words (words longer than 2 characters after whitespace splitting), THE Comprehend_Provider SHALL return an NLPError with reason "pocas_palabras"
11. IF AWS Comprehend returns an error or is unreachable, THEN THE Comprehend_Provider SHALL raise an exception with a descriptive error message including the AWS error code
12. THE Comprehend_Provider SHALL reject input text exceeding 5000 UTF-8 bytes by returning an NLPError with reason "texto_muy_largo" without calling the AWS API

### Requirement 2: AWS Comprehend Key Phrase Extraction

**User Story:** As a corporate user, I want keyword extraction to use AWS Comprehend's key phrase detection, so that keywords are extracted using a robust managed NLP service.

#### Acceptance Criteria

1. WHEN extract_keywords is called with a max_keywords parameter, THE Comprehend_Provider SHALL clamp the parameter to the range 1 to 10, discard any key phrases with 2 or fewer characters, and return at most the clamped number of key phrases
2. WHEN AWS Comprehend returns key phrases with confidence scores, THE Comprehend_Provider SHALL sort results by confidence score in descending order, apply the character length filter, and then apply the max_keywords limit
3. THE Comprehend_Provider SHALL normalize all extracted key phrases to lowercase before returning them
4. WHEN AWS Comprehend returns no key phrases for a given text, THE Comprehend_Provider SHALL return an empty list
5. IF the input text is empty or contains only whitespace, THEN THE Comprehend_Provider SHALL return an empty list without calling AWS Comprehend
6. IF the AWS Comprehend API call fails due to a service error or network issue, THEN THE Comprehend_Provider SHALL raise an exception indicating that keyword extraction failed and include the underlying error reason

### Requirement 3: AWS Cognito User Registration

**User Story:** As a new user, I want to register an account using AWS Cognito, so that my credentials are managed securely by a managed identity service.

#### Acceptance Criteria

1. THE Cognito_Provider SHALL implement the IAuthProvider interface and expose a register method accepting email, password, and company_name parameters that returns an AuthResult
2. WHEN a new user registers with a valid email (max 128 characters), password (8 to 128 characters), and company_name (1 to 255 characters), THE Cognito_Provider SHALL create the user in the Cognito User Pool with email as the username
3. WHEN a new user registers successfully, THE Cognito_Provider SHALL store company_name as a custom attribute named "custom:company_name" in the Cognito User Pool
4. WHEN registration succeeds, THE Cognito_Provider SHALL return an AuthResult with success=True
5. IF a registration request uses an email already registered in the User_Pool, THEN THE Cognito_Provider SHALL return an AuthResult with success=False and an error message indicating the email is already in use
6. THE User_Pool SHALL enforce a minimum password length of 8 characters with at least one uppercase letter, one lowercase letter, one number, and one special character
7. IF the registration password does not meet the User_Pool password policy, THEN THE Cognito_Provider SHALL return an AuthResult with success=False and an error message indicating which policy rule was violated
8. IF the Cognito service is unreachable or returns a service error during registration, THEN THE Cognito_Provider SHALL return an AuthResult with success=False and an error message indicating a service availability issue

### Requirement 4: AWS Cognito Authentication

**User Story:** As a registered user, I want to authenticate using AWS Cognito, so that the platform uses industry-standard managed authentication with token refresh.

#### Acceptance Criteria

1. WHEN a user authenticates with valid email and password, THE Cognito_Provider SHALL initiate the USER_PASSWORD_AUTH flow with the Cognito User Pool and return an AuthResult with success=True and a valid AuthToken containing user_id mapped from the Cognito "sub" claim, company_name mapped from a custom "custom:company_name" claim, and expiration derived from the token's "exp" claim
2. WHEN a user authenticates with invalid credentials, THE Cognito_Provider SHALL return an AuthResult with success=False and a generic error message that does not reveal which field is incorrect
3. WHEN Cognito signals that an account is locked or disabled, THE Cognito_Provider SHALL return an AuthResult with success=False and account_locked=True
4. WHEN validate_token receives a JWT issued by the Cognito User Pool, THE Cognito_Provider SHALL verify the token signature against the Cognito JWKS endpoint, cache the JWKS keys for up to 24 hours, and return an AuthToken with user_id, company_name, and expiration extracted from the verified claims if valid
5. IF validate_token receives an expired or invalid token, OR the JWKS endpoint is unreachable and no cached keys are available, THEN THE Cognito_Provider SHALL return None
6. THE Cognito_Provider SHALL configure Cognito to lock accounts after 5 consecutive failed authentication attempts for a duration of 15 minutes
7. WHEN a valid refresh token is provided to refresh_token, THE Cognito_Provider SHALL request new access and ID tokens from Cognito and return an AuthResult with success=True and an updated AuthToken with a new expiration

### Requirement 5: AWS Lambda API Layer

**User Story:** As a platform operator, I want the API to run on AWS Lambda behind API Gateway, so that the platform scales automatically and has no server maintenance overhead.

#### Acceptance Criteria

1. THE Lambda_Handler SHALL expose all existing API endpoints under the /api/v1/ prefix with identical request and response schemas as the existing FastAPI application
2. WHEN an HTTP request arrives at the API_Gateway, THE API_Gateway SHALL proxy the request to the Lambda_Handler as a Lambda event
3. THE Lambda_Handler SHALL support the following HTTP methods and routes: POST /api/v1/login, POST /api/v1/register, POST /api/v1/batches/upload, GET /api/v1/batches/{batch_id}/status, GET /api/v1/batches/{batch_id}/summary, GET /api/v1/batches/{batch_id}/keywords, GET /api/v1/batches/{batch_id}/feedbacks, GET /api/v1/batches/{batch_id}/triage, GET /api/v1/batches
4. THE Lambda_Handler SHALL validate JWT tokens from the Authorization header in "Bearer {token}" format using the Cognito_Provider before processing protected endpoints (all endpoints except POST /api/v1/login and POST /api/v1/register)
5. WHEN a request lacks a valid Authorization header on a protected endpoint, THE Lambda_Handler SHALL return HTTP 401 with an error message indicating invalid or missing credentials and include a WWW-Authenticate: Bearer response header
6. THE Lambda_Handler SHALL accept multipart/form-data file uploads for the CSV batch upload endpoint, and THE API_Gateway SHALL configure a maximum payload size of 10 MB for all routes
7. THE API_Gateway SHALL configure CORS with the allowed origin read from an environment variable, allowed methods GET and POST, allowed headers Content-Type and Authorization, and credentials support enabled
8. IF a Lambda function encounters an unhandled exception, THEN THE Lambda_Handler SHALL return HTTP 500 with a generic error message that does not expose internal details and log the full error details including stack trace to CloudWatch
9. THE Lambda_Handler SHALL be configured with a maximum execution timeout of 60 seconds per invocation
10. WHEN a request arrives for an unsupported route or HTTP method, THE API_Gateway SHALL return HTTP 404 for unknown routes and HTTP 405 for unsupported methods on known routes

### Requirement 6: DynamoDB Data Persistence

**User Story:** As a platform operator, I want data stored in DynamoDB, so that the platform has scalable, managed data persistence without database administration.

#### Acceptance Criteria

1. THE DynamoDB_Provider SHALL implement all methods defined in the IStorageProvider interface (create_batch, update_batch_status, store_feedback, store_feedback_error, get_batch_summary, get_batch_feedbacks, get_feedbacks_by_keyword, get_top_keywords, get_urgent_feedbacks, get_user_batches, create_user, get_user_by_email, increment_failed_attempts, reset_failed_attempts, lock_account, update_batch_counts)
2. THE DynamoDB_Provider SHALL use a single-table design with partition key (PK) and sort key (SK) to store users, batches, feedbacks, and keywords
3. WHEN create_batch is called with user_id and filename, THE DynamoDB_Provider SHALL store a batch item with status "pending", user_id, filename, and uploaded_at timestamp as UTC ISO-8601, and return a generated batch_id
4. WHEN store_feedback is called, THE DynamoDB_Provider SHALL store the feedback with batch_id, original_text truncated to a maximum of 5000 characters, sentiment, score, keywords list, and status, and return a generated feedback_id
5. WHEN get_batch_feedbacks is called with batch_id, page, and page_size (default 20, maximum 100), THE DynamoDB_Provider SHALL return a dictionary containing items (list of feedback records), total (integer count), page, page_size, and total_pages, with results filtered to status "success" and ordered by analyzed_at descending
6. WHEN get_top_keywords is called with batch_id and limit (default 20, maximum 100), THE DynamoDB_Provider SHALL aggregate keyword frequencies across all feedbacks in the specified batch and return a list of dictionaries with "word" and "frequency" fields, sorted by frequency descending, limited to the specified count
7. WHEN get_urgent_feedbacks is called with batch_id, threshold (float between -1.0 and 1.0), page, and page_size (default 10, maximum 100), THE DynamoDB_Provider SHALL return feedbacks with status "success" and score strictly less than the threshold, ordered by score ascending, in the same paginated dictionary format as get_batch_feedbacks
8. WHEN create_user is called with email, password_hash, and company_name, THE DynamoDB_Provider SHALL store the user record with email, password_hash, company_name, failed_attempts initialized to 0, locked_until set to None, and created_at as UTC ISO-8601 timestamp, using email as a unique identifier, and return a generated user_id
9. WHEN get_user_by_email is called and no user exists with that email, THE DynamoDB_Provider SHALL return None; WHEN a user exists, THE DynamoDB_Provider SHALL return a dictionary containing id, email, password_hash, company_name, failed_attempts, locked_until, and created_at fields
10. THE DynamoDB_Provider SHALL generate UUID v4 identifiers for batch_id, feedback_id, and user_id
11. IF a create_user call is made with an email that already exists, THEN THE DynamoDB_Provider SHALL raise an error indicating a duplicate email conflict without overwriting the existing record
12. WHEN update_batch_status is called with batch_id and status, THE DynamoDB_Provider SHALL update the batch item's status field; IF the status is "completed", THEN THE DynamoDB_Provider SHALL also set a completed_at UTC ISO-8601 timestamp
13. IF any DynamoDB operation fails due to a service error, THEN THE DynamoDB_Provider SHALL propagate the exception to the caller without silently swallowing the error

### Requirement 7: DynamoDB Batch Operations

**User Story:** As a corporate user, I want batch operations to work efficiently in DynamoDB, so that bulk uploads and batch queries perform well at scale.

#### Acceptance Criteria

1. WHEN update_batch_status is called with status "completed", THE DynamoDB_Provider SHALL also record a completed_at UTC ISO-8601 timestamp
2. WHEN update_batch_counts is called, THE DynamoDB_Provider SHALL update total_rows, processed_rows, and error_rows using DynamoDB atomic counter operations (ADD expressions) to prevent lost updates from concurrent processing
3. WHEN get_user_batches is called with user_id, page, and page_size, THE DynamoDB_Provider SHALL return the user's batches ordered by uploaded_at descending with pagination, placing batches with null completed_at after those with a completed_at value
4. WHEN store_feedback_error is called, THE DynamoDB_Provider SHALL store a feedback item with status "error", the error_reason, and original_text truncated to 5000 characters
5. WHEN multiple feedbacks are stored for a single batch, THE DynamoDB_Provider SHALL use DynamoDB batch_write_item operations with chunks of 25 items per request, retrying any unprocessed items with exponential backoff up to 3 attempts

### Requirement 8: Configuration and Dependency Injection

**User Story:** As a developer, I want the cloud providers configured through the existing dependency injection system, so that switching between local and cloud implementations requires only a configuration change.

#### Acceptance Criteria

1. THE dependencies module SHALL provide factory functions that return AWS-based provider instances (Comprehend_Provider implementing INLPProvider, Cognito_Provider implementing IAuthProvider, DynamoDB_Provider implementing IStorageProvider) using the same function signatures as the existing local provider factories
2. WHEN the application starts, THE dependencies module SHALL read AWS configuration from environment variables (SENTIFY_AWS_REGION, SENTIFY_COGNITO_USER_POOL_ID, SENTIFY_COGNITO_APP_CLIENT_ID, SENTIFY_DYNAMODB_TABLE_NAME)
3. THE Settings class SHALL include configuration fields for aws_region, cognito_user_pool_id, cognito_app_client_id, and dynamodb_table_name with the SENTIFY_ environment variable prefix, alongside existing fields (database_url, jwt_secret_key, spacy_model)
4. THE Settings class SHALL include a use_local_providers boolean configuration field (defaulting to true) that determines whether factory functions return local providers or AWS providers
5. IF use_local_providers is set to false and any required AWS environment variable (SENTIFY_AWS_REGION, SENTIFY_COGNITO_USER_POOL_ID, SENTIFY_COGNITO_APP_CLIENT_ID, SENTIFY_DYNAMODB_TABLE_NAME) is missing or empty, THEN THE application SHALL raise a configuration error at startup before accepting requests, indicating which variable is missing
6. WHILE use_local_providers is set to true, THE dependencies module SHALL return the existing local provider instances (LocalAuthProvider, SpaCyNLPProvider, SQLiteStorageProvider) without requiring AWS environment variables to be set

### Requirement 9: Data Migration

**User Story:** As a platform operator, I want existing SQLite data migrated to DynamoDB, so that no historical data is lost during the transition.

#### Acceptance Criteria

1. WHEN the migration script is executed, THE Migration_Script SHALL read all users, batches, feedbacks, and keywords from the SQLite database
2. WHEN the migration script processes records, THE Migration_Script SHALL transform each record into the DynamoDB single-table schema format preserving all field values including null fields
3. WHEN the migration script writes to DynamoDB, THE Migration_Script SHALL use batch write operations of no more than 25 items per request with exponential backoff on throttled requests up to a maximum of 5 retry attempts per batch
4. IF a record fails to write to DynamoDB after all retry attempts are exhausted, THEN THE Migration_Script SHALL log the failed record entity type and record ID and continue processing remaining records
5. WHEN the migration completes, THE Migration_Script SHALL output a summary report with total records read from SQLite, records successfully written, and records failed per entity type (users, batches, feedbacks, keywords)
6. WHEN the migration completes, THE Migration_Script SHALL compare the total record count per entity type in DynamoDB against the source SQLite count and report any discrepancies

### Requirement 10: IAuthProvider Interface Adaptation

**User Story:** As a developer, I want the IAuthProvider interface to accommodate Cognito's authentication model, so that the interface remains clean while supporting managed auth.

#### Acceptance Criteria

1. THE Cognito_Provider SHALL implement hash_password as a no-op that returns an empty string, since Cognito manages password hashing internally
2. THE Cognito_Provider SHALL implement verify_password as a no-op that returns False, since Cognito manages password verification internally
3. WHEN authenticate is called, THE Cognito_Provider SHALL delegate password verification entirely to the Cognito service using the USER_PASSWORD_AUTH flow and return an AuthResult with success=True and a valid AuthToken on successful authentication, or success=False with an error message on failure
4. WHEN validate_token is called, THE Cognito_Provider SHALL fetch the JWKS from the Cognito User Pool and cache the keys for up to 24 hours for subsequent validations; IF the token is expired, malformed, or the signature does not match any cached key, THEN validate_token SHALL return None
5. IF the Cognito service is unreachable during authenticate, THEN THE Cognito_Provider SHALL return an AuthResult with success=False and an error message indicating a service availability issue
