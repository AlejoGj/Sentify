# Implementation Plan: Sentiment Analysis Platform (Sentify)

## Overview

Implementación de la plataforma Sentify siguiendo la arquitectura de capas desacopladas definida en el diseño. Se comienza con la estructura del proyecto y las interfaces abstractas, se implementan las capas de infraestructura (storage, auth, NLP), luego los servicios de negocio y la API REST, y finalmente el frontend React con dashboard interactivo. El backend usa Python (FastAPI + spaCy + SQLAlchemy) y el frontend usa TypeScript (React + Chart.js).

## Tasks

- [x] 1. Set up project structure and core interfaces
  - [x] 1.1 Create backend project structure and dependencies
    - Create directory structure following the design (`backend/app/`, `core/`, `infrastructure/`, `api/`, `utils/`, `tests/`)
    - Create `pyproject.toml` with dependencies: fastapi, uvicorn, sqlalchemy, pyjwt, bcrypt, spacy, scikit-learn, hypothesis, pytest
    - Create `backend/app/__init__.py`, `backend/app/main.py` (FastAPI app entry point), `backend/app/config.py`
    - _Requirements: 8.1, 8.2, 8.3_

  - [x] 1.2 Define abstract interfaces (INLPProvider, IAuthProvider, IStorageProvider)
    - Create `backend/app/core/interfaces/nlp_provider.py` with `INLPProvider` ABC, `SentimentResult`, and `NLPError` dataclasses
    - Create `backend/app/core/interfaces/auth_provider.py` with `IAuthProvider` ABC, `AuthToken`, and `AuthResult` dataclasses
    - Create `backend/app/core/interfaces/storage_provider.py` with `IStorageProvider` ABC
    - All interfaces must match the exact signatures defined in the design document
    - _Requirements: 8.1, 8.2, 8.3, 8.5_

  - [x] 1.3 Create Pydantic models and data schemas
    - Create `backend/app/core/models/user.py`, `batch.py`, `feedback.py`, `keyword.py` with SQLAlchemy ORM models
    - Create Pydantic request/response schemas (`LoginRequest`, `LoginResponse`, `BatchStatusResponse`, `FeedbackResponse`, `BatchSummaryResponse`, `KeywordResponse`, `PaginatedResponse`)
    - Create `backend/app/core/models/__init__.py` with exports
    - _Requirements: 1.1, 2.1, 3.2, 3.3, 5.1_

  - [x] 1.4 Set up testing framework and configuration
    - Create `backend/tests/conftest.py` with shared fixtures (in-memory SQLite DB, mock providers)
    - Create `backend/tests/unit/`, `backend/tests/integration/`, `backend/tests/property/` directories with `__init__.py`
    - Configure pytest in `pyproject.toml` with hypothesis settings (min 100 examples)
    - _Requirements: 8.5_

- [x] 2. Implement storage layer (SQLite + SQLAlchemy)
  - [x] 2.1 Implement database setup and SQLAlchemy models
    - Create `backend/app/infrastructure/storage/database.py` with SQLAlchemy engine, session factory, and Base
    - Define SQL tables matching the ER diagram: `users`, `batches`, `feedbacks`, `keywords`
    - Add all indexes defined in the design (idx_batches_user_id, idx_feedbacks_batch_id, idx_feedbacks_score, idx_keywords_word, etc.)
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 2.2 Implement SQLiteStorageProvider
    - Create `backend/app/infrastructure/storage/sqlite_storage_provider.py` implementing `IStorageProvider`
    - Implement all methods: `create_batch`, `update_batch_status`, `store_feedback`, `get_batch_summary`, `get_feedbacks_by_keyword`, `get_top_keywords`, `get_urgent_feedbacks`, `get_user_batches`, `create_user`, `get_user_by_email`, `increment_failed_attempts`, `reset_failed_attempts`, `lock_account`
    - Use UUID4 for IDs, enforce text max 5000 chars, keywords in lowercase
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.3, 6.4, 7.1, 7.4_

  - [x] 2.3 Write property test for feedback text persistence round-trip
    - **Property 12: Feedback text persistence round-trip**
    - **Validates: Requirements 5.1, 5.4**

  - [x] 2.4 Write property test for batch history ordering
    - **Property 13: Batch history ordering**
    - **Validates: Requirements 5.6**

  - [ ] 2.5 Write property test for keyword filtering with pagination
    - **Property 14: Keyword filtering with pagination**
    - **Validates: Requirements 6.3**

  - [ ] 2.6 Write property test for top-N keyword selection
    - **Property 15: Top-N keyword selection**
    - **Validates: Requirements 6.4**

  - [ ] 2.7 Write property test for urgency classification and triage ordering
    - **Property 16: Urgency classification and triage ordering**
    - **Validates: Requirements 7.1, 7.4**

- [x] 3. Implement authentication module
  - [x] 3.1 Implement LocalAuthProvider
    - Create `backend/app/infrastructure/auth/local_auth_provider.py` implementing `IAuthProvider`
    - Implement `hash_password` with bcrypt, `verify_password`, `authenticate` (with lockout logic: 5 attempts → 15 min lock), `validate_token` with PyJWT (30 min expiry)
    - Ensure error messages are generic (not revealing which field is wrong)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6_

  - [x] 3.2 Write property test for password hashing round-trip
    - **Property 1: Password hashing round-trip**
    - **Validates: Requirements 1.4**

  - [x] 3.3 Write property test for token validity window
    - **Property 2: Token validity window**
    - **Validates: Requirements 1.1, 1.3**

  - [x] 3.4 Write property test for generic error message on invalid credentials
    - **Property 3: Generic error message on invalid credentials**
    - **Validates: Requirements 1.2**

  - [x] 3.5 Write property test for account lockout at threshold
    - **Property 4: Account lockout at threshold**
    - **Validates: Requirements 1.6**

- [x] 4. Checkpoint - Ensure storage and auth tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement CSV validator
  - [x] 5.1 Implement CSV validation logic
    - Create `backend/app/utils/csv_parser.py` with `validate_csv` function
    - Implement validation: extension check (.csv), encoding detection (UTF-8/Latin-1), column detection (set: "texto", "comentario", "review", "comment", "feedback"), size limit (10 MB), row limit (50,000)
    - Return `CSVValidationResult` dataclass with detected column name or specific error reason
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 5.2 Write property test for CSV validation accepts recognized columns
    - **Property 5: CSV validation accepts recognized column names**
    - **Validates: Requirements 2.1, 2.2**

  - [x] 5.3 Write property test for CSV validation rejects invalid files
    - **Property 6: CSV validation rejects invalid files with specific reason**
    - **Validates: Requirements 2.3, 2.4**

- [x] 6. Implement NLP engine
  - [x] 6.1 Implement SpaCyNLPProvider
    - Create `backend/app/infrastructure/nlp/spacy_nlp_provider.py` implementing `INLPProvider`
    - Implement `validate_text`: check empty text, < 2 significant words, non-Spanish language detection
    - Implement `analyze_sentiment`: classify as positivo/neutro/negativo with score [-1.0, 1.0], enforce score-classification consistency (positivo > 0.2, negativo < -0.2, neutro -0.2 to 0.2)
    - Implement `extract_keywords`: TF-IDF based, 1-10 keywords, exclude stopwords, >2 chars, lowercase
    - Use spaCy `es_core_news_md` model and scikit-learn `TfidfVectorizer`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 4.1, 4.2, 4.3, 4.4, 4.5_

  - [ ]* 6.2 Write property test for NLP output validity invariants
    - **Property 8: NLP output validity invariants**
    - **Validates: Requirements 3.2, 3.3**

  - [ ]* 6.3 Write property test for score-classification consistency
    - **Property 9: Score-classification consistency**
    - **Validates: Requirements 3.4, 3.5, 3.6**

  - [ ]* 6.4 Write property test for NLP error handling for invalid text
    - **Property 10: NLP error handling for invalid text**
    - **Validates: Requirements 3.7, 3.8**

  - [ ]* 6.5 Write property test for keyword extraction invariants
    - **Property 11: Keyword extraction invariants**
    - **Validates: Requirements 4.1, 4.2, 4.4**

- [x] 7. Implement batch processing service
  - [x] 7.1 Implement BatchService orchestrator
    - Create `backend/app/core/services/batch_service.py` with `BatchService` class
    - Implement CSV upload flow: validate → create batch → parse rows → process each via NLP → store results → update batch status
    - Handle partial failures: mark individual feedbacks as error, continue processing, update `error_rows` count
    - Ensure `processed_count + error_count == total_rows` invariant
    - _Requirements: 2.1, 2.5, 2.6, 2.7, 3.1, 3.7, 5.1, 5.5_

  - [ ]* 7.2 Write property test for partial row processing
    - **Property 7: Partial row processing preserves valid rows**
    - **Validates: Requirements 2.7**

- [x] 8. Implement API layer (FastAPI routes)
  - [x] 8.1 Implement auth endpoints
    - Create `backend/app/api/routes/auth.py` with `POST /api/v1/auth/login` and `POST /api/v1/auth/register`
    - Implement JWT middleware in `backend/app/api/middleware/auth_middleware.py`
    - Return appropriate error codes: 401 for invalid credentials, 423 for locked account
    - Show `company_name` in login response
    - _Requirements: 1.1, 1.2, 1.5, 1.6_

  - [x] 8.2 Implement batch endpoints
    - Create `backend/app/api/routes/batches.py` with all batch-related endpoints
    - `POST /api/v1/batches/upload`: accept multipart file, validate, return 202 + batch_id
    - `GET /api/v1/batches`: paginated user batch history
    - `GET /api/v1/batches/{id}/status`: batch processing status
    - `GET /api/v1/batches/{id}/summary`: sentiment distribution summary
    - `GET /api/v1/batches/{id}/keywords`: top 20 keywords
    - `GET /api/v1/batches/{id}/feedbacks`: paginated feedbacks with keyword filter
    - `GET /api/v1/batches/{id}/triage`: urgent feedbacks (score < -0.7)
    - _Requirements: 2.1, 2.3, 2.4, 2.6, 5.6, 6.1, 6.3, 6.4, 7.1, 7.4_

  - [x] 8.3 Set up dependency injection and app wiring
    - Create `backend/app/dependencies.py` with FastAPI dependency injection
    - Wire `INLPProvider` → `SpaCyNLPProvider`, `IAuthProvider` → `LocalAuthProvider`, `IStorageProvider` → `SQLiteStorageProvider`
    - Configure CORS middleware for frontend access
    - Enable OpenAPI docs at `/docs`
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [x] 8.4 Write unit tests for API endpoints
    - Test login success/failure responses, token validation
    - Test CSV upload validation errors (422), batch status transitions
    - Test pagination and filtering on dashboard endpoints
    - _Requirements: 1.1, 1.2, 2.3, 6.3, 7.4_

- [ ] 9. Checkpoint - Ensure backend tests pass end-to-end
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document using Hypothesis
- Unit tests validate specific examples and edge cases
- Backend uses Python (FastAPI, spaCy, SQLAlchemy, bcrypt, PyJWT)
- Frontend uses TypeScript (React, Chart.js, react-wordcloud, Vite)
- The architecture ensures module interchangeability per Requirement 8

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.4"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["2.1", "3.1", "5.1"] },
    { "id": 3, "tasks": ["2.2", "3.2", "3.3", "3.4", "3.5", "5.2", "5.3"] },
    { "id": 4, "tasks": ["2.3", "2.4", "2.5", "2.6", "2.7", "6.1"] },
    { "id": 5, "tasks": ["6.2", "6.3", "6.4", "6.5", "7.1"] },
    { "id": 6, "tasks": ["7.2", "8.1", "8.2", "8.3"] },
    { "id": 7, "tasks": ["8.4"] }
  ]
}
```
