"""Unit tests for WP-F4 review classification, model-derived tagging, and verbatim quote verification."""

import pytest
import duckdb
from datamind.agent.classifier import (
    ReviewClassifier,
    ReviewClassificationResult,
    verify_verbatim_quotes,
    map_star_rating_to_sentiment,
)


def test_star_rating_mapping():
    assert map_star_rating_to_sentiment(1) == "negative"
    assert map_star_rating_to_sentiment(2) == "negative"
    assert map_star_rating_to_sentiment(3) == "neutral"
    assert map_star_rating_to_sentiment(4) == "positive"
    assert map_star_rating_to_sentiment(5) == "positive"


def test_review_classification_result_defaults():
    res = ReviewClassificationResult(
        review_id="rev-123",
        sentiment="positive",
        topic="delivery delay",
    )
    assert res.model_derived is True
    assert res.model_name == "gemma4:e2b"
    assert res.prompt_version == "v1.0"
    d = res.to_dict()
    assert d["model_derived"] is True
    assert d["sentiment"] == "positive"


def test_classifier_heuristic_fallback():
    classifier = ReviewClassifier()
    # Positive delivery delay review
    pos_res = classifier._heuristic_fallback("Recebi bem antes do prazo estipulado! Excelente entrega.", review_id="rev-pos")
    assert pos_res.sentiment == "positive"
    assert pos_res.topic == "delivery delay"
    assert pos_res.model_derived is True

    # Negative product quality review
    neg_res = classifier._heuristic_fallback("Produto veio quebrado com defeito horrível péssimo", review_id="rev-neg")
    assert neg_res.sentiment == "negative"
    assert neg_res.topic == "product quality"
    assert neg_res.model_derived is True


def test_classifier_duckdb_storage(tmp_path):
    db_file = tmp_path / "test_reviews.duckdb"
    classifier = ReviewClassifier()

    results = [
        ReviewClassificationResult(review_id="r1", sentiment="positive", topic="delivery delay"),
        ReviewClassificationResult(review_id="r2", sentiment="negative", topic="product quality"),
    ]

    count = classifier.store_classifications_in_duckdb(str(db_file), results)
    assert count == 2

    con = duckdb.connect(str(db_file), read_only=True)
    rows = con.execute("SELECT review_id, sentiment, topic, model_derived, model_name FROM olist_review_classifications").fetchall()
    con.close()

    assert len(rows) == 2
    assert rows[0][0] == "r1"
    assert rows[0][3] is True  # model_derived is strictly TRUE
    assert rows[1][3] is True


def test_verbatim_quote_verification():
    source_chunks = [
        "O produto chegou muito rapido e a qualidade do material superou as expectativas.",
        "Nao recebi a nota fiscal junto com a encomenda.",
    ]

    # Narrative with verbatim quotes
    clean_narrative = 'O cliente destacou que "O produto chegou muito rapido" e elogiou o atendimento.'
    is_clean, diags = verify_verbatim_quotes(clean_narrative, source_chunks)
    assert is_clean is True
    assert len(diags) == 1
    assert diags[0]["verbatim_in_source"] is True

    # Narrative with hallucinated/fabricated quote
    tampered_narrative = 'O cliente alegou "o vendedor roubou meu dinheiro e fugiu".'
    is_tampered_clean, tampered_diags = verify_verbatim_quotes(tampered_narrative, source_chunks)
    assert is_tampered_clean is False
    assert len(tampered_diags) == 1
    assert tampered_diags[0]["verbatim_in_source"] is False
