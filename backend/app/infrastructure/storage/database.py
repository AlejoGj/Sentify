"""Database engine, session factory, and initialization."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.core.models.base import Base

# Import all models so they register with Base.metadata
from app.core.models.user import User  # noqa: F401
from app.core.models.batch import Batch  # noqa: F401
from app.core.models.feedback import Feedback  # noqa: F401
from app.core.models.keyword import Keyword  # noqa: F401

# Engine creation
engine = create_engine(settings.database_url, echo=False)

# Session factory
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_session() -> Session:
    """Get a new database session."""
    return SessionLocal()


def init_db() -> None:
    """Create all tables and indexes."""
    Base.metadata.create_all(bind=engine)
