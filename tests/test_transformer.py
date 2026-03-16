"""Tests for transformer.py."""
import numpy as np
import pandas as pd
import pytest

from hestia.transformer import (
    apply_derived_fields,
    apply_normalisations,
    build_acgs_comment,
    make_acgs_criteria_null,
    transform,
)


class TestApplyNormalisations:
    def test_replaces_values(self):
        df = pd.DataFrame({"germline_classification": ["Likely Pathogenic", "Benign"]})
        norms = [
            {"field": "germline_classification",
             "replace": {"Likely Pathogenic": "Likely pathogenic"}}
        ]
        result = apply_normalisations(df, norms)
        assert result["germline_classification"][0] == "Likely pathogenic"
        assert result["germline_classification"][1] == "Benign"

    def test_missing_field_skipped(self):
        df = pd.DataFrame({"other": ["val"]})
        norms = [{"field": "nonexistent", "replace": {"x": "y"}}]
        result = apply_normalisations(df, norms)
        assert "other" in result.columns

    def test_empty_normalisations(self):
        df = pd.DataFrame({"field": ["val"]})
        result = apply_normalisations(df, [])
        assert list(result["field"]) == ["val"]


class TestMakeAcgsCriteriaNull:
    def test_replaces_na_with_nan(self):
        df = pd.DataFrame({"pvs1": ["Very Strong", "NA", None]})
        result = make_acgs_criteria_null(df, ["pvs1"])
        assert result["pvs1"][0] == "Very Strong"
        assert pd.isna(result["pvs1"][1])
        assert pd.isna(result["pvs1"][2])

    def test_nulls_evidence_when_criterion_null(self):
        df = pd.DataFrame({
            "pvs1": ["NA"],
            "pvs1_evidence": ["Some evidence"],
        })
        result = make_acgs_criteria_null(df, ["pvs1"])
        assert pd.isna(result["pvs1"][0])
        assert pd.isna(result["pvs1_evidence"][0])

    def test_evidence_preserved_when_criterion_set(self):
        df = pd.DataFrame({
            "ps4": ["Strong"],
            "ps4_evidence": ["PMID: 12345"],
        })
        result = make_acgs_criteria_null(df, ["ps4"])
        assert result["ps4"][0] == "Strong"
        assert result["ps4_evidence"][0] == "PMID: 12345"

    def test_missing_criterion_skipped(self):
        df = pd.DataFrame({"other": ["val"]})
        result = make_acgs_criteria_null(df, ["pvs1"])
        assert "other" in result.columns

    def test_missing_evidence_col_no_error(self):
        df = pd.DataFrame({"pvs1": ["NA"]})
        result = make_acgs_criteria_null(df, ["pvs1"])
        assert pd.isna(result["pvs1"][0])


class TestBuildAcgsComment:
    MATCHED = {
        "PVS": "Very Strong",
        "PS":  "Strong",
        "PM":  "Moderate",
        "PP":  "Supporting",
        "BS":  "Supporting",
        "BA":  "Stand-Alone",
        "BP":  "Supporting",
    }

    def test_default_strength_no_suffix(self):
        df = pd.DataFrame({"pvs1": ["Very Strong"]})
        config = {
            "db_column": "comment_on_classification",
            "criteria": ["pvs1"],
            "matched_strength": self.MATCHED,
        }
        result = build_acgs_comment(df, config)
        assert result["comment_on_classification"][0] == "PVS1"

    def test_non_default_strength_has_suffix(self):
        df = pd.DataFrame({"ps4": ["Moderate"]})
        config = {
            "db_column": "comment_on_classification",
            "criteria": ["ps4"],
            "matched_strength": self.MATCHED,
        }
        result = build_acgs_comment(df, config)
        assert result["comment_on_classification"][0] == "PS4_Moderate"

    def test_null_criterion_excluded(self):
        df = pd.DataFrame({"pvs1": ["Very Strong"], "pm1": [np.nan]})
        config = {
            "db_column": "comment_on_classification",
            "criteria": ["pvs1", "pm1"],
            "matched_strength": self.MATCHED,
        }
        result = build_acgs_comment(df, config)
        assert result["comment_on_classification"][0] == "PVS1"

    def test_multiple_criteria_comma_separated(self):
        df = pd.DataFrame({"pvs1": ["Very Strong"], "ps4": ["Moderate"]})
        config = {
            "db_column": "comment_on_classification",
            "criteria": ["pvs1", "ps4"],
            "matched_strength": self.MATCHED,
        }
        result = build_acgs_comment(df, config)
        assert result["comment_on_classification"][0] == "PVS1,PS4_Moderate"

    def test_empty_df_returns_empty_comment(self):
        df = pd.DataFrame({"pvs1": []})
        config = {
            "db_column": "comment_on_classification",
            "criteria": ["pvs1"],
            "matched_strength": self.MATCHED,
        }
        result = build_acgs_comment(df, config)
        assert len(result) == 0


class TestApplyDerivedFields:
    def test_acgs_comment_dispatched(self):
        df = pd.DataFrame({"pvs1": ["Very Strong"]})
        derived = [
            {
                "db_column": "comment_on_classification",
                "type": "acgs_comment",
                "criteria": ["pvs1"],
                "matched_strength": {"PVS": "Very Strong"},
            }
        ]
        result = apply_derived_fields(df, derived)
        assert "comment_on_classification" in result.columns

    def test_unknown_type_skipped(self):
        df = pd.DataFrame({"col": ["val"]})
        result = apply_derived_fields(df, [{"type": "unknown_type", "db_column": "x"}])
        assert "col" in result.columns


class TestTransform:
    def test_full_pipeline(self):
        df = pd.DataFrame({
            "germline_classification": ["Likely Pathogenic"],
            "pvs1": ["NA"],
            "pvs1_evidence": ["evidence"],
        })
        config = {
            "normalisations": [
                {"field": "germline_classification",
                 "replace": {"Likely Pathogenic": "Likely pathogenic"}}
            ],
            "validations": {
                "acgs": {
                    "criteria": ["pvs1"],
                    "strength_dropdown": ["Very Strong", "NA"],
                    "ba1_dropdown": [],
                }
            },
            "derived_fields": [
                {
                    "db_column": "comment_on_classification",
                    "type": "acgs_comment",
                    "criteria": ["pvs1"],
                    "matched_strength": {"PVS": "Very Strong"},
                }
            ],
        }
        result = transform(df, config)
        assert result["germline_classification"][0] == "Likely pathogenic"
        assert pd.isna(result["pvs1"][0])
        assert pd.isna(result["pvs1_evidence"][0])
        assert result["comment_on_classification"][0] == ""
