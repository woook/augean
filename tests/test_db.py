"""Tests for db.py using a mock SQLAlchemy engine."""
from unittest.mock import MagicMock, call, patch

import pandas as pd
import pytest

from augean.db import (
    add_variants,
    add_workbook,
    get_failed_workbooks,
    get_parsed_workbooks,
    mark_workbook_failed,
    mark_workbook_parsed,
)
from augean.errors import ParseError


def _make_engine():
    """Return a mock SQLAlchemy Engine."""
    engine = MagicMock()
    conn = MagicMock()
    engine.begin.return_value.__enter__ = MagicMock(return_value=conn)
    engine.begin.return_value.__exit__ = MagicMock(return_value=False)
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    return engine, conn


class TestAddWorkbook:
    def test_executes_insert(self):
        engine, conn = _make_engine()
        add_workbook(engine, "test.xlsx", "rd_dias_v1")
        assert conn.execute.called
        call_args = conn.execute.call_args
        # Check that the SQL contains the expected table
        sql_str = str(call_args[0][0])
        assert "staging_workbooks" in sql_str

    def test_passes_workbook_name_and_format(self):
        engine, conn = _make_engine()
        add_workbook(engine, "my_workbook.xlsx", "haemonc_uranus_v1")
        params = conn.execute.call_args[0][1]
        assert params["wb"] == "my_workbook.xlsx"
        assert params["fmt"] == "haemonc_uranus_v1"


class TestMarkWorkbookParsed:
    def test_sets_parse_status_true(self):
        engine, conn = _make_engine()
        mark_workbook_parsed(engine, "ok.xlsx")
        params = conn.execute.call_args[0][1]
        assert params["wb"] == "ok.xlsx"
        sql_str = str(conn.execute.call_args[0][0])
        assert "parse_status = TRUE" in sql_str


class TestMarkWorkbookFailed:
    def test_sets_parse_status_false_with_errors(self):
        engine, conn = _make_engine()
        errors = [
            ParseError("fail.xlsx", "field", "hgvsc is null"),
            ParseError("fail.xlsx", "structural", "extra column"),
        ]
        mark_workbook_failed(engine, "fail.xlsx", errors)
        params = conn.execute.call_args[0][1]
        assert params["wb"] == "fail.xlsx"
        assert "hgvsc is null" in params["err"]
        assert "extra column" in params["err"]

    def test_empty_errors_list(self):
        engine, conn = _make_engine()
        mark_workbook_failed(engine, "fail.xlsx", [])
        assert conn.execute.called


class TestAddVariants:
    def test_returns_row_count(self):
        engine, conn = _make_engine()
        df = pd.DataFrame({"hgvsc": ["NM_1:c.1A>T"], "chromosome": [1]})
        with patch("augean.db.pd.DataFrame.to_sql", return_value=1) as mock_to_sql:
            count = add_variants(engine, df, "inca", "testdirectory")
        assert count == 1

    def test_empty_df_returns_zero(self):
        engine, conn = _make_engine()
        df = pd.DataFrame()
        count = add_variants(engine, df, "inca", "testdirectory")
        assert count == 0
        conn.execute.assert_not_called()


class TestGetParsedWorkbooks:
    def test_returns_names(self):
        engine, conn = _make_engine()
        conn.execute.return_value = [("wb1.xlsx",), ("wb2.xlsx",)]
        result = get_parsed_workbooks(engine)
        assert result == ["wb1.xlsx", "wb2.xlsx"]


class TestGetFailedWorkbooks:
    def test_returns_names(self):
        engine, conn = _make_engine()
        conn.execute.return_value = [("bad.xlsx",)]
        result = get_failed_workbooks(engine)
        assert result == ["bad.xlsx"]
