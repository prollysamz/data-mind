"""Leakage guard for DataMind evaluation suites.

Enforces zero prompt/test leakage by verifying that few-shot training examples
and verified queries in the semantic model are strictly disjoint from evaluation questions.
Computes token and n-gram Jaccard similarity and fails if similarity exceeds the threshold (0.80).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from datamind.semantic.loader import load_semantic_model

_STOP_WORDS = {
    "a", "an", "the", "in", "on", "at", "for", "to", "of", "and", "or", "is",
    "was", "are", "were", "what", "which", "who", "whom", "how", "our", "all",
    "by", "with", "from", "as", "that", "this", "these", "those",
}


def tokenize(text: str) -> list[str]:
    """Extract lowercased alphanumeric tokens from text."""
    return re.findall(r"\b[a-z0-9_]+\b", text.lower())


def get_token_set(text: str, remove_stopwords: bool = True) -> set[str]:
    """Return set of normalized tokens, optionally filtering basic stop words."""
    tokens = tokenize(text)
    if remove_stopwords:
        tokens = [t for t in tokens if t not in _STOP_WORDS]
    return set(tokens)


def get_bigram_set(text: str) -> set[str]:
    """Return set of 2-grams (bigrams) from text."""
    tokens = tokenize(text)
    if len(tokens) < 2:
        return set(tokens)
    return {f"{tokens[i]}_{tokens[i+1]}" for i in range(len(tokens) - 1)}


def compute_jaccard_similarity(s1: set[str], s2: set[str]) -> float:
    """Compute standard Jaccard similarity between two sets: |A ∩ B| / |A ∪ B|."""
    if not s1 or not s2:
        return 0.0
    intersection = len(s1 & s2)
    union = len(s1 | s2)
    return round(intersection / union, 4) if union > 0 else 0.0


def compute_question_similarity(q1: str, q2: str) -> float:
    """Compute combined 1-gram and 2-gram Jaccard similarity between two questions."""
    tokens1 = get_token_set(q1)
    tokens2 = get_token_set(q2)
    j_unigram = compute_jaccard_similarity(tokens1, tokens2)

    bigrams1 = get_bigram_set(q1)
    bigrams2 = get_bigram_set(q2)
    j_bigram = compute_jaccard_similarity(bigrams1, bigrams2)

    # 60% unigram weight + 40% bigram sequence weight
    return round(0.6 * j_unigram + 0.4 * j_bigram, 4)


@dataclass
class LeakagePair:
    training_question: str
    eval_question: str
    eval_id: str
    similarity: float
    exceeds_threshold: bool


@dataclass
class LeakageReport:
    semantic_model_path: str
    question_set_path: str
    threshold: float
    pairs_evaluated: int = 0
    max_similarity: float = 0.0
    passed: bool = True
    violations: list[LeakagePair] = field(default_factory=list)
    top_matches: list[LeakagePair] = field(default_factory=list)


def check_leakage(
    training_questions: list[str],
    eval_questions: list[tuple[str, str]],  # (qid, question)
    threshold: float = 0.80,
    model_path: str = "",
    questions_path: str = "",
) -> LeakageReport:
    """Evaluate pairwise text similarity between training questions and evaluation questions."""
    report = LeakageReport(
        semantic_model_path=model_path,
        question_set_path=questions_path,
        threshold=threshold,
    )

    all_pairs: list[LeakagePair] = []

    for t_q in training_questions:
        for qid, e_q in eval_questions:
            sim = compute_question_similarity(t_q, e_q)
            exceeds = (sim >= threshold)
            pair = LeakagePair(
                training_question=t_q,
                eval_question=e_q,
                eval_id=qid,
                similarity=sim,
                exceeds_threshold=exceeds,
            )
            all_pairs.append(pair)
            if exceeds:
                report.violations.append(pair)

    report.pairs_evaluated = len(all_pairs)
    all_pairs.sort(key=lambda p: p.similarity, reverse=True)
    report.top_matches = all_pairs[:5]
    report.max_similarity = all_pairs[0].similarity if all_pairs else 0.0
    report.passed = (len(report.violations) == 0)
    return report


def check_model_leakage(
    semantic_model_path: str | Path,
    question_set_path: str | Path,
    threshold: float = 0.80,
) -> LeakageReport:
    """Load semantic model verified queries and questions YAML to check for leakage."""
    s_path = Path(semantic_model_path)
    q_path = Path(question_set_path)

    if not s_path.exists():
        raise FileNotFoundError(f"Semantic model file not found: {s_path}")
    if not q_path.exists():
        raise FileNotFoundError(f"Question set file not found: {q_path}")

    model = load_semantic_model(s_path)
    training_questions = [vq.question for vq in model.verified_queries]

    with open(q_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    eval_questions: list[tuple[str, str]] = []
    for item in data.get("questions", []):
        qid = item.get("id", "unknown")
        q_text = item.get("question", "")
        if q_text:
            eval_questions.append((qid, q_text))

    return check_leakage(
        training_questions=training_questions,
        eval_questions=eval_questions,
        threshold=threshold,
        model_path=str(s_path),
        questions_path=str(q_path),
    )
