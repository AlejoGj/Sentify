from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SentimentResult:
    sentiment: str  # "positivo" | "neutro" | "negativo"
    score: float  # -1.0 a 1.0, precisión 2 decimales
    keywords: list[str]  # 1-10 palabras clave en minúsculas


@dataclass
class NLPError:
    feedback_id: str
    reason: str  # "texto_vacio" | "pocas_palabras" | "idioma_no_soportado"


class INLPProvider(ABC):
    @abstractmethod
    def analyze_sentiment(self, text: str) -> SentimentResult:
        """Analiza sentimiento de un texto individual."""
        ...

    @abstractmethod
    def extract_keywords(self, text: str, max_keywords: int = 10) -> list[str]:
        """Extrae palabras clave de un texto."""
        ...

    @abstractmethod
    def validate_text(self, text: str) -> NLPError | None:
        """Valida si el texto es procesable. Retorna None si es válido."""
        ...
