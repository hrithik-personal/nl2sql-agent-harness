"""Execution-match comparison for text-to-SQL evaluation.

Two queries "match" if they return the same result *set*, regardless of row
order, column order, or equivalent SQL phrasing. Numeric cells are compared with
a small tolerance. This is the metric used by the eval harness instead of brittle
exact-SQL-string matching.
"""

from __future__ import annotations

from collections import Counter
from itertools import permutations
from typing import Any

FLOAT_TOL = 1e-4


def _norm(v: Any) -> Any:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 4)
    return str(v)


def _row_key(row: list[Any]) -> tuple:
    return tuple(_norm(c) for c in row)


def _multiset(rows: list[list[Any]]) -> Counter:
    return Counter(_row_key(r) for r in rows)


def _close(a: Counter, b: Counter) -> bool:
    # exact multiset of normalised rows
    return a == b


def execution_match(
    rows_a: list[list[Any]],
    rows_b: list[list[Any]],
    allow_col_permutation: bool = True,
) -> bool:
    """True if result set A equals result set B (order-insensitive)."""
    if len(rows_a) != len(rows_b):
        return False
    if not rows_a:  # both empty
        return True

    ncols = len(rows_a[0])
    if any(len(r) != ncols for r in rows_a + rows_b):
        return False

    if _close(_multiset(rows_a), _multiset(rows_b)):
        return True

    # tolerate column reordering (agent may SELECT columns in another order)
    if allow_col_permutation and ncols <= 6:
        target = _multiset(rows_a)
        for perm in permutations(range(ncols)):
            permuted = [[r[i] for i in perm] for r in rows_b]
            if _close(target, _multiset(permuted)):
                return True
    return False
