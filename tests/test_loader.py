"""Tests for loader.py."""
import pytest

from hestia.loader import detect_format, load_workbook
from hestia.errors import WorkbookFormatUnknownError


class TestLoadWorkbook:
    def test_opens_valid_xlsx(self, rd_dias_cuh_path):
        wb = load_workbook(rd_dias_cuh_path)
        assert wb is not None
        assert "summary" in wb.sheetnames

    def test_raises_on_missing_file(self, tmp_path):
        with pytest.raises(OSError, match="Cannot open workbook"):
            load_workbook(tmp_path / "nonexistent.xlsx")

    def test_raises_on_invalid_file(self, tmp_path):
        bad = tmp_path / "bad.xlsx"
        bad.write_bytes(b"this is not a valid xlsx file")
        with pytest.raises(OSError, match="Cannot open workbook"):
            load_workbook(bad)


class TestDetectFormat:
    def test_rd_dias_detected(self, rd_dias_cuh_workbook, all_configs):
        cfg = detect_format(rd_dias_cuh_workbook, all_configs)
        assert cfg["format_name"] == "rd_dias_v1"

    def test_haemonc_detected(self, haemonc_workbook, all_configs):
        cfg = detect_format(haemonc_workbook, all_configs)
        assert cfg["format_name"] == "haemonc_uranus_v1"

    def test_unknown_raises(self, all_configs):
        from unittest.mock import MagicMock
        wb = MagicMock()
        wb.sheetnames = ["unknown_sheet"]

        def sheet(name):
            s = MagicMock()
            s.__getitem__ = lambda self, k: MagicMock(value=None)
            s.iter_rows = MagicMock(return_value=iter([[]]))
            return s

        wb.__getitem__ = lambda self, k: sheet(k)
        with pytest.raises(WorkbookFormatUnknownError):
            detect_format(wb, all_configs)
