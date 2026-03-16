"""Tests for validator.py."""
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from hestia.errors import ParseError
from hestia.validator import (
    validate_acgs,
    validate_all,
    validate_cross_sheet,
    validate_fields,
    validate_structural,
)


# ---------------------------------------------------------------------------
# validate_structural
# ---------------------------------------------------------------------------

class TestValidateStructural:
    def _make_wb(self, sheetnames, cells):
        wb = MagicMock()
        wb.sheetnames = sheetnames

        def get_sheet(name):
            s = MagicMock()
            sheet_cells = cells.get(name, {})
            s.__getitem__ = lambda self, k: MagicMock(value=sheet_cells.get(k))
            return s

        wb.__getitem__ = lambda s, k: get_sheet(k)
        return wb

    def test_no_errors_when_cells_match(self):
        wb = self._make_wb(["summary"], {"summary": {"G21": "Date"}})
        config = {
            "validations": {
                "structural": [
                    {"sheet": "summary", "cell": "G21", "equals": "Date",
                     "error": "summary broken"}
                ]
            }
        }
        errors = validate_structural(wb, config, "test.xlsx")
        assert errors == []

    def test_error_when_cell_mismatch(self):
        wb = self._make_wb(["summary"], {"summary": {"G21": "Wrong"}})
        config = {
            "validations": {
                "structural": [
                    {"sheet": "summary", "cell": "G21", "equals": "Date",
                     "error": "summary broken"}
                ]
            }
        }
        errors = validate_structural(wb, config, "test.xlsx")
        assert len(errors) == 1
        assert errors[0].stage == "structural"
        assert errors[0].message == "summary broken"

    def test_pattern_sheet_checks_all_matching(self):
        wb = self._make_wb(
            ["summary", "interpret_1", "interpret_2"],
            {
                "interpret_1": {"B26": "FINAL ACMG CLASSIFICATION"},
                "interpret_2": {"B26": "WRONG VALUE"},
            },
        )
        config = {
            "validations": {
                "structural": [
                    {"sheet": "interpret*", "cell": "B26",
                     "equals": "FINAL ACMG CLASSIFICATION",
                     "error": "interpret sheet broken"}
                ]
            }
        }
        errors = validate_structural(wb, config, "test.xlsx")
        assert len(errors) == 1
        assert "interpret sheet broken" in errors[0].message

    def test_empty_validations(self):
        wb = self._make_wb(["summary"], {})
        errors = validate_structural(wb, {}, "test.xlsx")
        assert errors == []


# ---------------------------------------------------------------------------
# validate_fields
# ---------------------------------------------------------------------------

class TestValidateFields:
    def test_in_list_passes(self):
        df = pd.DataFrame({"germline_classification": ["Pathogenic", "Benign"]})
        config = {
            "validations": {
                "field": [
                    {"field": "germline_classification", "type": "in_list",
                     "values": ["Pathogenic", "Benign", "Likely pathogenic"]}
                ]
            }
        }
        errors = validate_fields(df, config, "test.xlsx")
        assert errors == []

    def test_in_list_fails_with_invalid_value(self):
        df = pd.DataFrame({"germline_classification": ["Pathogenic", "InvalidValue"]})
        config = {
            "validations": {
                "field": [
                    {"field": "germline_classification", "type": "in_list",
                     "values": ["Pathogenic", "Benign"]}
                ]
            }
        }
        errors = validate_fields(df, config, "test.xlsx")
        assert len(errors) == 1
        assert errors[0].stage == "field"
        assert "InvalidValue" in errors[0].message

    def test_in_list_ignores_nulls(self):
        df = pd.DataFrame({"interpreted": ["yes", np.nan, "no"]})
        config = {
            "validations": {
                "field": [{"field": "interpreted", "type": "in_list", "values": ["yes", "no"]}]
            }
        }
        errors = validate_fields(df, config, "test.xlsx")
        assert errors == []

    def test_not_null_passes(self):
        df = pd.DataFrame({"hgvsc": ["NM_1:c.1A>T", "NM_2:c.2G>C"]})
        config = {
            "validations": {"field": [{"field": "hgvsc", "type": "not_null"}]}
        }
        errors = validate_fields(df, config, "test.xlsx")
        assert errors == []

    def test_not_null_fails(self):
        df = pd.DataFrame({"hgvsc": ["NM_1:c.1A>T", None]})
        config = {
            "validations": {"field": [{"field": "hgvsc", "type": "not_null"}]}
        }
        errors = validate_fields(df, config, "test.xlsx")
        assert len(errors) == 1
        assert errors[0].stage == "field"

    def test_missing_field_skipped(self):
        df = pd.DataFrame({"other_field": ["val"]})
        config = {
            "validations": {
                "field": [{"field": "nonexistent", "type": "not_null"}]
            }
        }
        errors = validate_fields(df, config, "test.xlsx")
        assert errors == []


# ---------------------------------------------------------------------------
# validate_cross_sheet
# ---------------------------------------------------------------------------

class TestValidateCrossSheet:
    def test_no_error_when_interpreted_has_classification(self):
        df = pd.DataFrame({
            "interpreted": ["yes", "no"],
            "germline_classification": ["Pathogenic", np.nan],
            "hgvsc": ["NM_1:c.1A>T", "NM_2:c.2G>C"],
        })
        config = {
            "validations": {
                "cross_sheet": [
                    {"check": "interpret_hgvsc_in_included"},
                    {"check": "interpreted_classification_consistency"},
                ]
            }
        }
        errors = validate_cross_sheet(df, config, "test.xlsx")
        assert errors == []

    def test_error_when_yes_has_no_classification(self):
        df = pd.DataFrame({
            "interpreted": ["yes"],
            "germline_classification": [np.nan],
            "hgvsc": ["NM_1:c.1A>T"],
        })
        config = {
            "validations": {
                "cross_sheet": [{"check": "interpret_hgvsc_in_included"}]
            }
        }
        errors = validate_cross_sheet(df, config, "test.xlsx")
        assert len(errors) == 1
        assert "interpreted=yes" in errors[0].message

    def test_error_when_no_has_classification(self):
        df = pd.DataFrame({
            "interpreted": ["no"],
            "germline_classification": ["Pathogenic"],
            "hgvsc": ["NM_1:c.1A>T"],
        })
        config = {
            "validations": {
                "cross_sheet": [{"check": "interpreted_classification_consistency"}]
            }
        }
        errors = validate_cross_sheet(df, config, "test.xlsx")
        assert len(errors) == 1
        assert "interpreted=no" in errors[0].message

    def test_multiple_errors_all_captured(self):
        df = pd.DataFrame({
            "interpreted": ["yes", "yes"],
            "germline_classification": [np.nan, np.nan],
            "hgvsc": ["NM_1:c.1A>T", "NM_2:c.2G>C"],
        })
        config = {
            "validations": {
                "cross_sheet": [{"check": "interpret_hgvsc_in_included"}]
            }
        }
        errors = validate_cross_sheet(df, config, "test.xlsx")
        assert len(errors) == 2


# ---------------------------------------------------------------------------
# validate_acgs
# ---------------------------------------------------------------------------

class TestValidateAcgs:
    def test_valid_strengths_no_error(self):
        df = pd.DataFrame({"pvs1": ["Very Strong"], "ps1": ["Strong"]})
        config = {
            "validations": {
                "acgs": {
                    "criteria": ["pvs1", "ps1"],
                    "strength_dropdown": ["Very Strong", "Strong", "Moderate", "Supporting", "NA"],
                    "ba1_dropdown": ["Stand-Alone", "Very Strong", "Strong", "Moderate", "Supporting", "NA"],
                }
            }
        }
        errors = validate_acgs(df, config, "test.xlsx")
        assert errors == []

    def test_invalid_strength_raises_error(self):
        df = pd.DataFrame({"pvs1": ["InvalidStrength"]})
        config = {
            "validations": {
                "acgs": {
                    "criteria": ["pvs1"],
                    "strength_dropdown": ["Very Strong", "Strong", "NA"],
                    "ba1_dropdown": [],
                }
            }
        }
        errors = validate_acgs(df, config, "test.xlsx")
        assert len(errors) == 1
        assert "pvs1" in errors[0].message

    def test_ba1_uses_separate_dropdown(self):
        df = pd.DataFrame({"ba1": ["Stand-Alone"]})
        config = {
            "validations": {
                "acgs": {
                    "criteria": ["ba1"],
                    "strength_dropdown": ["Very Strong", "Strong", "NA"],
                    "ba1_dropdown": ["Stand-Alone", "Very Strong", "Strong", "NA"],
                }
            }
        }
        errors = validate_acgs(df, config, "test.xlsx")
        assert errors == []

    def test_null_criteria_ignored(self):
        df = pd.DataFrame({"pvs1": [np.nan]})
        config = {
            "validations": {
                "acgs": {
                    "criteria": ["pvs1"],
                    "strength_dropdown": ["Very Strong", "NA"],
                    "ba1_dropdown": [],
                }
            }
        }
        errors = validate_acgs(df, config, "test.xlsx")
        assert errors == []

    def test_no_acgs_config_returns_empty(self):
        df = pd.DataFrame({"pvs1": ["Very Strong"]})
        errors = validate_acgs(df, {}, "test.xlsx")
        assert errors == []


# ---------------------------------------------------------------------------
# validate_all
# ---------------------------------------------------------------------------

class TestValidateAll:
    def test_accumulates_errors_from_all_stages(self):
        wb = MagicMock()
        wb.sheetnames = ["summary"]

        def get_sheet(name):
            s = MagicMock()
            s.__getitem__ = lambda self, k: MagicMock(value="Wrong")
            return s

        wb.__getitem__ = lambda s, k: get_sheet(k)

        df = pd.DataFrame({
            "interpreted": ["bad_value"],
            "hgvsc": [None],
            "germline_classification": [np.nan],
        })
        config = {
            "validations": {
                "structural": [
                    {"sheet": "summary", "cell": "G21", "equals": "Date",
                     "error": "structural error"}
                ],
                "field": [
                    {"field": "hgvsc", "type": "not_null"},
                    {"field": "interpreted", "type": "in_list", "values": ["yes", "no"]},
                ],
                "cross_sheet": [],
                "acgs": {},
            }
        }
        errors = validate_all(wb, df, config, "test.xlsx")
        stages = {e.stage for e in errors}
        assert "structural" in stages
        assert "field" in stages
        assert len(errors) >= 3
