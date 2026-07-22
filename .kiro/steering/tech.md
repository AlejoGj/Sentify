# Sentify — Tech Stack & Build

## Backend (Python)

| Category | Technology |
|----------|-----------|
| Framework | FastAPI (async, Pydantic validation, auto OpenAPI) |
| ORM | SQLAlchemy |
| Database | SQLite (local dev), abstracted for migration |
| NLP | spaCy (`es_core_news_md`) + scikit-learn TF-IDF |
| Auth | bcrypt (password hashing) + PyJWT (tokens) |
| Testing | pytest + Hypothesis (property-based testing, min 100 examples) |
| Package mgmt | pyproject.toml (pip) |

## Frontend (TypeScript)

| Category | Technology |
|----------|-----------|
| Framework | React |
| Build tool | Vite |
| Charts | Chart.js + react-chartjs-2 |
| Word cloud | react-wordcloud |
| HTTP | Axios |
| Routing | react-router-dom |
| Testing | React Testing Library, Cypress or Playwright (e2e) |

## Common Commands

```bash
# Backend
cd backend
pip install -e ".[dev]"          # Install with dev dependencies
python -m spacy download es_core_news_md
uvicorn app.main:app --reload    # Run dev server
pytest                           # Run all tests
pytest tests/property/           # Run property-based tests only
pytest tests/unit/               # Run unit tests only

# Frontend
cd frontend
npm install
npm run dev                      # Vite dev server
npm run build                    # Production build
npm run test                     # Unit/component tests
npm run e2e                      # End-to-end tests
```

## Key Conventions

- Python code uses type hints everywhere
- Pydantic models for all request/response schemas
- Abstract Base Classes (ABC) for module interfaces
- Dependency injection via FastAPI `Depends()`
- API versioning prefix: `/api/v1/`
- OpenAPI spec auto-generated at `/docs`
- Hypothesis property tests reference design properties by number (e.g., Property 9)
- All keywords stored lowercase, >2 chars, excluding Spanish stopwords
