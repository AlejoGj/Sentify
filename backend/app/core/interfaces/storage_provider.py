from abc import ABC, abstractmethod
from datetime import datetime


class IStorageProvider(ABC):
    @abstractmethod
    def create_batch(self, user_id: str, filename: str) -> str:
        """Crea un lote. Retorna batch_id."""
        ...

    @abstractmethod
    def update_batch_status(self, batch_id: str, status: str) -> None:
        """Actualiza estado del lote."""
        ...

    @abstractmethod
    def store_feedback(self, batch_id: str, text: str, sentiment: str,
                       score: float, keywords: list[str], status: str) -> str:
        """Almacena un feedback procesado. Retorna feedback_id."""
        ...

    @abstractmethod
    def get_batch_summary(self, batch_id: str) -> dict:
        """Retorna resumen con distribución de sentimientos."""
        ...

    @abstractmethod
    def get_feedbacks_by_keyword(self, batch_id: str, keyword: str,
                                 page: int, page_size: int = 20) -> dict:
        """Retorna feedbacks asociados a una palabra clave, paginados."""
        ...

    @abstractmethod
    def get_top_keywords(self, batch_id: str, limit: int = 20) -> list[dict]:
        """Retorna las top N palabras clave con frecuencia."""
        ...

    @abstractmethod
    def get_urgent_feedbacks(self, batch_id: str, threshold: float,
                             page: int, page_size: int = 10) -> dict:
        """Retorna feedbacks con score menor al threshold, paginados."""
        ...

    @abstractmethod
    def get_user_batches(self, user_id: str, page: int,
                         page_size: int = 10) -> dict:
        """Retorna historial de lotes del usuario, ordenados por fecha desc."""
        ...

    @abstractmethod
    def create_user(self, email: str, password_hash: str,
                    company_name: str) -> str:
        """Crea un usuario. Retorna user_id."""
        ...

    @abstractmethod
    def get_user_by_email(self, email: str) -> dict | None:
        """Busca usuario por email."""
        ...

    @abstractmethod
    def increment_failed_attempts(self, user_id: str) -> int:
        """Incrementa intentos fallidos. Retorna total actual."""
        ...

    @abstractmethod
    def reset_failed_attempts(self, user_id: str) -> None:
        """Resetea intentos fallidos a 0."""
        ...

    @abstractmethod
    def lock_account(self, user_id: str, until: datetime) -> None:
        """Bloquea cuenta hasta la fecha indicada."""
        ...

    @abstractmethod
    def update_batch_counts(
        self, batch_id: str, total_rows: int, processed_rows: int, error_rows: int
    ) -> None:
        """Actualiza los contadores de filas del lote."""
        ...

    @abstractmethod
    def store_feedback_error(
        self, batch_id: str, text: str, error_reason: str
    ) -> str:
        """Almacena un feedback con error. Retorna feedback_id."""
        ...
