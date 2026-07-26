"""Unit tests for ComprehendNLPProvider.validate_text.

Validates: Requirements 1.1, 1.9, 1.10, 1.12
"""

from unittest.mock import patch

import pytest

from app.core.interfaces.nlp_provider import INLPProvider, NLPError


@pytest.fixture
def provider():
    """Create a ComprehendNLPProvider with a mocked boto3 client."""
    with patch("boto3.client") as mock_client:
        from app.infrastructure.nlp.comprehend_nlp_provider import (
            ComprehendNLPProvider,
        )

        instance = ComprehendNLPProvider(region="us-east-1")
        yield instance


class TestComprehendNLPProviderInterface:
    """Requirement 1.1: ComprehendNLPProvider implements INLPProvider."""

    def test_implements_inlp_provider(self, provider):
        assert isinstance(provider, INLPProvider)


class TestValidateTextEmpty:
    """Requirement 1.9: Empty/whitespace text returns texto_vacio."""

    def test_empty_string(self, provider):
        result = provider.validate_text("")
        assert result is not None
        assert result.reason == "texto_vacio"

    def test_whitespace_only(self, provider):
        result = provider.validate_text("   ")
        assert result is not None
        assert result.reason == "texto_vacio"

    def test_tabs_and_newlines_only(self, provider):
        result = provider.validate_text("\t\n\r")
        assert result is not None
        assert result.reason == "texto_vacio"


class TestValidateTextFewWords:
    """Requirement 1.10: Fewer than 2 significant words returns pocas_palabras."""

    def test_single_short_word(self, provider):
        """A single word with <=2 chars has zero significant words."""
        result = provider.validate_text("hi")
        assert result is not None
        assert result.reason == "pocas_palabras"

    def test_single_long_word(self, provider):
        """One significant word (>2 chars) is still less than 2."""
        result = provider.validate_text("hello")
        assert result is not None
        assert result.reason == "pocas_palabras"

    def test_multiple_short_words(self, provider):
        """Multiple words all <=2 chars means zero significant words."""
        result = provider.validate_text("a b c d")
        assert result is not None
        assert result.reason == "pocas_palabras"

    def test_one_long_one_short(self, provider):
        """One word >2 chars and one <=2 chars means only 1 significant word."""
        result = provider.validate_text("hello ab")
        assert result is not None
        assert result.reason == "pocas_palabras"

    def test_two_significant_words_valid(self, provider):
        """Two words >2 chars should pass this validation."""
        result = provider.validate_text("hello world")
        assert result is None


class TestValidateTextTooLong:
    """Requirement 1.12: Text exceeding 5000 UTF-8 bytes returns texto_muy_largo."""

    def test_exactly_5000_bytes_valid(self, provider):
        """Text at exactly 5000 UTF-8 bytes should be valid."""
        # 'a' is 1 byte in UTF-8; create text with enough significant words
        text = "word " * 1000  # 5000 bytes exactly (4 chars + space = 5 bytes × 1000)
        assert len(text.encode("utf-8")) == 5000
        result = provider.validate_text(text)
        assert result is None

    def test_exceeds_5000_bytes(self, provider):
        """Text over 5000 UTF-8 bytes returns texto_muy_largo."""
        text = "word " * 1001  # 5005 bytes
        assert len(text.encode("utf-8")) > 5000
        result = provider.validate_text(text)
        assert result is not None
        assert result.reason == "texto_muy_largo"

    def test_multibyte_chars_exceed_limit(self, provider):
        """Multi-byte UTF-8 characters can push text over the byte limit."""
        # 'ñ' is 2 bytes in UTF-8; construct text exceeding limit with multi-byte chars
        # Need 2 significant words first, then padding
        base = "hola mundo "  # 11 bytes, 2 significant words
        # Fill remaining with multi-byte chars to exceed 5000
        padding = "ñ" * 2500  # 5000 bytes for just the ñs
        text = base + padding
        assert len(text.encode("utf-8")) > 5000
        result = provider.validate_text(text)
        assert result is not None
        assert result.reason == "texto_muy_largo"


class TestValidateTextValidInput:
    """Valid inputs should return None."""

    def test_normal_spanish_text(self, provider):
        result = provider.validate_text("El servicio fue excelente")
        assert result is None

    def test_exactly_two_significant_words(self, provider):
        result = provider.validate_text("muy bueno")
        assert result is None


class TestAnalyzeSentimentNotImplemented:
    """Stub methods raise NotImplementedError."""

    def test_analyze_sentiment_raises(self, provider):
        with pytest.raises(NotImplementedError):
            provider.analyze_sentiment("texto de prueba")

    def test_extract_keywords_raises(self, provider):
        with pytest.raises(NotImplementedError):
            provider.extract_keywords("texto de prueba")
