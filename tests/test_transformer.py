"""Tests for transformer.py."""
import numpy as np
import pandas as pd
import pytest

from augean.transformer import (
    apply_derived_fields,
    apply_normalisations,
    apply_null_sentinels,
    build_acgs_comment,
    coerce_date_last_evaluated,
    make_acgs_criteria_null,
    transform,
)


class TestApplyNullSentinels:
    def test_replaces_dot_with_nan(self):
        df = pd.DataFrame({"hgvsp": ["NM_1:c.1A>T", "."], "vaf": ["0.5", "."]})
        result = apply_null_sentinels(df, [".", "./."])
        assert result["hgvsp"][0] == "NM_1:c.1A>T"
        assert pd.isna(result["hgvsp"][1])
        assert pd.isna(result["vaf"][1])

    def test_replaces_slash_dot_with_nan(self):
        df = pd.DataFrame({"prev_count": ["665/1706", "./."]})
        result = apply_null_sentinels(df, [".", "./."])
        assert result["prev_count"][0] == "665/1706"
        assert pd.isna(result["prev_count"][1])

    def test_empty_sentinels_noop(self):
        df = pd.DataFrame({"x": [".", "./.", "value"]})
        result = apply_null_sentinels(df, [])
        assert list(result["x"]) == [".", "./.", "value"]


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

    def test_two_pass_normalisation_chains(self):
        """Multi-pass normalisations chain: alias → canonical → final."""
        norms = [
            {"field": "oncogenicity_classification", "replace": {
                "VUS":               "Uncertain_significance",
                "Likely benign":     "Likely_benign",
                "Likely Benign":     "Likely_benign",
                "Likely Pathogenic": "Likely_oncogenic",
                "Likely pathogenic": "Likely_oncogenic",
                "Pathogenic":        "Oncogenic",
            }},
            {"field": "oncogenicity_classification", "replace": {
                "Likely_oncogenic":       "Likely oncogenic",
                "Uncertain_significance": "Uncertain significance",
                "Likely_benign":          "Likely benign",
            }},
        ]
        raw = ["VUS", "Likely benign", "Likely Benign",
               "Likely Pathogenic", "Likely pathogenic",
               "Pathogenic", "Benign", "Oncogenic"]
        df = pd.DataFrame({"oncogenicity_classification": raw})
        result = apply_normalisations(df, norms)
        expected = ["Uncertain significance", "Likely benign", "Likely benign",
                    "Likely oncogenic", "Likely oncogenic",
                    "Oncogenic", "Benign", "Oncogenic"]
        assert list(result["oncogenicity_classification"]) == expected


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
        "BS":  "Strong",
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


class TestCoerceDateLastEvaluated:
    def test_two_dates_takes_last(self):
        """07/01/2025 / 13/01/2026 → 13 Jan 2026."""
        df = pd.DataFrame({"date_last_evaluated": ["07/01/2025 / 13/01/2026"]})
        result = coerce_date_last_evaluated(df)
        assert result["date_last_evaluated"].iloc[0] == pd.Timestamp("2026-01-13")

    def test_same_month_boundary(self):
        """22/12/2025 / 23/12/2025 → 23 Dec 2025."""
        df = pd.DataFrame({"date_last_evaluated": ["22/12/2025 / 23/12/2025"]})
        result = coerce_date_last_evaluated(df)
        assert result["date_last_evaluated"].iloc[0] == pd.Timestamp("2025-12-23")

    def test_year_boundary(self):
        """31/12/2025 / 02/01/2026 → 2 Jan 2026."""
        df = pd.DataFrame({"date_last_evaluated": ["31/12/2025 / 02/01/2026"]})
        result = coerce_date_last_evaluated(df)
        assert result["date_last_evaluated"].iloc[0] == pd.Timestamp("2026-01-02")

    def test_hyphen_separator(self):
        """Dates separated by ' - ' instead of ' / '."""
        df = pd.DataFrame({"date_last_evaluated": ["07/01/2025 - 13/01/2026"]})
        result = coerce_date_last_evaluated(df)
        assert result["date_last_evaluated"].iloc[0] == pd.Timestamp("2026-01-13")

    def test_hyphen_same_month(self):
        """22/12/2025 - 23/12/2025 → 23 Dec 2025."""
        df = pd.DataFrame({"date_last_evaluated": ["22/12/2025 - 23/12/2025"]})
        result = coerce_date_last_evaluated(df)
        assert result["date_last_evaluated"].iloc[0] == pd.Timestamp("2025-12-23")

    def test_single_string_date_parsed(self):
        """Plain string date is parsed correctly."""
        df = pd.DataFrame({"date_last_evaluated": ["13/01/2026"]})
        result = coerce_date_last_evaluated(df)
        assert result["date_last_evaluated"].iloc[0] == pd.Timestamp("2026-01-13")

    def test_existing_datetime_unchanged(self):
        """Already-parsed datetime objects pass through untouched."""
        ts = pd.Timestamp("2026-01-13")
        df = pd.DataFrame({"date_last_evaluated": [ts]})
        result = coerce_date_last_evaluated(df)
        assert result["date_last_evaluated"].iloc[0] == ts

    def test_nan_unchanged(self):
        df = pd.DataFrame({"date_last_evaluated": [None]})
        result = coerce_date_last_evaluated(df)
        assert pd.isna(result["date_last_evaluated"].iloc[0])

    def test_column_absent_noop(self):
        df = pd.DataFrame({"other_col": [1]})
        result = coerce_date_last_evaluated(df)
        assert list(result.columns) == ["other_col"]

    def test_leading_backtick_stripped(self):
        """Backtick prefix (Excel text-force artefact) is stripped before parsing."""
        df = pd.DataFrame({"date_last_evaluated": ["`13/01/2026"]})
        result = coerce_date_last_evaluated(df)
        assert result["date_last_evaluated"].iloc[0] == pd.Timestamp("2026-01-13")

    def test_leading_apostrophe_stripped(self):
        """Apostrophe prefix is also stripped."""
        df = pd.DataFrame({"date_last_evaluated": ["'13/01/2026"]})
        result = coerce_date_last_evaluated(df)
        assert result["date_last_evaluated"].iloc[0] == pd.Timestamp("2026-01-13")


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
