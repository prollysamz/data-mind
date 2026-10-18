"""Unit tests for leakage guard."""

from datamind.eval.leakage_guard import (
    check_leakage,
    check_model_leakage,
    compute_question_similarity,
)


def test_compute_similarity_identical_questions():
    q1 = "What is the total sales revenue across all products?"
    q2 = "What is the total sales revenue across all products?"
    sim = compute_question_similarity(q1, q2)
    assert sim == 1.0


def test_compute_similarity_disjoint_questions():
    q1 = "How many orders were canceled in 2017?"
    q2 = "Which customer cities have the highest average review score?"
    sim = compute_question_similarity(q1, q2)
    assert sim < 0.20


def test_leakage_guard_flags_paraphrase():
    train_q = ["What are the top 5 product categories by net revenue?"]
    eval_q = [("q1", "What are the top 5 product categories by net sales revenue?")]
    report = check_leakage(train_q, eval_q, threshold=0.70)
    assert not report.passed
    assert len(report.violations) == 1
    assert report.violations[0].similarity >= 0.70


def test_olist_dev_set_has_zero_leakage():
    report = check_model_leakage(
        semantic_model_path="examples/olist/semantic_model.yaml",
        question_set_path="eval/questions/olist_dev.yaml",
        threshold=0.80,
    )
    assert report.passed
    assert len(report.violations) == 0
    assert report.max_similarity < 0.50
    assert report.pairs_evaluated == 90  # 3 training * 30 eval
