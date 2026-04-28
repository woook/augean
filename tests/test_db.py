"""Tests for db.py using a mock SQLAlchemy engine."""
from unittest.mock import MagicMock, call, patch

import pandas as pd
import pytest

import augean.db as db_module
from augean.db import (
    add_variants,
    add_workbook,
    create_engine,
    get_failed_workbooks,
    get_parsed_workbooks,
    mark_workbook_failed,
    mark_workbook_parsed,
    migrate_schema,
)
from augean.errors import ParseError, SchemaMismatchError


def _make_engine():
    """Return a mock SQLAlchemy Engine."""
    engine = MagicMock()
    conn = MagicMock()
    engine.begin.return_value.__enter__ = MagicMock(return_value=conn)
    engine.begin.return_value.__exit__ = MagicMock(return_value=False)
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    return engine, conn


class TestCreateEngine:
    def test_default_sslmode_is_require(self):
        """create_engine passes sslmode=require to psycopg2 by default."""
        creds = {
            "user": "u", "password": "p", "host": "localhost",
            "port": 5432, "database": "db",
        }
        with patch("augean.db._sa_create_engine") as mock_sa:
            create_engine(creds)
        _, kwargs = mock_sa.call_args
        assert kwargs["connect_args"]["sslmode"] == "require"

    def test_sslmode_overridable(self):
        """sslmode in credentials dict overrides the default."""
        creds = {
            "user": "u", "password": "p", "host": "localhost",
            "port": 5432, "database": "db", "sslmode": "disable",
        }
        with patch("augean.db._sa_create_engine") as mock_sa:
            create_engine(creds)
        _, kwargs = mock_sa.call_args
        assert kwargs["connect_args"]["sslmode"] == "disable"


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
        engine, _conn = _make_engine()
        df = pd.DataFrame({"hgvsc": ["NM_1:c.1A>T"], "chromosome": [1]})
        with patch.object(db_module, "_check_schema"), \
             patch("augean.db.pd.DataFrame.to_sql", return_value=1):
            count = add_variants(engine, df, "inca", "testdirectory")
        assert count == 1

    def test_empty_df_returns_zero(self):
        engine, conn = _make_engine()
        df = pd.DataFrame()
        count = add_variants(engine, df, "inca", "testdirectory")
        assert count == 0
        conn.execute.assert_not_called()

    def test_schema_mismatch_raises(self):
        engine, _ = _make_engine()
        df = pd.DataFrame({"hgvsc": ["NM_1:c.1A>T"], "new_col": ["val"]})
        with patch.object(db_module, "_sa_inspect") as mock_inspect:
            mock_inspect.return_value.has_table.return_value = True
            mock_inspect.return_value.get_columns.return_value = [{"name": "hgvsc"}]
            with pytest.raises(SchemaMismatchError) as exc_info:
                add_variants(engine, df, "inca", "testdirectory")
        assert "new_col" in str(exc_info.value)
        assert "ALTER TABLE" in str(exc_info.value)
        assert "--migrate" in str(exc_info.value)

    def test_schema_check_skipped_when_table_absent(self):
        engine, _ = _make_engine()
        df = pd.DataFrame({"hgvsc": ["NM_1:c.1A>T"]})
        with patch.object(db_module, "_sa_inspect") as mock_inspect, \
             patch("augean.db.pd.DataFrame.to_sql", return_value=1):
            mock_inspect.return_value.has_table.return_value = False
            count = add_variants(engine, df, "inca", "testdirectory")
        assert count == 1


class TestMigrateSchema:
    def test_executes_alter_for_missing_columns(self):
        engine, conn = _make_engine()
        df = pd.DataFrame({"hgvsc": ["NM_1:c.1A>T"], "new_col": ["val"]})
        with patch.object(db_module, "_sa_inspect") as mock_inspect:
            mock_inspect.return_value.has_table.return_value = True
            mock_inspect.return_value.get_columns.return_value = [{"name": "hgvsc"}]
            migrate_schema(engine, df, "inca", "testdirectory")
        sql_called = conn.execute.call_args[0][0].text
        assert "ADD COLUMN IF NOT EXISTS new_col" in sql_called

    def test_no_alter_when_schema_matches(self):
        engine, conn = _make_engine()
        df = pd.DataFrame({"hgvsc": ["NM_1:c.1A>T"]})
        with patch.object(db_module, "_sa_inspect") as mock_inspect:
            mock_inspect.return_value.has_table.return_value = True
            mock_inspect.return_value.get_columns.return_value = [{"name": "hgvsc"}]
            migrate_schema(engine, df, "inca", "testdirectory")
        conn.execute.assert_not_called()

    def test_skipped_when_table_absent(self):
        engine, conn = _make_engine()
        df = pd.DataFrame({"hgvsc": ["NM_1:c.1A>T"]})
        with patch.object(db_module, "_sa_inspect") as mock_inspect:
            mock_inspect.return_value.has_table.return_value = False
            migrate_schema(engine, df, "inca", "testdirectory")
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
