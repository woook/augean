"""Extract sheets from Excel workbooks into DataFrames per config."""
import logging
import re
import time
import uuid
from datetime import date
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)


def extract_named_cells(workbook, sheet_name: str, sheet_config: dict) -> pd.DataFrame:
    """Extract a single-row DataFrame from named cell references.

    Supports:
    - Regular cell references (cell address → db_column)
    - sentinel_scan: scan a column for a label, read adjacent cell
    - clinical_indication_split parse type: produces preferred_condition_name + r_code
    - sample_id_split parse type: produces instrument_id, specimen_id, batch_id, test_code, probeset_id
    """
    sheet = workbook[sheet_name]
    row: dict = {}

    for field in sheet_config.get("fields", []):
        db_col = field["db_column"]

        if field.get("extraction") == "sentinel_scan":
            value = _sentinel_scan(
                sheet,
                scan_column=field["scan_column"],
                sentinel_value=field["sentinel_value"],
                value_column=field["value_column"],
                default=field.get("default"),
            )
            row[db_col] = value
            continue

        cell_val = sheet[field["cell"]].value

        if field.get("parse") == "clinical_indication_split":
            names, codes = _split_clinical_indication(cell_val)
            row["preferred_condition_name"] = names
            row["r_code"] = codes
            # db_col itself is not stored; split produces the above two columns
            continue

        if field.get("parse") == "sample_id_split":
            row.update(_split_sample_id(cell_val))
            continue

        if cell_val is None:
            default = field.get("default")
            if field.get("type") == "date" and default == "today":
                cell_val = str(date.today())
            else:
                cell_val = default

        row[db_col] = cell_val

    return pd.DataFrame([row])


def extract_label_scan(workbook, sheet_name: str, sheet_config: dict) -> pd.DataFrame:
    """Extract a single-row DataFrame by scanning column A for label strings.

    Reads the adjacent value column (typically B) for each matched label.
    Used by HaemOnc Uranus summary sheet.
    """
    sheet = workbook[sheet_name]
    scan_col = sheet_config["scan_column"]
    value_col = sheet_config["value_column"]

    label_to_row: dict[str, int] = {}
    for cell in sheet[scan_col]:
        if cell.value is not None:
            label_to_row[str(cell.value).strip()] = cell.row

    row: dict = {}
    for field in sheet_config.get("fields", []):
        db_col = field["db_column"]
        label = field.get("label", "")
        row_num = label_to_row.get(label)

        if row_num is not None:
            cell_val = sheet[f"{value_col}{row_num}"].value
        else:
            cell_val = None

        if cell_val is None:
            default = field.get("default")
            cell_val = str(date.today()) if default == "today" else default

        if field.get("parse") == "sample_id_split":
            row.update(_split_sample_id(cell_val))
            continue

        row[db_col] = cell_val

    return pd.DataFrame([row])


def extract_tabular(
    workbook,
    sheet_name: str,
    sheet_config: dict,
    filename: Path,
    context_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Extract a tabular sheet using pd.read_excel; add generated columns."""
    nrows = None
    if "row_count_ref" in sheet_config:
        ref = sheet_config["row_count_ref"]
        nrows = workbook[ref["sheet"]][ref["cell"]].value

    columns = sheet_config.get("columns", [])
    source_cols = [c["source"] for c in columns]

    df = pd.read_excel(str(filename), sheet_name=sheet_name, usecols=source_cols, nrows=nrows)

    rename_map = {c["source"]: c["db_column"] for c in columns}
    df.rename(columns=rename_map, inplace=True)

    for col_config in columns:
        db_col = col_config["db_column"]
        if db_col not in df.columns:
            continue
        transform = col_config.get("transform")
        if transform == "lowercase":
            df[db_col] = df[db_col].str.lower()
        elif transform == "boolean_to_yes_no":
            df[db_col] = df[db_col].map({True: "yes", False: "no", 1: "yes", 0: "no"})

    for gen_col in sheet_config.get("generated_columns", []):
        db_col = gen_col["db_column"]
        if gen_col.get("generation") == "uuid_time":
            ids = []
            for _ in range(len(df)):
                unique_id = uuid.uuid1()
                ids.append(f"uid_{unique_id.time}")
                time.sleep(0.5)
            df[db_col] = ids
        elif "source" in gen_col:
            source = gen_col["source"]
            if source in df.columns:
                df[db_col] = df[source]

    return df


def extract_named_cells_multi(workbook, sheet_config: dict) -> pd.DataFrame:
    """Extract one row per sheet matching the sheet_pattern (e.g. interpret*)."""
    pattern = sheet_config.get("sheet_pattern", "^interpret")
    matching_sheets = [
        s for s in workbook.sheetnames if re.match(pattern, s, re.IGNORECASE)
    ]

    fields = sheet_config.get("fields", [])
    col_names = [f["db_column"] for f in fields]
    rows = []

    for sheet_name in matching_sheets:
        sheet = workbook[sheet_name]
        row: dict = {}
        for field in fields:
            db_col = field["db_column"]
            row[db_col] = sheet[field["cell"]].value
        rows.append(row)

    df = pd.DataFrame(rows, columns=col_names)
    df.reset_index(drop=True, inplace=True)
    return df


def merge_dataframes(
    summary_df: pd.DataFrame,
    included_df: pd.DataFrame,
    interpret_df: pd.DataFrame | None,
    merge_config: dict,
) -> pd.DataFrame:
    """Apply cross join then optional left join per merge_strategy config."""
    if not included_df.empty and not summary_df.empty:
        df_merged = pd.merge(included_df, summary_df, how="cross")
    elif not summary_df.empty:
        df_merged = summary_df.copy()
    else:
        df_merged = included_df.copy()

    if interpret_df is not None and not interpret_df.empty:
        join_cfg = merge_config.get("included_join_interpret", {})
        on_col = join_cfg.get("on", "hgvsc")
        how = join_cfg.get("how", "left")
        df_merged = pd.merge(df_merged, interpret_df, on=on_col, how=how)

    return df_merged


def parse_workbook(workbook, config: dict, filename: Path) -> pd.DataFrame:
    """Orchestrate: extract all sheets, merge, add constant fields."""
    sheets = config.get("sheets", {})
    merge_config = config.get("merge_strategy", {})

    summary_df = pd.DataFrame()
    included_dfs: list[pd.DataFrame] = []
    interpret_df: pd.DataFrame | None = None

    for sheet_key, sheet_config in sheets.items():
        extraction_type = sheet_config.get("extraction_type")

        if extraction_type == "named_cells":
            summary_df = extract_named_cells(workbook, sheet_key, sheet_config)
            log.debug("Extracted named_cells sheet '%s': %d fields", sheet_key, len(summary_df.columns))

        elif extraction_type == "label_scan":
            summary_df = extract_label_scan(workbook, sheet_key, sheet_config)
            log.debug("Extracted label_scan sheet '%s': %d fields", sheet_key, len(summary_df.columns))

        elif extraction_type == "tabular":
            df = extract_tabular(workbook, sheet_key, sheet_config, filename)
            included_dfs.append(df)
            log.debug("Extracted tabular sheet '%s': %d rows", sheet_key, len(df))

        elif extraction_type == "named_cells_multi":
            interpret_df = extract_named_cells_multi(workbook, sheet_config)
            log.debug("Extracted named_cells_multi: %d rows", len(interpret_df))

    # Add constant fields to summary
    constant_fields = config.get("constant_fields", {})
    if not summary_df.empty:
        for key, val in constant_fields.items():
            summary_df[key] = val
    else:
        summary_df = pd.DataFrame([constant_fields])

    if included_dfs:
        included_df = pd.concat(included_dfs, ignore_index=True)
    else:
        included_df = pd.DataFrame()

    return merge_dataframes(summary_df, included_df, interpret_df, merge_config)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sentinel_scan(sheet, scan_column: str, sentinel_value: str, value_column: str, default=None):
    for cell in sheet[scan_column]:
        if cell.value == sentinel_value:
            return sheet[f"{value_column}{cell.row}"].value
    return default


def _split_sample_id(raw_value) -> dict:
    """Split a composite sample ID into component fields.

    Format: [InstrumentID]-[SpecimenID]-[BatchID]-[Testcode]-[Sex]-[ProbesetID]
    e.g. 100033006-22363S0007-23NGSHO1-8128-M-96527893
    Sex (index 4) is ignored — no db column.
    """
    if raw_value is None:
        return {}
    parts = str(raw_value).split("-", 5)
    keys = ["instrument_id", "specimen_id", "batch_id", "test_code", None, "probeset_id"]
    return {k: v for k, v in zip(keys, parts) if k is not None}


def _split_clinical_indication(raw_value) -> tuple[str, str]:
    """Split a clinical indication string into (condition_names, r_codes).

    Input format: "R208.1_Condition name_P" or "R208.1_Condition;R207.1_Other"
    Returns: ("Condition name", "R208.1") or ("Condition;Other", "R208.1;R207.1")
    """
    if raw_value is None:
        return "", ""

    value = str(raw_value)
    parts = [p.strip() for p in value.split(";")]
    condition_names = []
    test_codes = []

    for part in parts:
        segments = part.split("_")
        test_codes.append(segments[0])
        condition_names.append(segments[1] if len(segments) > 1 else part)

    return ";".join(condition_names), ";".join(test_codes)
