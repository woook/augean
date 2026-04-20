"""Tests for config loading and fingerprint evaluation."""
import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from augean.config import _evaluate_fingerprint, get_config_for_workbook, load_configs
from augean.errors import (
    AmbiguousWorkbookFormatError,
    ConfigValidationError,
    WorkbookFormatUnknownError,
)


CONFIGS_DIR = Path(__file__).parent.parent / "configs"


class TestLoadConfigs:
    def test_loads_both_configs(self):
        configs = load_configs(CONFIGS_DIR)
        names = {c["format_name"] for c in configs}
        assert "rd_dias_v1" in names
        assert "haemonc_uranus_v1" in names
        assert "haemonc_uranus_v0" in names

    def test_required_keys_present(self):
        configs = load_configs(CONFIGS_DIR)
        for cfg in configs:
            for key in ("format_name", "format_version", "fingerprint", "sheets"):
                assert key in cfg, f"{cfg.get('format_name')} missing key '{key}'"

    def test_missing_required_key_raises(self, tmp_path):
        bad = {"format_name": "bad", "format_version": "1.0", "fingerprint": []}
        (tmp_path / "bad.json").write_text(json.dumps(bad))
        with pytest.raises(ConfigValidationError, match="missing required keys"):
            load_configs(tmp_path)

    def test_empty_dir_returns_empty_list(self, tmp_path):
        assert load_configs(tmp_path) == []


class TestFingerprintEvaluation:
    def _make_wb(self, sheetnames, cells=None):
        """Return a minimal mock workbook."""
        cells = cells or {}
        wb = MagicMock()
        wb.sheetnames = sheetnames

        def get_sheet(name):
            s = MagicMock()
            sheet_cells = cells.get(name, {})

            def getitem(key):
                c = MagicMock()
                c.value = sheet_cells.get(key)
                return c

            s.__getitem__ = lambda self, k: getitem(k)

            headers = sheet_cells.get("__headers__", [])
            mock_row = []
            for h in headers:
                mc = MagicMock()
                mc.value = h
                mock_row.append(mc)
            s.iter_rows = MagicMock(return_value=iter([mock_row]))
            return s

        wb.__getitem__ = lambda self, k: get_sheet(k)
        return wb

    def test_sheet_equals_passes(self):
        wb = self._make_wb(["summary"], {"summary": {"A5": "Subpanel analysed"}})
        fp = [{"sheet": "summary", "cell": "A5", "equals": "Subpanel analysed"}]
        assert _evaluate_fingerprint(wb, fp) is True

    def test_sheet_equals_fails(self):
        wb = self._make_wb(["summary"], {"summary": {"A5": "Something else"}})
        fp = [{"sheet": "summary", "cell": "A5", "equals": "Subpanel analysed"}]
        assert _evaluate_fingerprint(wb, fp) is False

    def test_matches_pattern_passes(self):
        wb = self._make_wb(["summary"], {"summary": {"B1": "123456789-ABC"}})
        fp = [{"sheet": "summary", "cell": "B1", "matches_pattern": "^\\d{9}-"}]
        assert _evaluate_fingerprint(wb, fp) is True

    def test_matches_pattern_fails(self):
        wb = self._make_wb(["summary"], {"summary": {"B1": "shortid"}})
        fp = [{"sheet": "summary", "cell": "B1", "matches_pattern": "^\\d{9}-"}]
        assert _evaluate_fingerprint(wb, fp) is False

    def test_sheet_exists_passes(self):
        wb = self._make_wb(["m_codes"])
        fp = [{"sheet": "m_codes", "exists": True}]
        assert _evaluate_fingerprint(wb, fp) is True

    def test_sheet_not_exists_fails(self):
        wb = self._make_wb(["summary"])
        fp = [{"sheet": "m_codes", "exists": True}]
        assert _evaluate_fingerprint(wb, fp) is False

    def test_sheet_pattern_exists_passes(self):
        wb = self._make_wb(["summary", "interpret_1", "interpret_2"])
        fp = [{"sheet_pattern": "^interpret", "exists": True}]
        assert _evaluate_fingerprint(wb, fp) is True

    def test_sheet_pattern_not_exists_fails(self):
        wb = self._make_wb(["summary", "included"])
        fp = [{"sheet_pattern": "^interpret", "exists": True}]
        assert _evaluate_fingerprint(wb, fp) is False

    def test_has_columns_passes(self):
        wb = self._make_wb(
            ["included"],
            {"included": {"__headers__": ["HGVSc", "CHROM", "POS", "Interpreted"]}},
        )
        fp = [{"sheet": "included", "has_columns": ["HGVSc", "CHROM"]}]
        assert _evaluate_fingerprint(wb, fp) is True

    def test_has_columns_fails(self):
        wb = self._make_wb(
            ["included"],
            {"included": {"__headers__": ["HGVSc", "CHROM"]}},
        )
        fp = [{"sheet": "included", "has_columns": ["HGVSc", "REF"]}]
        assert _evaluate_fingerprint(wb, fp) is False

    def test_all_checks_must_pass(self):
        wb = self._make_wb(
            ["summary"],
            {"summary": {"A5": "Subpanel analysed", "A6": "wrong"}},
        )
        fp = [
            {"sheet": "summary", "cell": "A5", "equals": "Subpanel analysed"},
            {"sheet": "summary", "cell": "A6", "equals": "M-code"},
        ]
        assert _evaluate_fingerprint(wb, fp) is False


class TestGetConfigForWorkbook:
    def _make_haemonc_mock(self):
        wb = MagicMock()
        wb.sheetnames = ["summary", "m_codes", "included"]

        def sheet(name):
            s = MagicMock()
            cells = {
                "summary": {"A5": "Subpanel analysed", "A6": "M-code"},
                "m_codes": {},
                "included": {},
            }.get(name, {})

            def getitem(k):
                c = MagicMock()
                c.value = cells.get(k)
                return c

            s.__getitem__ = lambda self, k: getitem(k)
            s.iter_rows = MagicMock(return_value=iter([[]]))
            return s

        wb.__getitem__ = lambda self, k: sheet(k)
        return wb

    def test_unknown_format_raises(self, all_configs):
        wb = MagicMock()
        wb.sheetnames = ["totally", "unknown"]

        def sheet(name):
            s = MagicMock()
            s.__getitem__ = lambda self, k: MagicMock(value=None)
            s.iter_rows = MagicMock(return_value=iter([[]]))
            return s

        wb.__getitem__ = lambda self, k: sheet(k)
        with pytest.raises(WorkbookFormatUnknownError):
            get_config_for_workbook(wb, all_configs)

    def test_ambiguous_format_raises(self, all_configs):
        """If a workbook matches more than one config, raise AmbiguousWorkbookFormatError."""
        always_true_config = {
            "format_name": "dup",
            "format_version": "1.0",
            "fingerprint": [],
            "sheets": {},
        }
        haemonc_config = next(c for c in all_configs if c["format_name"] == "haemonc_uranus_v1")
        configs = [haemonc_config, always_true_config]
        wb = self._make_haemonc_mock()
        with pytest.raises(AmbiguousWorkbookFormatError):
            get_config_for_workbook(wb, configs)


class TestRealWorkbookFingerprint:
    def test_rd_dias_cuh_detected(self, rd_dias_cuh_workbook, all_configs):
        cfg = get_config_for_workbook(rd_dias_cuh_workbook, all_configs)
        assert cfg["format_name"] == "rd_dias_v1"

    def test_rd_dias_nuh_detected(self, rd_dias_nuh_workbook, all_configs):
        cfg = get_config_for_workbook(rd_dias_nuh_workbook, all_configs)
        assert cfg["format_name"] == "rd_dias_v1"

    def test_haemonc_detected(self, haemonc_workbook, all_configs):
        cfg = get_config_for_workbook(haemonc_workbook, all_configs)
        assert cfg["format_name"] == "haemonc_uranus_v1"

    def test_haemonc_v1_detected_without_m_codes_sheet(self, all_configs):
        """v1 fingerprint no longer requires m_codes sheet."""
        wb = MagicMock()
        wb.sheetnames = ["summary", "included", "pindel"]  # no m_codes

        def sheet(name):
            s = MagicMock()
            cells = {"summary": {"A5": "Subpanel analysed", "A6": "M-code"}}.get(name, {})
            s.__getitem__ = lambda self, k: MagicMock(value=cells.get(k))
            s.iter_rows = MagicMock(return_value=iter([[]]))
            return s

        wb.__getitem__ = lambda self, k: sheet(k)
        cfg = get_config_for_workbook(wb, all_configs)
        assert cfg["format_name"] == "haemonc_uranus_v1"

    def test_haemonc_v0_detected(self, all_configs):
        """v0 fingerprint: A8='Sample ID', F12='Subpanel analysed'."""
        wb = MagicMock()
        wb.sheetnames = ["summary", "included", "excluded", "pindel"]

        def sheet(name):
            s = MagicMock()
            cells = {"summary": {"A8": "Sample ID", "F12": "Subpanel analysed"}}.get(name, {})
            s.__getitem__ = lambda self, k: MagicMock(value=cells.get(k))
            s.iter_rows = MagicMock(return_value=iter([[]]))
            return s

        wb.__getitem__ = lambda self, k: sheet(k)
        cfg = get_config_for_workbook(wb, all_configs)
        assert cfg["format_name"] == "haemonc_uranus_v0"
