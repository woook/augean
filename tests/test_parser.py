"""Tests for parser.py."""
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from freezegun import freeze_time

from augean import parser
from augean.parser import (
    _split_clinical_indication,
    extract_label_scan,
    extract_named_cells,
    extract_named_cells_multi,
    extract_tabular,
    merge_dataframes,
    parse_workbook,
)

WORKBOOKS_DIR = Path(__file__).parent / "test_data" / "workbooks"


# ---------------------------------------------------------------------------
# Unit tests for _split_clinical_indication
# ---------------------------------------------------------------------------

class TestSplitClinicalIndication:
    def test_single_indication(self):
        names, codes = _split_clinical_indication("R208.1_Inherited breast cancer")
        assert codes == "R208.1"
        assert names == "Inherited breast cancer"

    def test_multiple_indications(self):
        names, codes = _split_clinical_indication(
            "R208.1_Inherited breast cancer;R207.1_Ovarian cancer"
        )
        assert codes == "R208.1;R207.1"
        assert names == "Inherited breast cancer;Ovarian cancer"

    def test_none_input(self):
        names, codes = _split_clinical_indication(None)
        assert names == ""
        assert codes == ""

    def test_no_underscore(self):
        names, codes = _split_clinical_indication("Bare condition")
        assert codes == "Bare condition"
        assert names == "Bare condition"


# ---------------------------------------------------------------------------
# extract_named_cells
# ---------------------------------------------------------------------------

class TestExtractNamedCells:
    def _make_sheet_with_cells(self, cell_values: dict):
        """Build a mock sheet where cell_values = {addr: value}."""
        sheet = MagicMock()

        def getitem(key):
            # Column iteration (single letter key)
            if isinstance(key, str) and len(key) == 1 and key.isalpha():
                col_data = cell_values.get(f"__col_{key}__", [])
                cells = []
                for i, val in enumerate(col_data, start=1):
                    mc = MagicMock()
                    mc.value = val
                    mc.row = i
                    cells.append(mc)
                return cells
            # Regular cell
            mc = MagicMock()
            mc.value = cell_values.get(key)
            return mc

        sheet.__getitem__ = lambda s, k: getitem(k)
        return sheet

    def test_extracts_simple_fields(self):
        wb = MagicMock()
        sheet = self._make_sheet_with_cells({"B1": "SAMPLE123", "F2": "Panel1"})
        wb.__getitem__ = lambda s, k: sheet

        config = {
            "fields": [
                {"db_column": "sample_id", "cell": "B1"},
                {"db_column": "panel",     "cell": "F2"},
            ]
        }
        df = extract_named_cells(wb, "summary", config)
        assert df["sample_id"][0] == "SAMPLE123"
        assert df["panel"][0] == "Panel1"

    def test_sentinel_scan(self):
        wb = MagicMock()
        sheet = self._make_sheet_with_cells({
            "__col_A__": [None, "Reference:", None],
            "B2": "GRCh38",
        })
        wb.__getitem__ = lambda s, k: sheet

        config = {
            "fields": [
                {
                    "db_column": "ref_genome",
                    "extraction": "sentinel_scan",
                    "scan_column": "A",
                    "sentinel_value": "Reference:",
                    "value_column": "B",
                    "default": "not_defined",
                }
            ]
        }
        df = extract_named_cells(wb, "summary", config)
        assert df["ref_genome"][0] == "GRCh38"

    def test_sentinel_scan_uses_default_when_not_found(self):
        wb = MagicMock()
        sheet = self._make_sheet_with_cells({
            "__col_A__": [None, None],
        })
        wb.__getitem__ = lambda s, k: sheet

        config = {
            "fields": [
                {
                    "db_column": "ref_genome",
                    "extraction": "sentinel_scan",
                    "scan_column": "A",
                    "sentinel_value": "Reference:",
                    "value_column": "B",
                    "default": "not_defined",
                }
            ]
        }
        df = extract_named_cells(wb, "summary", config)
        assert df["ref_genome"][0] == "not_defined"

    def test_clinical_indication_split(self):
        wb = MagicMock()
        sheet = self._make_sheet_with_cells({
            "F1": "R208.1_Inherited breast cancer;R207.1_Ovarian cancer"
        })
        wb.__getitem__ = lambda s, k: sheet

        config = {
            "fields": [
                {"db_column": "clinical_indication", "cell": "F1",
                 "parse": "clinical_indication_split"}
            ]
        }
        df = extract_named_cells(wb, "summary", config)
        assert "preferred_condition_name" in df.columns
        assert "r_code" in df.columns
        assert df["preferred_condition_name"][0] == "Inherited breast cancer;Ovarian cancer"
        assert df["r_code"][0] == "R208.1;R207.1"
        assert "clinical_indication" not in df.columns

    @freeze_time("2024-07-10")
    def test_date_default_today(self):
        wb = MagicMock()
        sheet = self._make_sheet_with_cells({"G22": None})
        wb.__getitem__ = lambda s, k: sheet

        config = {
            "fields": [
                {"db_column": "date_last_evaluated", "cell": "G22",
                 "type": "date", "default": "today"}
            ]
        }
        df = extract_named_cells(wb, "summary", config)
        assert str(df["date_last_evaluated"][0]) == "2024-07-10"


# ---------------------------------------------------------------------------
# extract_label_scan
# ---------------------------------------------------------------------------

class TestExtractLabelScan:
    def _make_wb(self, col_a: list, col_b_map: dict):
        wb = MagicMock()
        sheet = MagicMock()

        def getitem(key):
            if key == "A":
                cells = []
                for i, val in enumerate(col_a, start=1):
                    mc = MagicMock()
                    mc.value = val
                    mc.row = i
                    cells.append(mc)
                return cells
            # B{row} access
            mc = MagicMock()
            mc.value = col_b_map.get(key)
            return mc

        sheet.__getitem__ = lambda s, k: getitem(k)
        wb.__getitem__ = lambda s, k: sheet
        return wb

    def test_extracts_fields_by_label(self):
        wb = self._make_wb(
            ["Sample ID", None, "M-code", "Subpanel analysed"],
            {"B1": "SAMPLE-001", "B3": "M87", "B4": "Myeloid"},
        )
        config = {
            "scan_column": "A",
            "value_column": "B",
            "fields": [
                {"db_column": "sample_id", "label": "Sample ID"},
                {"db_column": "panel",     "label": "M-code"},
                {"db_column": "preferred_condition_name", "label": "Subpanel analysed"},
            ],
        }
        df = extract_label_scan(wb, "summary", config)
        assert df["sample_id"][0] == "SAMPLE-001"
        assert df["panel"][0] == "M87"
        assert df["preferred_condition_name"][0] == "Myeloid"

    def test_missing_label_returns_default(self):
        wb = self._make_wb(["Sample ID"], {"B1": "S1"})
        config = {
            "scan_column": "A",
            "value_column": "B",
            "fields": [
                {"db_column": "ref_genome", "label": "Reference:", "default": "not_defined"},
            ],
        }
        df = extract_label_scan(wb, "summary", config)
        assert df["ref_genome"][0] == "not_defined"

    @freeze_time("2024-07-10")
    def test_date_default_today(self):
        wb = self._make_wb([], {})
        config = {
            "scan_column": "A",
            "value_column": "B",
            "fields": [
                {"db_column": "date_last_evaluated", "label": "Date",
                 "type": "date", "default": "today"},
            ],
        }
        df = extract_label_scan(wb, "summary", config)
        assert str(df["date_last_evaluated"][0]) == "2024-07-10"


# ---------------------------------------------------------------------------
# extract_named_cells_multi
# ---------------------------------------------------------------------------

class TestExtractNamedCellsMulti:
    def test_extracts_one_row_per_matching_sheet(self):
        wb = MagicMock()
        wb.sheetnames = ["summary", "interpret_1", "interpret_2", "included"]

        cells = {
            "interpret_1": {"C3": "NM_001.1:c.100A>T", "C26": "Pathogenic"},
            "interpret_2": {"C3": "NM_002.2:c.200G>C", "C26": "Likely pathogenic"},
        }

        def get_sheet(name):
            s = MagicMock()
            sheet_cells = cells.get(name, {})
            s.__getitem__ = lambda self, k: MagicMock(value=sheet_cells.get(k))
            return s

        wb.__getitem__ = lambda s, k: get_sheet(k)

        config = {
            "sheet_pattern": "^interpret",
            "fields": [
                {"db_column": "hgvsc",                   "cell": "C3"},
                {"db_column": "germline_classification", "cell": "C26"},
            ],
        }
        df = extract_named_cells_multi(wb, config)
        assert len(df) == 2
        assert list(df["hgvsc"]) == ["NM_001.1:c.100A>T", "NM_002.2:c.200G>C"]
        assert list(df["germline_classification"]) == ["Pathogenic", "Likely pathogenic"]

    def test_no_matching_sheets_returns_empty(self):
        wb = MagicMock()
        wb.sheetnames = ["summary", "included"]
        config = {
            "sheet_pattern": "^interpret",
            "fields": [{"db_column": "hgvsc", "cell": "C3"}],
        }
        df = extract_named_cells_multi(wb, config)
        assert df.empty


# ---------------------------------------------------------------------------
# extract_tabular (with real workbook)
# ---------------------------------------------------------------------------

class TestExtractTabular:
    def test_extracts_rd_dias_included(self, rd_dias_cuh_workbook, rd_dias_cuh_path, rd_dias_config):
        sheet_config = rd_dias_config["sheets"]["included"]
        with patch.object(parser, "time") as mock_time:
            mock_time.sleep = MagicMock()
            df = extract_tabular(rd_dias_cuh_workbook, "included", sheet_config, rd_dias_cuh_path)

        assert "hgvsc" in df.columns
        assert "chromosome" in df.columns
        assert "local_id" in df.columns
        assert "linking_id" in df.columns
        assert len(df) == 2  # test workbook has 2 variants

    def test_interpreted_lowercased(self, rd_dias_cuh_workbook, rd_dias_cuh_path, rd_dias_config):
        sheet_config = rd_dias_config["sheets"]["included"]
        with patch.object(parser, "time") as mock_time:
            mock_time.sleep = MagicMock()
            df = extract_tabular(rd_dias_cuh_workbook, "included", sheet_config, rd_dias_cuh_path)

        assert df["interpreted"].isin(["yes", "no"]).all()

    def test_local_id_unique(self, rd_dias_cuh_workbook, rd_dias_cuh_path, rd_dias_config):
        sheet_config = rd_dias_config["sheets"]["included"]
        with patch.object(parser, "time") as mock_time:
            mock_time.sleep = MagicMock()
            df = extract_tabular(rd_dias_cuh_workbook, "included", sheet_config, rd_dias_cuh_path)

        assert df["local_id"].nunique() == len(df)

    def test_linking_id_equals_local_id(self, rd_dias_cuh_workbook, rd_dias_cuh_path, rd_dias_config):
        sheet_config = rd_dias_config["sheets"]["included"]
        with patch.object(parser, "time") as mock_time:
            mock_time.sleep = MagicMock()
            df = extract_tabular(rd_dias_cuh_workbook, "included", sheet_config, rd_dias_cuh_path)

        assert (df["local_id"] == df["linking_id"]).all()


# ---------------------------------------------------------------------------
# merge_dataframes
# ---------------------------------------------------------------------------

class TestMergeDataframes:
    def test_cross_join_then_left_join(self):
        summary = pd.DataFrame([{"sample_id": "S1", "panel": "P1"}])
        included = pd.DataFrame([
            {"hgvsc": "NM_1:c.100A>T", "chromosome": 1},
            {"hgvsc": "NM_2:c.200G>C", "chromosome": 2},
        ])
        interpret = pd.DataFrame([
            {"hgvsc": "NM_1:c.100A>T", "germline_classification": "Pathogenic"},
        ])
        merge_config = {
            "summary_x_included": {"how": "cross"},
            "included_join_interpret": {"on": "hgvsc", "how": "left"},
        }
        df = merge_dataframes(summary, included, interpret, merge_config)

        assert len(df) == 2
        assert "sample_id" in df.columns
        assert "germline_classification" in df.columns
        # Second variant has no interpret row → NaN classification
        row2 = df[df["hgvsc"] == "NM_2:c.200G>C"].iloc[0]
        assert pd.isna(row2["germline_classification"])

    def test_no_interpret_skips_join(self):
        summary = pd.DataFrame([{"sample_id": "S1"}])
        included = pd.DataFrame([{"hgvsc": "NM_1:c.100A>T"}])
        merge_config = {"summary_x_included": {"how": "cross"}}
        df = merge_dataframes(summary, included, None, merge_config)
        assert len(df) == 1
        assert "sample_id" in df.columns


# ---------------------------------------------------------------------------
# Integration: parse_workbook
# ---------------------------------------------------------------------------

class TestParseWorkbook:
    def test_rd_dias_parse_returns_dataframe(self, rd_dias_cuh_workbook, rd_dias_cuh_path, rd_dias_config):
        with patch.object(parser, "time") as mock_time:
            mock_time.sleep = MagicMock()
            df = parse_workbook(rd_dias_cuh_workbook, rd_dias_config, rd_dias_cuh_path)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert "hgvsc" in df.columns
        assert "germline_classification" in df.columns
        assert "sample_id" in df.columns
        assert "institution" in df.columns

    def test_rd_dias_constant_fields(self, rd_dias_cuh_workbook, rd_dias_cuh_path, rd_dias_config):
        with patch.object(parser, "time") as mock_time:
            mock_time.sleep = MagicMock()
            df = parse_workbook(rd_dias_cuh_workbook, rd_dias_config, rd_dias_cuh_path)

        assert df["allele_origin"].unique()[0] == "germline"
        assert df["collection_method"].unique()[0] == "clinical testing"
        assert df["affected_status"].unique()[0] == "yes"

    def test_rd_dias_summary_fields(self, rd_dias_cuh_workbook, rd_dias_cuh_path, rd_dias_config):
        with patch.object(parser, "time") as mock_time:
            mock_time.sleep = MagicMock()
            df = parse_workbook(rd_dias_cuh_workbook, rd_dias_config, rd_dias_cuh_path)

        assert df["ref_genome"][0] == "GRCh37.p13"
        assert "preferred_condition_name" in df.columns
        assert "r_code" in df.columns

    def test_haemonc_parse_returns_dataframe(self, haemonc_workbook, haemonc_path, haemonc_config):
        with patch.object(parser, "time") as mock_time:
            mock_time.sleep = MagicMock()
            df = parse_workbook(haemonc_workbook, haemonc_config, haemonc_path)

        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0
        assert "hgvsc" in df.columns
        assert "sample_id" in df.columns
        assert "allele_origin" in df.columns

    def test_haemonc_allele_origin_somatic(self, haemonc_workbook, haemonc_path, haemonc_config):
        with patch.object(parser, "time") as mock_time:
            mock_time.sleep = MagicMock()
            df = parse_workbook(haemonc_workbook, haemonc_config, haemonc_path)

        assert df["allele_origin"].unique()[0] == "somatic"
