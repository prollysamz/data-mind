"""Regression cases for independently computed SQL result comparison."""

from types import SimpleNamespace

import pytest

from datamind.eval.runner import _compare_result_sets


def query(rows, truncated=False):
    return SimpleNamespace(result=SimpleNamespace(rows=rows, truncated=truncated))


@pytest.mark.parametrize("truth,actual", [
    ([], [(1,)]),
    ([("a", 10)], [("wrong", 10)]),
    ([("a", 1), ("b", 2)], [("a", 1), ("b", 2), ("c", 3)]),
    ([("a", 1), ("a", 2)], [("a", 2), ("a", 2)]),
    ([("a", 1, 2)], [("a", 999, 2)]),
    ([(None,)], [(0,)]),
])
def test_partial_or_incorrect_results_fail(truth, actual):
    assert not _compare_result_sets(truth, [query(actual)])[0]


def test_empty_results_need_actual_empty_execution():
    assert not _compare_result_sets([], [])[0]
    assert _compare_result_sets([], [query([])])[0]


def test_complete_results_respect_duplicates_truncation_and_order():
    rows = [("a", 1), ("b", 2)]
    assert _compare_result_sets(rows, [query(rows[::-1])])[0]
    assert not _compare_result_sets(rows, [query(rows[::-1])], ordered=True)[0]
    assert not _compare_result_sets(rows, [query(rows, truncated=True)])[0]
