"""Normalisation and derived-field transformations."""
import re
import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def apply_null_sentinels(df: pd.DataFrame, sentinels: list) -> pd.DataFrame:
    """Replace sentinel null values (e.g. '.', './.') with NaN across all columns."""
    if not sentinels:
        return df
    return df.replace(sentinels, np.nan)


def apply_normalisations(df: pd.DataFrame, normalisations: list) -> pd.DataFrame:
    """Apply replace-map normalisations to specified fields."""
    for norm in normalisations:
        field = norm["field"]
        if field in df.columns:
            df[field] = df[field].replace(norm.get("replace", {}))
    return df


def make_acgs_criteria_null(df: pd.DataFrame, criteria: list) -> pd.DataFrame:
    """Replace 'NA' with NaN for ACGS criteria; null evidence if criterion is null."""
    for criterion in criteria:
        if criterion not in df.columns:
            continue
        df.loc[df[criterion] == "NA", criterion] = np.nan

    for criterion in criteria:
        if criterion not in df.columns:
            continue
        evidence_col = f"{criterion}_evidence"
        if evidence_col in df.columns:
            df.loc[df[criterion].isna(), evidence_col] = np.nan

    return df


def build_acgs_comment(df: pd.DataFrame, derived_config: dict) -> pd.DataFrame:
    """Build comment_on_classification string per row.

    If a criterion was applied at its default strength, it appears without
    a suffix (e.g. "PVS1"). If at non-default strength, appended with the
    strength (e.g. "PS4_Moderate").
    """
    criteria = derived_config.get("criteria", [])
    matched_strength = derived_config.get("matched_strength", {})
    db_col = derived_config.get("db_column", "comment_on_classification")

    df[db_col] = ""

    for index, row in df.iterrows():
        parts = []
        for criterion in criteria:
            if criterion not in df.columns:
                continue
            val = row.get(criterion)
            if pd.isna(val):
                continue
            prefix = criterion.upper()[:-1]  # "pvs1" → "PVS", "pm1" → "PM"
            label = criterion.upper()
            if matched_strength.get(prefix) == val:
                parts.append(label)
            else:
                parts.append(f"{label}_{val}")
        df.loc[index, db_col] = ",".join(parts)

    return df


def apply_derived_fields(df: pd.DataFrame, derived_fields: list[dict]) -> pd.DataFrame:
    """Dispatch to the appropriate derivation function by type."""
    for field_config in derived_fields:
        field_type = field_config.get("type")
        if field_type == "acgs_comment":
            df = build_acgs_comment(df, field_config)
        else:
            log.warning("Unknown derived field type: %s", field_type)
    return df


def coerce_date_last_evaluated(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise date_last_evaluated to a parseable date value.

    Handles cases caused by manual workbook edits:
    - Leading backtick or apostrophe (Excel text-prefix artefact) — stripped.
    - Multiple dates separated by ' / ' or ' - ' (e.g. '07/01/2025 / 13/01/2026') —
      takes the last entry, which is the most recent review date.
    - A plain date string (e.g. '13/01/2026') — parses it to datetime.

    Rows where the value is already a datetime or NaN are left unchanged.
    """
    col = "date_last_evaluated"
    if col not in df.columns:
        return df

    def _resolve(val):
        if pd.isna(val) or isinstance(val, (pd.Timestamp, type(pd.NaT))):
            return val
        if hasattr(val, 'date'):  # already a datetime-like
            return val
        s = str(val).strip().lstrip("`'")
        if re.search(r'\s+[/\-]\s+', s):
            s = re.split(r'\s+[/\-]\s+', s)[-1].strip()
            log.warning(
                "date_last_evaluated contained multiple dates; using last: '%s'", s
            )
        try:
            return pd.to_datetime(s, dayfirst=True)
        except (ValueError, TypeError):
            log.warning("Could not parse date_last_evaluated value: '%s'", s)
            return pd.NaT

    df[col] = pd.to_datetime(df[col].apply(_resolve), errors="coerce")
    return df


def transform(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Orchestrate: null sentinels → normalisations → coerce dates → ACGS null → derived fields."""
    df = apply_null_sentinels(df, config.get("null_sentinels", []))
    df = apply_normalisations(df, config.get("normalisations", []))
    df = coerce_date_last_evaluated(df)

    acgs_config = config.get("validations", {}).get("acgs", {})
    if acgs_config:
        df = make_acgs_criteria_null(df, acgs_config.get("criteria", []))

    df = apply_derived_fields(df, config.get("derived_fields", []))

    return df
