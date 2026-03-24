# Config Authoring Guide

This guide explains how to write or extend a format config. It is the primary extension point — adding support for a new workbook format requires only a new JSON file, no code changes.

See `configs/template.json` for a fully annotated skeleton to copy from.

---

## Top-level structure

```json
{
  "format_name": "my_format_v1",
  "format_version": "1.0",
  "fingerprint": [ ... ],
  "sheets": { ... },
  "merge_strategy": { ... },
  "constant_fields": { ... },
  "null_sentinels": [ ... ],
  "normalisations": [ ... ],
  "derived_fields": [ ... ],
  "validations": { ... }
}
```

`format_name` must be unique across all configs in the config directory.

---

## Fingerprinting

When augean opens a workbook, it needs to know which config to apply. It does this automatically by testing the workbook against a set of rules — the "fingerprint" — defined in each config. If all rules in a config's fingerprint match the workbook, that config is selected. If no config matches, or more than one matches, an error is raised.

**All rules must match** for the format to be selected.

```json
"fingerprint": [
  { "sheet": "summary", "cell": "A5", "equals": "Subpanel analysed" },
  { "sheet": "summary", "cell": "B1", "matches_pattern": "^\\d{9}-" },
  { "sheet": "m_codes", "exists": true },
  { "sheet_pattern": "^interpret", "exists": true },
  { "sheet": "included", "has_columns": ["HGVSc", "CHROM", "POS"] }
]
```

| Rule key | Type | Description |
|----------|------|-------------|
| `sheet` + `cell` + `equals` | string | Cell must contain exactly this value |
| `sheet` + `cell` + `matches_pattern` | regex | Cell value must match the pattern |
| `sheet` + `exists` | bool | Sheet must exist (or must not exist if `false`) |
| `sheet_pattern` + `exists` | regex | At least one sheet name matching the pattern must exist |
| `sheet` + `has_columns` | list | Sheet must contain all named column headers |

---

## Sheets

Each workbook sheet that augean reads must declare an `extraction_type` in the config. This tells augean how to read it — different workbook layouts require different strategies. The key under `sheets` is usually the exact sheet name (except for `named_cells_multi`, where the actual sheet names are determined at runtime by a pattern).

There are four extraction types:

| Type | When to use |
|------|-------------|
| `named_cells` | Fields are at fixed, known cell addresses (e.g. sample ID always in B1) |
| `label_scan` | Fields are stored as label/value pairs in a column (no fixed row positions) |
| `tabular` | A columnar variant table read with `pd.read_excel` |
| `named_cells_multi` | One row per sheet whose name matches a pattern (e.g. one interpret sheet per variant) |

The sections below describe each type in detail.

### `named_cells` — fixed cell addresses

```json
"summary": {
  "extraction_type": "named_cells",
  "fields": [
    { "db_column": "panel",    "cell": "F2" },
    { "db_column": "ref_genome",
      "extraction": "sentinel_scan",
      "scan_column": "A", "sentinel_value": "Reference:", "value_column": "B",
      "default": "not_defined" },
    { "db_column": "clinical_indication", "cell": "F1",
      "parse": "clinical_indication_split" },
    { "db_column": "sample_id", "cell": "B1",
      "parse": "sample_id_split" },
    { "db_column": "date_last_evaluated", "cell": "G22",
      "type": "date", "default": "today" }
  ]
}
```

- `cell` — Excel address (e.g. `"B1"`)
- `default` — value to use if cell is empty; `"today"` inserts today's date
- `type: "date"` — required alongside `default: "today"` in `named_cells` to trigger date substitution
- `extraction: "sentinel_scan"` — scan `scan_column` for `sentinel_value`, then read `value_column` on the same row

### `label_scan` — label/value pairs

```json
"summary": {
  "extraction_type": "label_scan",
  "scan_column": "A",
  "value_column": "B",
  "fields": [
    { "label": "Sample ID",      "db_column": "sample_id", "parse": "sample_id_split" },
    { "label": "Date",           "db_column": "date_last_evaluated" },
    { "label": "Subpanel analysed", "db_column": "panel" },
    { "label": "Reference:",     "db_column": "ref_genome" }
  ]
}
```

Scans `scan_column` for cells whose text matches `label`; reads the value from `value_column` on the same row. Order of labels in the sheet does not matter.

### `tabular` — columnar variant table

```json
"included": {
  "extraction_type": "tabular",
  "row_count_ref": { "sheet": "summary", "cell": "C38" },
  "columns": [
    { "source": "CHROM",          "db_column": "chromosome" },
    { "source": "Classification", "db_column": "oncogenicity_classification" },
    { "source": "Interpreted",    "db_column": "interpreted" }
  ],
  "generated_columns": [
    { "db_column": "local_id",   "generation": "uuid_time" },
    { "db_column": "linking_id", "source": "local_id" }
  ]
}
```

- `source` — the exact column header in the Excel sheet
- `row_count_ref` — optional; limits rows read to the value in a specific cell (avoids reading trailing blank rows)
- `transform` — optional per-column transform:
  - `"lowercase"` — converts string values to lower case
  - `"boolean_to_yes_no"` — maps `True/False/1/0` to `"yes"/"no"` (for Excel checkbox columns)
- `generated_columns` — columns added programmatically:
  - `generation: "uuid_time"` — generates a time-based UUID string (`uid_<timestamp>`)
  - `source: "<col>"` — copies an existing column (used for `linking_id = local_id`)

### `named_cells_multi` — one row per matching sheet

```json
"interpret": {
  "extraction_type": "named_cells_multi",
  "sheet_pattern": "^interpret",
  "fields": [
    { "db_column": "hgvsc",                   "cell": "C3" },
    { "db_column": "germline_classification", "cell": "C26" },
    { "db_column": "pvs1",                    "cell": "H10" },
    { "db_column": "pvs1_evidence",           "cell": "C10" }
  ]
}
```

Produces one row per sheet whose name matches `sheet_pattern`. Used for RD Dias `interpret_*` sheets where each variant has its own interpretation sheet.

---

## Parse types

Applied within any field definition via `"parse": "<type>"`. The `db_column` acts as a placeholder and is not written to the database.

### `sample_id_split`

Splits `[InstrumentID]-[SpecimenID]-[BatchID]-[Testcode]-[Sex]-[ProbesetID]` into five columns. Sex (index 4) is discarded.

Output columns: `instrument_id`, `specimen_id`, `batch_id`, `test_code`, `probeset_id`

### `clinical_indication_split`

Splits `R208.1_Condition name_P` (or semicolon-separated multiples) into two columns.

Output columns: `preferred_condition_name`, `r_code`

---

## Merge strategy

```json
"merge_strategy": {
  "summary_x_included":      { "how": "cross" },
  "included_join_interpret": { "on": "hgvsc", "how": "left" }
}
```

- `summary_x_included` — always a cross join: every summary field is broadcast onto every variant row
- `included_join_interpret` — left join interpret rows onto included rows using the specified key column

---

## Constant fields

```json
"constant_fields": {
  "allele_origin":     "somatic",
  "collection_method": "clinical testing",
  "affected_status":   "yes"
}
```

These values are stamped onto every output row. Useful for fields that are the same for all workbooks of this format.

---

## Null sentinels

```json
"null_sentinels": [".", "./."]
```

Values that represent NULL in the source data (common in VCF-derived columns). Applied across **all** columns before inserting. Both `"."` (missing scalar) and `"./."` (missing genotype fraction) are replaced with `NaN`/`NULL`.

---

## Normalisations

```json
"normalisations": [
  { "field": "oncogenicity_classification", "replace": {
      "Likely_oncogenic":       "Likely oncogenic",
      "Uncertain_significance": "Uncertain significance",
      "Likely_benign":          "Likely benign"
  }}
]
```

String replacements applied **after** validation. Because validation runs on raw values, the validation `values` list must contain the raw (pre-normalisation) forms.

---

## Derived fields

```json
"derived_fields": [
  {
    "db_column": "comment_on_classification",
    "type": "acgs_comment",
    "criteria": ["pvs1", "ps1", "ps2", "pm1", "pm2", "pp1", "bs1", "bp1"],
    "matched_strength": {
      "PVS": "Very Strong", "PS": "Strong", "PM": "Moderate",
      "PP": "Supporting",   "BS": "Supporting", "BP": "Supporting"
    }
  }
]
```

Currently only `acgs_comment` is supported. This builds the `comment_on_classification` string by concatenating applied criteria (e.g. `"PVS1,PM2,BP4_Supporting"`). Criteria set to `"NA"` or null are excluded.

---

## Validations

Validation runs on the raw DataFrame. All errors are accumulated and returned as a list — the workbook is rejected if any errors are found.

### Structural

```json
"structural": [
  { "sheet": "summary", "cell": "G21", "equals": "Date",
    "error": "Extra rows or columns added to summary sheet" }
]
```

Guards against workbook layout changes that would silently shift cell references. The `sheet` value supports a trailing `*` wildcard to match all sheets of a pattern.

### Field

```json
"field": [
  { "field": "germline_classification", "type": "in_list",
    "values": ["Pathogenic", "Likely pathogenic", "Uncertain significance",
               "Likely benign", "Benign"] },
  { "field": "hgvsc",       "type": "not_null" },
  { "field": "interpreted", "type": "in_list", "values": ["yes", "no"] }
]
```

- `in_list` — value must be one of the listed strings (null values are ignored)
- `not_null` — value must not be null

### Cross-sheet

```json
"cross_sheet": [
  { "check": "interpret_hgvsc_in_included" },
  { "check": "interpreted_classification_consistency" }
]
```

Named checks implemented in `validator.py`:

| Check | What it validates |
|-------|------------------|
| `interpret_hgvsc_in_included` | Every HGVSc in interpret sheets also appears in the included sheet |
| `interpreted_classification_consistency` | `interpreted=yes` rows must have a classification; `interpreted=no` rows must not |

### ACGS

```json
"acgs": {
  "criteria": ["pvs1", "ps1", "ps2", "pm1", "pm2", "pp1", "ba1", "bs1", "bp1"],
  "strength_dropdown": ["Very Strong", "Strong", "Moderate", "Supporting", "NA"],
  "ba1_dropdown":      ["Stand-Alone", "Very Strong", "Strong", "Moderate", "Supporting", "NA"]
}
```

Checks that each criterion cell contains a value from the allowed strength dropdown. `ba1` uses a separate dropdown. Null criteria are ignored.

---

## Adding a new format: checklist

1. Copy `configs/template.json` to `configs/<format_name>_v1.json`
2. Fill in `format_name` and `format_version`
3. Define `fingerprint` rules that uniquely identify this format
4. Define `sheets` with the appropriate `extraction_type` per sheet
5. Map each workbook field to a `db_column` that exists in `testdirectory.inca`
6. Add `validations` for critical fields
7. Add `normalisations` if raw values need cleaning
8. Add `null_sentinels` if the source uses VCF-style null indicators
9. Drop a test workbook into `tests/test_data/workbooks/<format>/`
10. Run `augean --dry_run` to inspect the extracted DataFrame
11. Add a smoke test (or extend the existing parametrized one)
12. Run the full test suite to confirm no regressions
