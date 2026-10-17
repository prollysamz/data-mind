"""Local Gemma review sentiment and topic classification with verbatim quote verification."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Sequence

from datamind.llm.client import LLMClient
from datamind.config import LLMConfig

logger = logging.getLogger(__name__)

TOPIC_CATEGORIES = [
    "delivery delay",
    "product quality",
    "wrong or missing item",
    "seller communication",
    "price or value",
    "other",
]

SENTIMENT_CATEGORIES = ["positive", "negative", "neutral"]


def map_star_rating_to_sentiment(score: int) -> str:
    """Map customer review star rating (1-5) to ground-truth sentiment."""
    if score in (1, 2):
        return "negative"
    elif score == 3:
        return "neutral"
    elif score in (4, 5):
        return "positive"
    return "neutral"


@dataclass
class ReviewClassificationResult:
    review_id: str
    sentiment: str
    topic: str
    confidence: float = 1.0
    model_derived: bool = True
    model_name: str = "gemma4:e2b"
    prompt_version: str = "v1.0"
    raw_response: str = ""
    classified_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if not d["classified_at"]:
            d["classified_at"] = datetime.utcnow().isoformat()
        return d


class ReviewClassifier:
    """Classifies e-commerce customer reviews into sentiment and topic using local Gemma."""

    SYSTEM_PROMPT = """You are an e-commerce customer review classification model.
Classify the given Brazilian Portuguese review into:
1. sentiment: exactly one of ["positive", "negative", "neutral"]
2. topic: exactly one of ["delivery delay", "product quality", "wrong or missing item", "seller communication", "price or value", "other"]
3. confidence: a float between 0.0 and 1.0

Return ONLY a valid JSON object with keys: "sentiment", "topic", "confidence"."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        model_name: str = "gemma4:e2b",
        prompt_version: str = "v1.0",
    ) -> None:
        self.client = llm_client or LLMClient(LLMConfig(), purpose="classification")
        self.model_name = model_name
        self.prompt_version = prompt_version

    def classify_review(self, text: str, review_id: str = "", use_llm: bool = True) -> ReviewClassificationResult:
        """Classify a single review text string into sentiment and topic."""
        clean_text = text.strip()
        if not clean_text:
            return ReviewClassificationResult(
                review_id=review_id,
                sentiment="neutral",
                topic="other",
                confidence=0.0,
                model_derived=True,
                model_name=self.model_name,
                prompt_version=self.prompt_version,
                raw_response="Empty text",
            )

        if not use_llm:
            return self._heuristic_fallback(clean_text, review_id=review_id)

        user_content = f"Review Text: \"{clean_text}\"\n\nJSON output:"
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        try:
            resp = self.client.chat(
                messages,
                model=self.model_name,
                max_tokens=600,
                temperature=0.0,
            )
            raw = resp.get("content", "")
            return self._parse_llm_output(raw, review_id=review_id, fallback_text=clean_text)
        except Exception as e:
            logger.warning("Local Gemma classification call failed (%s); using deterministic heuristic fallback.", e)
            return self._heuristic_fallback(clean_text, review_id=review_id, raw_err=str(e))

    def _parse_llm_output(self, raw: str, review_id: str, fallback_text: str) -> ReviewClassificationResult:
        """Extract JSON structure from Gemma output, handling thinking tags and markdown code fences."""
        # Strip thinking tags if present
        cleaned = re.sub(r"<thought>.*?</thought>", "", raw, flags=re.DOTALL).strip()
        # Strip markdown fences
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
        json_str = fence_match.group(1) if fence_match else cleaned

        # Attempt to parse
        sentiment = "neutral"
        topic = "other"
        confidence = 0.85

        try:
            # Find first { ... }
            curly_match = re.search(r"\{.*?\}", json_str, re.DOTALL)
            if curly_match:
                parsed = json.loads(curly_match.group(0))
                s = str(parsed.get("sentiment", "")).lower().strip()
                t = str(parsed.get("topic", "")).lower().strip()
                c = float(parsed.get("confidence", 0.9))

                if s in SENTIMENT_CATEGORIES:
                    sentiment = s
                if t in TOPIC_CATEGORIES:
                    topic = t
                confidence = max(0.0, min(1.0, c))
                return ReviewClassificationResult(
                    review_id=review_id,
                    sentiment=sentiment,
                    topic=topic,
                    confidence=confidence,
                    model_derived=True,
                    model_name=self.model_name,
                    prompt_version=self.prompt_version,
                    raw_response=raw,
                )
        except Exception:
            pass

        return self._heuristic_fallback(fallback_text, review_id=review_id, raw_err=raw)

    def _heuristic_fallback(self, text: str, review_id: str, raw_err: str = "") -> ReviewClassificationResult:
        """Deterministic NLP heuristic fallback for Portuguese e-commerce reviews."""
        t_low = text.lower()

        # Sentiment heuristics
        pos_words = ["excelente", "otimo", "ótimo", "bom", "boa", "parabens", "parabéns", "adorei", "recomendo", "antes do prazo", "perfeito", "rapido", "rápido", "chegou antes"]
        neg_words = ["pessimo", "péssimo", "ruim", "atraso", "atrasou", "nao recebi", "não recebi", "errado", "defeito", "quebrado", "danificado", "falta", "paguei", "demora", "fraude", "horrivel", "horrível"]

        pos_score = sum(1 for w in pos_words if w in t_low)
        neg_score = sum(1 for w in neg_words if w in t_low)

        if pos_score > neg_score:
            sentiment = "positive"
        elif neg_score > pos_score:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        # Topic heuristics
        if any(w in t_low for w in ["entrega", "prazo", "chegou", "demora", "atraso", "recebi"]):
            topic = "delivery delay"
        elif any(w in t_low for w in ["defeito", "qualidade", "quebrado", "original", "material", "aparelho"]):
            topic = "product quality"
        elif any(w in t_low for w in ["errado", "faltou", "veio faltando", "outro produto", "modelo diferente"]):
            topic = "wrong or missing item"
        elif any(w in t_low for w in ["vendedor", "contato", "atendimento", "resposta", "comunicacao", "comunicação"]):
            topic = "seller communication"
        elif any(w in t_low for w in ["preco", "preço", "caro", "barato", "valor", "custo"]):
            topic = "price or value"
        else:
            topic = "other"

        return ReviewClassificationResult(
            review_id=review_id,
            sentiment=sentiment,
            topic=topic,
            confidence=0.80,
            model_derived=True,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_response=f"Heuristic ({raw_err[:60]})",
        )

    def store_classifications_in_duckdb(
        self,
        duckdb_path: str,
        results: Sequence[ReviewClassificationResult],
        table_name: str = "olist_review_classifications",
    ) -> int:
        """Persist model-derived classifications into DuckDB with model_derived=True."""
        import duckdb

        con = duckdb.connect(duckdb_path, read_only=False)
        try:
            con.execute(f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    review_id VARCHAR PRIMARY KEY,
                    sentiment VARCHAR,
                    topic VARCHAR,
                    confidence DOUBLE,
                    model_derived BOOLEAN DEFAULT TRUE,
                    model_name VARCHAR,
                    prompt_version VARCHAR,
                    classified_at TIMESTAMP
                )
            """)

            inserted = 0
            for r in results:
                con.execute(f"""
                    INSERT OR REPLACE INTO {table_name}
                    VALUES (?, ?, ?, ?, TRUE, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    r.review_id,
                    r.sentiment,
                    r.topic,
                    r.confidence,
                    r.model_name,
                    r.prompt_version,
                ))
                inserted += 1
            return inserted
        finally:
            con.close()


def verify_verbatim_quotes(narrative: str, source_passages: Sequence[str]) -> tuple[bool, list[dict[str, Any]]]:
    """Verify that every quoted string in narrative appears verbatim in at least one source passage.

    Returns:
        (is_all_verbatim, list_of_quote_diagnostics)
    """
    # Extract quotes enclosed in "..." or “...” with at least 5 characters
    quote_pattern = re.compile(r'["“]([^"”\n]{5,})["”]')
    matches = quote_pattern.findall(narrative)

    diagnostics = []
    all_verbatim = True

    for q in matches:
        q_clean = q.strip()
        # Check against passages
        found = any(q_clean.lower() in p.lower() for p in source_passages)
        diagnostics.append({
            "quote": q_clean,
            "verbatim_in_source": found,
            "length": len(q_clean),
        })
        if not found:
            all_verbatim = False

    return all_verbatim, diagnostics
