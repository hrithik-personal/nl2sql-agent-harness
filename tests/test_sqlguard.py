"""Unit tests for the static SQL safety guard (no DB required)."""

from nl2sql.sqlguard import validate_select

ALLOWED = {"orders", "order_items", "sellers", "shipments"}


def test_plain_select_ok_and_limit_injected():
    r = validate_select("SELECT id FROM orders", allowed_tables=ALLOWED, max_rows=500)
    assert r.ok
    assert "limit" in r.sql.lower()
    assert r.tables == ("orders",)


def test_existing_limit_preserved():
    r = validate_select("SELECT id FROM orders LIMIT 5", allowed_tables=ALLOWED)
    assert r.ok
    assert "limit 5" in r.sql.lower()


def test_join_tables_extracted():
    r = validate_select(
        "SELECT s.name FROM orders o JOIN order_items i ON i.order_id=o.id "
        "JOIN sellers s ON s.id=i.seller_id",
        allowed_tables=ALLOWED,
    )
    assert r.ok
    assert set(r.tables) == {"orders", "order_items", "sellers"}


def test_reject_delete():
    r = validate_select("DELETE FROM orders", allowed_tables=ALLOWED)
    assert not r.ok and r.error_type == "forbidden"


def test_reject_update():
    r = validate_select("UPDATE orders SET status='x'", allowed_tables=ALLOWED)
    assert not r.ok and r.error_type == "forbidden"


def test_reject_stacked_statements():
    r = validate_select("SELECT 1; DROP TABLE orders", allowed_tables=ALLOWED)
    assert not r.ok and r.error_type == "forbidden"


def test_reject_cte_hidden_delete():
    sql = "WITH g AS (DELETE FROM orders RETURNING *) SELECT * FROM g"
    r = validate_select(sql, allowed_tables=ALLOWED)
    assert not r.ok and r.error_type == "forbidden"


def test_reject_unknown_table():
    r = validate_select("SELECT * FROM secret_vault", allowed_tables=ALLOWED)
    assert not r.ok and r.error_type == "invalid_sql"


def test_reject_garbage():
    r = validate_select("not sql at all ;;;", allowed_tables=ALLOWED)
    assert not r.ok


def test_cte_select_ok():
    sql = "WITH t AS (SELECT id FROM orders) SELECT id FROM t"
    r = validate_select(sql, allowed_tables=ALLOWED)
    assert r.ok
