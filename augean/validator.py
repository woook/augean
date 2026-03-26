"""Validate parsed DataFrames and workbook structure."""
import logging
import re

import pandas as pd

from augean.errors import ParseError

log = logging.getLogger(__name__)


def validate_structural(workbook, config: dict, workbook_name: str = "") -> list[ParseError]:
    """Check sentinel cells match expected values."""
    errors: list[ParseError] = []
    structural_checks = config.get("validations", {}).get("structural", [])

    for check in structural_checks:
        sheet_ref = check.get("sheet", "")
        cell = check.get("cell")
        expected = check.get("equals")
        error_msg = check.get("error", "Structural validation failed")

        if "*" in sheet_ref:
            pattern = sheet_ref.replace("*", ".*") + "$"
            matching = [s for s in workbook.sheetnames if re.match(pattern, s, re.IGNORECASE)]
            for sheet_name in matching:
                actual = workbook[sheet_name][cell].value
                if actual != expected:
                    errors.append(ParseError(workbook_name, "structural", error_msg))
        elif sheet_ref in workbook.sheetnames:
            actual = workbook[sheet_ref][cell].value
            if actual != expected:
                errors.append(ParseError(workbook_name, "structural", error_msg))

    return errors


def validate_fields(df: pd.DataFrame, config: dict, workbook_name: str = "") -> list[ParseError]:
    """Check in_list and not_null constraints per field."""
    errors: list[ParseError] = []
    field_checks = config.get("validations", {}).get("field", [])

    for check in field_checks:
        field = check["field"]
        check_type = check["type"]

        if field not in df.columns:
            continue

        if check_type == "not_null":
            nulls = df[field].isna()
            if nulls.any():
                errors.append(ParseError(
                    workbook_name, "field",
                    f"Field '{field}' has null values in {nulls.sum()} row(s)"
                ))

        elif check_type == "in_list":
            values = check["values"]
            non_null = df[field].dropna()
            invalid = non_null[~non_null.isin(values)]
            if not invalid.empty:
                errors.append(ParseError(
                    workbook_name, "field",
                    f"Field '{field}' has invalid value(s): {sorted(invalid.unique())}. "
                    f"Expected one of {values}"
                ))

    return errors


def validate_cross_sheet(df: pd.DataFrame, config: dict, workbook_name: str = "") -> list[ParseError]:
    """Check interpret HGVSc presence and interpreted/classification consistency."""
    errors: list[ParseError] = []
    cross_checks = config.get("validations", {}).get("cross_sheet", [])

    for check in cross_checks:
        check_name = check["check"]

        if check_name == "interpret_hgvsc_in_included":
            if "interpreted" in df.columns and "germline_classification" in df.columns:
                yes_rows = df[df["interpreted"] == "yes"]
                missing = yes_rows[yes_rows["germline_classification"].isna()]
                for _, row in missing.iterrows():
                    hgvsc = row.get("hgvsc", "unknown")
                    errors.append(ParseError(
                        workbook_name, "cross_sheet",
                        f"Variant '{hgvsc}' has interpreted=yes but no classification "
                        "from interpret sheet"
                    ))

        elif check_name == "interpreted_classification_consistency":
            if "interpreted" in df.columns and "germline_classification" in df.columns:
                no_rows = df[df["interpreted"] == "no"]
                has_class = no_rows[no_rows["germline_classification"].notna()]
                for _, row in has_class.iterrows():
                    hgvsc = row.get("hgvsc", "unknown")
                    errors.append(ParseError(
                        workbook_name, "cross_sheet",
                        f"Variant '{hgvsc}' has interpreted=no but has a classification"
                    ))

    return errors


def validate_acgs(df: pd.DataFrame, config: dict, workbook_name: str = "") -> list[ParseError]:
    """Check strength dropdown values for each ACGS criterion."""
    errors: list[ParseError] = []
    acgs_config = config.get("validations", {}).get("acgs", {})
    if not acgs_config:
        return errors

    criteria = acgs_config.get("criteria", [])
    strength_dropdown = acgs_config.get("strength_dropdown", [])
    ba1_dropdown = acgs_config.get("ba1_dropdown", [])

    for criterion in criteria:
        if criterion not in df.columns:
            continue
        valid_values = ba1_dropdown if criterion == "ba1" else strength_dropdown
        non_null = df[criterion].dropna()
        invalid = non_null[~non_null.isin(valid_values)]
        if not invalid.empty:
            errors.append(ParseError(
                workbook_name, "acgs",
                f"Wrong strength in {criterion}: {sorted(invalid.unique())}"
            ))

    return errors


def validate_all(
    workbook,
    df: pd.DataFrame,
    config: dict,
    workbook_name: str = "",
) -> list[ParseError]:
    """Run all validators; return combined error list."""
    errors: list[ParseError] = []
    errors.extend(validate_structural(workbook, config, workbook_name))
    errors.extend(validate_fields(df, config, workbook_name))
    errors.extend(validate_cross_sheet(df, config, workbook_name))
    errors.extend(validate_acgs(df, config, workbook_name))
    return errors
