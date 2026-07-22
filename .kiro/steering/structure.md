# Sentify — Project Structure

```
sentify/
├── backend/
│   ├── app/
│   │   ├── main.py                      # FastAPI app entry point
│   │   ├── config.py                    # Env vars and settings
│   │   ├── dependencies.py              # DI wiring (providers → interfaces)
│   │   ├── api/
│   │   │   ├── routes/
│   │   │   │   ├── auth.py              # POST /login, /register
│   │   │   │   ├── batches.py           # Upload, status, summary, keywords, feedbacks, triage
│   │   │   │   └── dashboard.py         # Dashboard aggregation endpoints
│   │   │   └── middleware/
│   │   │       └── auth_middleware.py    # JWT validation middleware
│   │   ├── core/
│   │   │   ├── interfaces/              # Abstract contracts (ABC)
│   │   │   │   ├── nlp_provider.py      # INLPProvider
│   │   │   │   ├── auth_provider.py     # IAuthProvider
│   │   │   │   └── storage_provider.py  # IStorageProvider
│   │   │   ├── models/                  # SQLAlchemy ORM + Pydantic schemas
│   │   │   │   ├── user.py
│   │   │   │   ├── batch.py
│   │   │   │   ├── feedback.py
│   │   │   │   └── keyword.py
│   │   │   └── services/                # Business logic orchestrators
│   │   │       ├── batch_service.py
│   │   │       ├── nlp_service.py
│   │   │       └── auth_service.py
│   │   ├── infrastructure/              # Concrete implementations
│   │   │   ├── nlp/
│   │   │   │   └── spacy_nlp_provider.py
│   │   │   ├── auth/
│   │   │   │   └── local_auth_provider.py
│   │   │   └── storage/
│   │   │       ├── sqlite_storage_provider.py
│   │   │       └── database.py          # Engine, session, Base
│   │   └── utils/
│   │       ├── csv_parser.py            # CSV validation logic
│   │       └── validators.py
│   ├── tests/
│   │   ├── conftest.py                  # Shared fixtures
│   │   ├── unit/
│   │   ├── integration/
│   │   └── property/                    # Hypothesis property tests
│   ├── pyproject.toml
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── Auth/                    # LoginForm
│   │   │   ├── Dashboard/              # BatchHistory, FeedbackList, EmptyState
│   │   │   ├── Upload/                 # CSVUploader
│   │   │   ├── Charts/                 # SentimentCharts, WordCloud
│   │   │   └── Triage/                 # TriagePanel
│   │   ├── services/
│   │   │   └── api.ts                   # Axios client with JWT interceptor
│   │   ├── hooks/
│   │   └── types/                       # TypeScript interfaces
│   ├── package.json
│   └── vite.config.ts
└── docs/
    └── openapi.yaml
```

## Architecture Principles

- **Layered separation**: API routes → Services → Interfaces → Infrastructure
- **Interface-driven**: All external concerns (NLP, auth, storage) sit behind ABCs in `core/interfaces/`
- **Implementations are swappable**: Changing from SQLite to PostgreSQL or from local NLP to AWS Comprehend only requires a new file in `infrastructure/` and a config change in `dependencies.py`
- **No cross-imports between infrastructure modules**: Each implementation only imports its own interface
- **Frontend organized by feature**: Components grouped by domain (Auth, Upload, Charts, Triage, Dashboard)
