"""spaCy NLP provider implementation."""

import spacy
from sklearn.feature_extraction.text import TfidfVectorizer

from app.core.interfaces.nlp_provider import INLPProvider, NLPError, SentimentResult


# Polarity lexicon for Spanish sentiment analysis
_POSITIVE_WORDS: set[str] = {
    "excelente", "bueno", "buena", "genial", "increíble", "fantástico", "fantástica",
    "maravilloso", "maravillosa", "perfecto", "perfecta", "mejor", "encanta",
    "recomendable", "satisfecho", "satisfecha", "feliz", "contento", "contenta",
    "agradable", "positivo", "positiva", "calidad", "eficiente", "rápido", "rápida",
    "cómodo", "cómoda", "útil", "práctico", "práctica", "fácil", "amable",
    "profesional", "destacable", "sobresaliente", "superior", "óptimo", "óptima",
    "excepcional", "brillante", "espectacular", "magnífico", "magnífica",
    "estupendo", "estupenda", "fenomenal", "impresionante", "grandioso", "grandiosa",
    "extraordinario", "extraordinaria", "favorable", "gusta", "gustar", "gustó",
    "encantó", "amor", "amar", "adorar", "disfrutar", "disfruto", "disfruté",
    "celebrar", "logro", "éxito", "triunfo", "alegría", "placer",
}

_NEGATIVE_WORDS: set[str] = {
    "malo", "mala", "terrible", "horrible", "pésimo", "pésima", "peor", "odio",
    "decepcionante", "insatisfecho", "insatisfecha", "enojado", "enojada",
    "molesto", "molesta", "frustrado", "frustrada", "negativo", "negativa",
    "lento", "lenta", "incómodo", "incómoda", "inútil", "difícil", "complicado",
    "complicada", "deficiente", "mediocre", "deplorable", "desastroso", "desastrosa",
    "inaceptable", "vergonzoso", "vergonzosa", "espantoso", "espantosa",
    "asqueroso", "asquerosa", "nefasto", "nefasta", "fatal", "fracaso",
    "problema", "problemas", "error", "errores", "fallo", "fallos", "queja",
    "quejas", "reclamo", "reclamos", "basura", "porquería", "chatarra",
    "estafa", "engaño", "mentira", "robo", "abuso", "negligencia",
    "desprecio", "asco", "odiar", "detestar", "sufrir", "sufrimiento",
    "dolor", "tristeza", "angustia", "rabia", "furia", "indignación",
}

_INTENSIFIERS: set[str] = {
    "muy", "bastante", "demasiado", "extremadamente", "sumamente",
    "increíblemente", "totalmente", "completamente", "absolutamente",
    "realmente", "verdaderamente", "enormemente",
}

_NEGATION_WORDS: set[str] = {
    "no", "nunca", "jamás", "tampoco", "nada", "ningún", "ninguno",
    "ninguna", "ni", "sin",
}


class SpaCyNLPProvider(INLPProvider):
    """NLP provider using spaCy es_core_news_md and scikit-learn TF-IDF."""

    def __init__(self) -> None:
        self._nlp = spacy.load("es_core_news_md")
        self._stopwords: set[str] = self._nlp.Defaults.stop_words

    def validate_text(self, text: str) -> NLPError | None:
        """Validate if text is processable. Returns None if valid."""
        # Check empty text (0 chars or only whitespace)
        if not text or not text.strip():
            return NLPError(feedback_id="", reason="texto_vacio")

        # Count significant words (excluding stopwords, >2 chars)
        doc = self._nlp(text.strip())
        significant_words = [
            token for token in doc
            if token.text.lower() not in self._stopwords
            and len(token.text) > 2
            and token.is_alpha
        ]

        if len(significant_words) < 2:
            return NLPError(feedback_id="", reason="pocas_palabras")

        # Language detection: check vocabulary coverage with the Spanish model
        if not self._is_spanish(doc):
            return NLPError(feedback_id="", reason="idioma_no_soportado")

        return None

    def analyze_sentiment(self, text: str) -> SentimentResult:
        """Analyze sentiment of text and return classification with score and keywords."""
        doc = self._nlp(text.strip())
        raw_score = self._compute_polarity_score(doc)

        # Clamp to [-1.0, 1.0] and round to 2 decimal places
        score = round(max(-1.0, min(1.0, raw_score)), 2)

        # Enforce score-classification consistency
        sentiment = self._classify_from_score(score)

        # Extract keywords
        keywords = self.extract_keywords(text)

        return SentimentResult(
            sentiment=sentiment,
            score=score,
            keywords=keywords,
        )

    def extract_keywords(self, text: str, max_keywords: int = 10) -> list[str]:
        """Extract keywords using TF-IDF, filtering by POS and stopwords."""
        max_keywords = max(1, min(10, max_keywords))

        doc = self._nlp(text.strip())

        # Get candidate tokens: nouns, adjectives, verbs; not stopwords; >2 chars; alpha
        candidates = [
            token.text.lower()
            for token in doc
            if token.pos_ in {"NOUN", "ADJ", "VERB"}
            and token.text.lower() not in self._stopwords
            and len(token.text) > 2
            and token.is_alpha
        ]

        if not candidates:
            return []

        # Use TF-IDF to score candidates
        unique_candidates = list(dict.fromkeys(candidates))  # preserve order, deduplicate

        if len(unique_candidates) <= max_keywords:
            return unique_candidates[:max_keywords]

        # Use TfidfVectorizer on the full text to get term importance
        try:
            vectorizer = TfidfVectorizer(
                stop_words=list(self._stopwords),
                token_pattern=r"(?u)\b[a-záéíóúüñ]{3,}\b",
                lowercase=True,
            )
            tfidf_matrix = vectorizer.fit_transform([text.strip().lower()])
            feature_names = vectorizer.get_feature_names_out()
            scores = tfidf_matrix.toarray()[0]

            # Build score map
            score_map: dict[str, float] = dict(zip(feature_names, scores))

            # Sort candidates by TF-IDF score (descending)
            scored_candidates = sorted(
                unique_candidates,
                key=lambda w: score_map.get(w, 0.0),
                reverse=True,
            )
            return scored_candidates[:max_keywords]
        except ValueError:
            # If TfidfVectorizer fails (e.g., all tokens filtered), return candidates as-is
            return unique_candidates[:max_keywords]

    def _compute_polarity_score(self, doc: spacy.tokens.Doc) -> float:
        """Compute polarity score using lexicon-based approach with negation handling."""
        tokens = [token.text.lower() for token in doc if token.is_alpha]

        if not tokens:
            return 0.0

        positive_count = 0.0
        negative_count = 0.0

        i = 0
        while i < len(tokens):
            word = tokens[i]

            # Skip stopwords that aren't negation/intensifiers for counting
            if word in self._stopwords and word not in _NEGATION_WORDS and word not in _INTENSIFIERS:
                i += 1
                continue

            # Check for negation in preceding context (up to 3 words back)
            is_negated = self._check_negation(tokens, i)

            # Check for intensifier in preceding context (1 word back)
            intensity = self._check_intensity(tokens, i)

            if word in _POSITIVE_WORDS:
                if is_negated:
                    negative_count += 1.0 * intensity
                else:
                    positive_count += 1.0 * intensity
            elif word in _NEGATIVE_WORDS:
                if is_negated:
                    positive_count += 0.5 * intensity  # Negated negative is mildly positive
                else:
                    negative_count += 1.0 * intensity

            i += 1

        if positive_count == 0 and negative_count == 0:
            return 0.0

        # Compute normalized score
        total_sentiment = positive_count + negative_count
        if total_sentiment == 0:
            return 0.0

        raw = (positive_count - negative_count) / total_sentiment
        return raw

    def _check_negation(self, tokens: list[str], current_idx: int) -> bool:
        """Check if word at current_idx is negated by looking at preceding tokens."""
        start = max(0, current_idx - 3)
        for j in range(start, current_idx):
            if tokens[j] in _NEGATION_WORDS:
                return True
        return False

    def _check_intensity(self, tokens: list[str], current_idx: int) -> float:
        """Check if word at current_idx is intensified by a preceding token."""
        if current_idx > 0 and tokens[current_idx - 1] in _INTENSIFIERS:
            return 1.5
        return 1.0

    def _classify_from_score(self, score: float) -> str:
        """Classify sentiment from score ensuring consistency.

        positivo: score > 0.2
        negativo: score < -0.2
        neutro: -0.2 <= score <= 0.2
        """
        if score > 0.2:
            return "positivo"
        elif score < -0.2:
            return "negativo"
        else:
            return "neutro"

    def _is_spanish(self, doc: spacy.tokens.Doc) -> bool:
        """Detect if text is likely Spanish using vocabulary coverage heuristic."""
        alpha_tokens = [token for token in doc if token.is_alpha and len(token.text) > 2]

        if not alpha_tokens:
            return False

        # Check how many tokens are recognized by the Spanish model (have vectors)
        recognized = sum(1 for token in alpha_tokens if token.has_vector)
        coverage = recognized / len(alpha_tokens) if alpha_tokens else 0

        # Also check against Spanish stopwords presence
        all_tokens_lower = {token.text.lower() for token in doc if token.is_alpha}
        spanish_stopword_hits = len(all_tokens_lower & self._stopwords)

        # If coverage is very low AND no Spanish stopwords found, likely not Spanish
        if coverage < 0.3 and spanish_stopword_hits == 0:
            return False

        return True
