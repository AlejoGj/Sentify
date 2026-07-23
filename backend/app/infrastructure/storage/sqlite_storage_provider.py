"""SQLite storage provider implementation."""

import logging
import math
import uuid
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.interfaces.storage_provider import IStorageProvider
from app.core.models import Batch, Feedback, Keyword, User

logger = logging.getLogger(__name__)


class SQLiteStorageProvider(IStorageProvider):
    """Concrete storage implementation using SQLAlchemy + SQLite."""

    def __init__(self, session_factory):
        """Accept a session factory (callable that returns a Session)."""
        self._session_factory = session_factory

    def create_batch(self, user_id: str, filename: str) -> str:
        """Crea un lote. Retorna batch_id."""
        session: Session = self._session_factory()
        try:
            batch_id = str(uuid.uuid4())
            batch = Batch(
                id=batch_id,
                user_id=user_id,
                filename=filename,
                status="pending",
                uploaded_at=datetime.utcnow(),
            )
            session.add(batch)
            session.commit()
            return batch_id
        except Exception as e:
            session.rollback()
            logger.error("Error creating batch: %s", e)
            raise
        finally:
            session.close()

    def update_batch_status(self, batch_id: str, status: str) -> None:
        """Actualiza estado del lote."""
        session: Session = self._session_factory()
        try:
            batch = session.query(Batch).filter(Batch.id == batch_id).first()
            if batch is None:
                logger.warning("Batch %s not found for status update", batch_id)
                return
            batch.status = status
            if status == "completed":
                batch.completed_at = datetime.utcnow()
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Error updating batch status: %s", e)
            raise
        finally:
            session.close()

    def store_feedback(
        self,
        batch_id: str,
        text: str,
        sentiment: str,
        score: float,
        keywords: list[str],
        status: str,
    ) -> str:
        """Almacena un feedback procesado. Retorna feedback_id."""
        session: Session = self._session_factory()
        try:
            feedback_id = str(uuid.uuid4())
            # Truncate text to 5000 chars
            truncated_text = text[:5000]

            feedback = Feedback(
                id=feedback_id,
                batch_id=batch_id,
                original_text=truncated_text,
                sentiment=sentiment,
                score=score,
                status=status,
                analyzed_at=datetime.utcnow(),
            )
            session.add(feedback)

            # Create keyword records (lowercase, >2 chars only)
            for kw in keywords:
                word = kw.lower().strip()
                if len(word) > 2:
                    keyword_record = Keyword(
                        id=str(uuid.uuid4()),
                        feedback_id=feedback_id,
                        word=word,
                    )
                    session.add(keyword_record)

            session.commit()
            return feedback_id
        except Exception as e:
            session.rollback()
            logger.error("Error storing feedback: %s", e)
            raise
        finally:
            session.close()

    def get_batch_summary(self, batch_id: str) -> dict:
        """Retorna resumen con distribución de sentimientos."""
        session: Session = self._session_factory()
        try:
            feedbacks = (
                session.query(Feedback)
                .filter(Feedback.batch_id == batch_id)
                .all()
            )
            total = len(feedbacks)
            positivo = sum(1 for f in feedbacks if f.sentiment == "positivo")
            neutro = sum(1 for f in feedbacks if f.sentiment == "neutro")
            negativo = sum(1 for f in feedbacks if f.sentiment == "negativo")

            sentiment_distribution = {
                "positivo": positivo,
                "neutro": neutro,
                "negativo": negativo,
            }

            sentiment_percentages = {}
            if total > 0:
                sentiment_percentages = {
                    "positivo": round((positivo / total) * 100, 2),
                    "neutro": round((neutro / total) * 100, 2),
                    "negativo": round((negativo / total) * 100, 2),
                }
            else:
                sentiment_percentages = {
                    "positivo": 0.0,
                    "neutro": 0.0,
                    "negativo": 0.0,
                }

            urgent_count = sum(
                1 for f in feedbacks if f.score is not None and f.score < -0.7
            )

            return {
                "batch_id": batch_id,
                "total_feedbacks": total,
                "sentiment_distribution": sentiment_distribution,
                "sentiment_percentages": sentiment_percentages,
                "urgent_count": urgent_count,
            }
        except Exception as e:
            logger.error("Error getting batch summary: %s", e)
            raise
        finally:
            session.close()

    def get_feedbacks_by_keyword(
        self, batch_id: str, keyword: str, page: int, page_size: int = 20
    ) -> dict:
        """Retorna feedbacks asociados a una palabra clave, paginados."""
        session: Session = self._session_factory()
        try:
            keyword_lower = keyword.lower()

            # Query feedbacks that have a matching keyword in this batch
            query = (
                session.query(Feedback)
                .join(Keyword, Keyword.feedback_id == Feedback.id)
                .filter(Feedback.batch_id == batch_id)
                .filter(Keyword.word == keyword_lower)
            )

            total = query.count()
            offset = (page - 1) * page_size
            feedbacks = query.offset(offset).limit(page_size).all()

            items = []
            for f in feedbacks:
                items.append({
                    "id": f.id,
                    "original_text": f.original_text,
                    "sentiment": f.sentiment,
                    "score": f.score,
                    "keywords": [kw.word for kw in f.keywords],
                    "analyzed_at": f.analyzed_at.isoformat() if f.analyzed_at else None,
                })

            total_pages = math.ceil(total / page_size) if page_size > 0 else 0

            return {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
            }
        except Exception as e:
            logger.error("Error getting feedbacks by keyword: %s", e)
            raise
        finally:
            session.close()

    def get_top_keywords(self, batch_id: str, limit: int = 20) -> list[dict]:
        """Retorna las top N palabras clave con frecuencia."""
        session: Session = self._session_factory()
        try:
            results = (
                session.query(Keyword.word, func.count(Keyword.id).label("frequency"))
                .join(Feedback, Feedback.id == Keyword.feedback_id)
                .filter(Feedback.batch_id == batch_id)
                .group_by(Keyword.word)
                .order_by(func.count(Keyword.id).desc())
                .limit(limit)
                .all()
            )

            return [{"word": row.word, "frequency": row.frequency} for row in results]
        except Exception as e:
            logger.error("Error getting top keywords: %s", e)
            raise
        finally:
            session.close()

    def get_urgent_feedbacks(
        self, batch_id: str, threshold: float, page: int, page_size: int = 10
    ) -> dict:
        """Retorna feedbacks con score menor al threshold, paginados."""
        session: Session = self._session_factory()
        try:
            query = (
                session.query(Feedback)
                .filter(Feedback.batch_id == batch_id)
                .filter(Feedback.score < threshold)
                .filter(Feedback.status == "success")
                .order_by(Feedback.score.asc())
            )

            total = query.count()
            offset = (page - 1) * page_size
            feedbacks = query.offset(offset).limit(page_size).all()

            items = []
            for f in feedbacks:
                items.append({
                    "id": f.id,
                    "original_text": f.original_text,
                    "sentiment": f.sentiment,
                    "score": f.score,
                    "keywords": [kw.word for kw in f.keywords],
                    "analyzed_at": f.analyzed_at.isoformat() if f.analyzed_at else None,
                })

            total_pages = math.ceil(total / page_size) if page_size > 0 else 0

            return {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
            }
        except Exception as e:
            logger.error("Error getting urgent feedbacks: %s", e)
            raise
        finally:
            session.close()

    def get_user_batches(
        self, user_id: str, page: int, page_size: int = 10
    ) -> dict:
        """Retorna historial de lotes del usuario, ordenados por fecha desc."""
        session: Session = self._session_factory()
        try:
            query = (
                session.query(Batch)
                .filter(Batch.user_id == user_id)
                .order_by(Batch.uploaded_at.desc())
            )

            total = query.count()
            offset = (page - 1) * page_size
            batches = query.offset(offset).limit(page_size).all()

            items = []
            for b in batches:
                items.append({
                    "id": b.id,
                    "filename": b.filename,
                    "status": b.status,
                    "total_rows": b.total_rows,
                    "processed_rows": b.processed_rows,
                    "error_rows": b.error_rows,
                    "uploaded_at": b.uploaded_at.isoformat() if b.uploaded_at else None,
                    "completed_at": b.completed_at.isoformat() if b.completed_at else None,
                })

            total_pages = math.ceil(total / page_size) if page_size > 0 else 0

            return {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
            }
        except Exception as e:
            logger.error("Error getting user batches: %s", e)
            raise
        finally:
            session.close()

    def create_user(
        self, email: str, password_hash: str, company_name: str
    ) -> str:
        """Crea un usuario. Retorna user_id."""
        session: Session = self._session_factory()
        try:
            user_id = str(uuid.uuid4())
            user = User(
                id=user_id,
                email=email,
                password_hash=password_hash,
                company_name=company_name,
                failed_attempts=0,
                locked_until=None,
                created_at=datetime.utcnow(),
            )
            session.add(user)
            session.commit()
            return user_id
        except Exception as e:
            session.rollback()
            logger.error("Error creating user: %s", e)
            raise
        finally:
            session.close()

    def get_user_by_email(self, email: str) -> dict | None:
        """Busca usuario por email."""
        session: Session = self._session_factory()
        try:
            user = session.query(User).filter(User.email == email).first()
            if user is None:
                return None
            return {
                "id": user.id,
                "email": user.email,
                "password_hash": user.password_hash,
                "company_name": user.company_name,
                "failed_attempts": user.failed_attempts,
                "locked_until": user.locked_until,
                "created_at": user.created_at,
            }
        except Exception as e:
            logger.error("Error getting user by email: %s", e)
            raise
        finally:
            session.close()

    def increment_failed_attempts(self, user_id: str) -> int:
        """Incrementa intentos fallidos. Retorna total actual."""
        session: Session = self._session_factory()
        try:
            user = session.query(User).filter(User.id == user_id).first()
            if user is None:
                logger.warning("User %s not found for increment_failed_attempts", user_id)
                return 0
            user.failed_attempts += 1
            session.commit()
            return user.failed_attempts
        except Exception as e:
            session.rollback()
            logger.error("Error incrementing failed attempts: %s", e)
            raise
        finally:
            session.close()

    def reset_failed_attempts(self, user_id: str) -> None:
        """Resetea intentos fallidos a 0."""
        session: Session = self._session_factory()
        try:
            user = session.query(User).filter(User.id == user_id).first()
            if user is None:
                logger.warning("User %s not found for reset_failed_attempts", user_id)
                return
            user.failed_attempts = 0
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Error resetting failed attempts: %s", e)
            raise
        finally:
            session.close()

    def lock_account(self, user_id: str, until: datetime) -> None:
        """Bloquea cuenta hasta la fecha indicada."""
        session: Session = self._session_factory()
        try:
            user = session.query(User).filter(User.id == user_id).first()
            if user is None:
                logger.warning("User %s not found for lock_account", user_id)
                return
            user.locked_until = until
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Error locking account: %s", e)
            raise
        finally:
            session.close()

    def update_batch_counts(
        self, batch_id: str, total_rows: int, processed_rows: int, error_rows: int
    ) -> None:
        """Actualiza los contadores de filas del lote."""
        session: Session = self._session_factory()
        try:
            batch = session.query(Batch).filter(Batch.id == batch_id).first()
            if batch is None:
                logger.warning("Batch %s not found for update_batch_counts", batch_id)
                return
            batch.total_rows = total_rows
            batch.processed_rows = processed_rows
            batch.error_rows = error_rows
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Error updating batch counts: %s", e)
            raise
        finally:
            session.close()

    def store_feedback_error(
        self, batch_id: str, text: str, error_reason: str
    ) -> str:
        """Almacena un feedback con error. Retorna feedback_id."""
        session: Session = self._session_factory()
        try:
            feedback_id = str(uuid.uuid4())
            truncated_text = text[:5000]

            feedback = Feedback(
                id=feedback_id,
                batch_id=batch_id,
                original_text=truncated_text,
                sentiment=None,
                score=None,
                status="error",
                error_reason=error_reason,
                analyzed_at=datetime.utcnow(),
            )
            session.add(feedback)
            session.commit()
            return feedback_id
        except Exception as e:
            session.rollback()
            logger.error("Error storing feedback error: %s", e)
            raise
        finally:
            session.close()
