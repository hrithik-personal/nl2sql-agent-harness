"""Tests for the tool permission matrix."""

import pytest

from nl2sql.tools.permissions import PermissionDenied, is_enabled, require


def test_read_tools_enabled():
    assert is_enabled("get_schema")
    assert is_enabled("ask")


def test_run_sql_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_RUN_SQL", raising=False)
    assert not is_enabled("run_sql")
    with pytest.raises(PermissionDenied):
        require("run_sql")


def test_run_sql_enabled_with_env(monkeypatch):
    monkeypatch.setenv("ENABLE_RUN_SQL", "1")
    assert is_enabled("run_sql")
    require("run_sql")  # no raise


def test_unknown_tool_denied():
    assert not is_enabled("drop_everything")
    with pytest.raises(PermissionDenied):
        require("drop_everything")
