"""Unit tests for the execution-match comparator (no DB)."""

from evals.compare import execution_match


def test_identical():
    assert execution_match([[1, "a"], [2, "b"]], [[1, "a"], [2, "b"]])


def test_row_order_insensitive():
    assert execution_match([[1, "a"], [2, "b"]], [[2, "b"], [1, "a"]])


def test_float_tolerance():
    assert execution_match([[1.000001]], [[1.0]])


def test_column_permutation():
    assert execution_match([[1, "a"]], [["a", 1]], allow_col_permutation=True)
    assert not execution_match([[1, "a"]], [["a", 1]], allow_col_permutation=False)


def test_both_empty():
    assert execution_match([], [])


def test_rowcount_mismatch():
    assert not execution_match([[1]], [[1], [2]])


def test_value_mismatch():
    assert not execution_match([[1, "a"]], [[1, "b"]])


def test_duplicate_rows_are_multiset():
    assert execution_match([[1], [1]], [[1], [1]])
    assert not execution_match([[1], [1]], [[1], [2]])
