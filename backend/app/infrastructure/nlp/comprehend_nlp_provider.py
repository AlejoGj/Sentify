"""AWS Comprehend NLP provider implementation."""

import boto3
from botocore.exceptions import ClientError

from app.core.interfaces.nlp_provider import INLPProvider, NLPError, SentimentResult


class ComprehendNLPProvider(INLPProvider):
    """NLP provider using AWS Comprehend for sentiment analysis and keyword extraction."""

    def __init__(self, region: str) -> None:
        """Initialize the Comprehend client.

        Args:
            region: AWS region name for the Comprehend service.
        """
        self._client = boto3.client("comprehend", region_name=region)

    def validate_text(self, text: str) -> NLPError | None:
        """Validate if text is processable. Returns None if valid.

        Performs local validation without calling the AWS API:
        - Empty or whitespace-only text → "texto_vacio"
        - Fewer than 2 significant words (>2 chars) → "pocas_palabras"
        - Text exceeding 5000 UTF-8 bytes → "texto_muy_largo"
        """
        # Check empty or whitespace-only text
        if not text or not text.strip():
            return NLPError(feedback_id="", reason="texto_vacio")

        # Check significant words: split on whitespace, count words with len > 2
        words = text.strip().split()
        significant_words = [w for w in words if len(w) > 2]

        if len(significant_words) < 2:
            return NLPError(feedback_id="", reason="pocas_palabras")

        # Check UTF-8 byte length limit
        if len(text.encode("utf-8")) > 5000:
            return NLPError(feedback_id="", reason="texto_muy_largo")

        return None

    def analyze_sentiment(self, text: str) -> SentimentResult:
        """Analyze sentiment of text using AWS Comprehend.

        Calls detect_sentiment with Spanish language, computes a polarity score
        from Positive - Negative scores, and classifies as positivo/negativo/neutro.

        Raises:
            RuntimeError: On AWS service errors or network failures.
        """
        try:
            response = self._client.detect_sentiment(Text=text, LanguageCode="es")
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            raise RuntimeError(
                f"AWS Comprehend error: {error_code}"
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"Error communicating with AWS Comprehend: {e}"
            ) from e

        sentiment_score = response["SentimentScore"]
        positive = sentiment_score["Positive"]
        negative = sentiment_score["Negative"]

        score = round(max(-1.0, min(1.0, positive - negative)), 2)

        if score > 0.2:
            classification = "positivo"
        elif score < -0.2:
            classification = "negativo"
        else:
            classification = "neutro"

        # Keywords will be populated via extract_keywords in task 2.3
        return SentimentResult(sentiment=classification, score=score, keywords=[])

    def extract_keywords(self, text: str, max_keywords: int = 10) -> list[str]:
        """Extract keywords from text using AWS Comprehend key phrase detection.

        Calls detect_key_phrases with Spanish language, filters to phrases >2 chars,
        sorts by confidence descending, normalizes to lowercase, and returns up to
        max_keywords results (clamped to 1-10).

        Returns an empty list for empty/whitespace input without calling AWS.

        Raises:
            RuntimeError: On AWS service errors or network failures.
        """
        # Return empty list for empty/whitespace input without calling AWS
        if not text or not text.strip():
            return []

        # Clamp max_keywords to range 1-10
        max_keywords = max(1, min(10, max_keywords))

        try:
            response = self._client.detect_key_phrases(Text=text, LanguageCode="es")
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            raise RuntimeError(
                f"AWS Comprehend keyword extraction failed: {error_code}"
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"Keyword extraction failed: {e}"
            ) from e

        key_phrases = response.get("KeyPhrases", [])

        # Filter to phrases with text longer than 2 characters
        filtered = [kp for kp in key_phrases if len(kp["Text"]) > 2]

        # Sort by confidence score descending
        filtered.sort(key=lambda kp: kp["Score"], reverse=True)

        # Normalize to lowercase and limit to max_keywords
        return [kp["Text"].lower() for kp in filtered[:max_keywords]]
