# Architecture Overview

This document is intended for developers who are new to the codebase. It explains what Augean does, how the code is structured, and the key design decisions that shape it.

---

## What the system does

Augean reads NHS genomics laboratory Excel workbooks (`.xlsx`), extracts variant classification data from them, validates and normalises that data, and loads it into a PostgreSQL staging database for ClinVar submission.

The key design goal is that **adding a new workbook format requires only a JSON config file — no code changes**. The extraction logic, validation rules, field mappings, and normalisations are all driven by configuration.

---

## The pipeline

Every workbook passes through six stages in sequence:

```text
Excel file
    │
    ▼
1. Load          loader.load_workbook()
    │               Opens the .xlsx with openpyxl
    │
    ▼
2. Detect        loader.detect_format()
    │               Matches workbook against fingerprint rules in each config.
    │               Raises if no match or ambiguous match.
    │
    ▼
3. Parse         parser.parse_workbook()
    │               Extracts data from each sheet into a single merged DataFrame.
    │               Uses the extraction_type defined per sheet in the config.
    │
    ▼
4. Validate      validator.validate_all()
    │               Runs on the RAW DataFrame (before any normalisation).
    │               Returns a list of error strings. Non-empty → workbook fails.
    │
    ▼
5. Transform     transformer.transform()
    │               Applies null sentinels, string normalisations, date coercion,
    │               ACGS criteria nulling, and derived field generation.
    │
    ▼
6. Insert        db.add_variants()
                    Inserts the final DataFrame into PostgreSQL.
                    Checks for schema mismatches before inserting.
```

The orchestration lives in `augean/main.py` → `_process_workbook()`.

---

## Module responsibilities

| Module | Responsibility |
|--------|---------------|
| `augean/config.py` | Load and validate JSON configs; evaluate fingerprint rules against a workbook |
| `augean/loader.py` | Open `.xlsx` files with openpyxl; call `config.get_config_for_workbook()` |
| `augean/parser.py` | Extract sheets into DataFrames; merge summary + included + interpret |
| `augean/validator.py` | Structural, field, cross-sheet, and ACGS validation checks |
| `augean/transformer.py` | Null sentinel replacement, normalisations, date coercion, ACGS comment building |
| `augean/db.py` | SQLAlchemy operations: workbook tracking, variant insert, schema migrate |
| `augean/main.py` | CLI argument parsing, pipeline orchestration, error CSV output |
| `augean/errors.py` | Custom exception types |

---

## Config system

Each supported workbook format has a JSON config file in `configs/`. The config is the single source of truth for:

- **Fingerprinting** — how to identify this format (cell values, sheet names, column headers)
- **Extraction** — which sheets to read, which cells/columns map to which database fields
- **Validation** — rules to check before inserting (allowed values, required fields, structural checks)
- **Normalisation** — string replacements applied after validation
- **Null sentinels** — values that represent NULL in the source data (e.g. `.` or `./.`)
- **Constants** — fields stamped onto every output row (e.g. `allele_origin`)

See [`docs/config-guide.md`](config-guide.md) for a full reference.

---

## Extraction types

Each sheet in a config declares an `extraction_type` that controls how data is read:

| Type | Use case | Example |
|------|----------|---------|
| `named_cells` | Fields at fixed cell addresses (e.g. `B1`, `F1`) | RD Dias summary |
| `label_scan` | Label/value pairs — scan column A for label text, read column B | HaemOnc summary |
| `tabular` | Columnar variant table read with `pd.read_excel` | Both `included` sheets |
| `named_cells_multi` | One row per sheet matching a name pattern | RD Dias `interpret_*` sheets |

### Special parse types

Some fields require post-extraction splitting:

- **`sample_id_split`** — the composite sample ID `[InstrumentID]-[SpecimenID]-[BatchID]-[Testcode]-[Sex]-[ProbesetID]` is split into five separate database columns. Sex (index 4) is discarded.
- **`clinical_indication_split`** — `R208.1_Condition name_P` is split into `preferred_condition_name` and `r_code`.

---

## Merge strategy

After extracting sheets individually, the DataFrames are merged into a single per-variant row:

1. **Cross join** — summary (one row) is joined onto every row of included (many rows), broadcasting the summary fields across all variants.
2. **Left join** — interpret rows (RD Dias only) are joined onto the included rows on `hgvsc`, attaching ACGS criteria to the matching variant.

---

## Validation design

Validation intentionally runs on the **raw** DataFrame, before normalisation. This means:

- Config `valid_values` must match the **raw workbook values** (e.g. `"Likely_oncogenic"` not `"Likely oncogenic"`).
- If a normalisation changes a value, the corresponding raw value must be in the validation list.

There are four validation stages, all accumulated into a single error list:

| Stage | What it checks |
|-------|----------------|
| Structural | Specific cells contain expected values (guards against sheet layout changes) |
| Field | Column values are in an allowed list or non-null |
| Cross-sheet | Consistency between columns (e.g. `interpreted=yes` must have a classification) |
| ACGS | Strength dropdown values are within the allowed set |

---

## Data quality handling in the transformer

Before ACGS processing, `transformer.transform()` calls `coerce_date_last_evaluated()` to normalise the `date_last_evaluated` column. This handles several common manual-editing errors found in older workbooks where sheet locking was not enforced:

- **Multiple dates separated by ` / ` or ` - `** — takes the last (most recent) date and logs a `WARNING`
- **Leading backtick or apostrophe** — Excel text-prefix artefact surfaced by openpyxl; stripped before parsing
- **Plain string dates** (e.g. `13/01/2026`) — parsed to datetime using `dayfirst=True`
- **All-NaT columns** — always returns `datetime64` dtype, not `object`, to prevent silent type mismatch on insert

---

## Skip-already-parsed and batch validation

`augean/main.py` performs two safeguards before the processing loop:

1. **Duplicate basename check** — if any two workbooks in the batch share the same filename (even from different directories), a `SystemExit` is raised immediately. The database keys on `workbook_name` (basename), so duplicate filenames are always ambiguous.

2. **Skip-already-parsed** — `db.get_parsed_workbooks()` is called once at startup to fetch all workbook names where `parse_status = TRUE`. Any matching workbook is skipped with a log message. Workbooks processed successfully during the run are added to the skip-set immediately, preventing within-run duplicates when the same path appears twice in `--samples_file`.

Workbooks where `parse_status = FALSE` (previous failure) are **not** skipped and are always retried.

---

## Database interaction

Two tables are written per run:

- **`<schema>.<workbooks_table>`** (default `testdirectory.inca_workbooks`) — one row per workbook recording filename, format, date, and parse status (`TRUE`/`FALSE` + error message). `add_workbook` uses `ON CONFLICT (workbook_name) DO NOTHING`, so re-running a previously-failed workbook updates the existing row via `mark_workbook_parsed` or `mark_workbook_failed` rather than inserting a duplicate. Both calls are wrapped in try/except so a DB tracking failure does not abort the batch.
- **`<schema>.<table>`** (default `testdirectory.inca`) — one row per variant, containing all extracted fields.

Before inserting, `db.add_variants()` compares the DataFrame columns against the live table columns. If any DataFrame column is absent from the table, a `SchemaMismatchError` is raised with the `ALTER TABLE` SQL needed to resolve it. The `--migrate` flag applies these automatically.

---

## Format differences: RD Dias, HaemOnc v1, and HaemOnc v0

| Aspect | RD Dias (`rd_dias_v1`) | HaemOnc v1 (`haemonc_uranus_v1`) | HaemOnc v0 (`haemonc_uranus_v0`) |
|--------|----------------------|----------------------------------|----------------------------------|
| Generator version | N/A | eggd_generate_variant_workbook v2.11.0+ | before v2.11.0 (pre-May 2025) |
| Allele origin | germline | somatic | somatic |
| Summary extraction | `named_cells` (fixed addresses) | `label_scan` (labels in col A, values in col B) | `named_cells` (labels split between col A row 8 and col F rows 10–12) |
| Classification type | `germline_classification` | `oncogenicity_classification` | `oncogenicity_classification` |
| ACGS criteria | Yes (interpret sheets) | No | No |
| M-code | No | Optional (present if `--m_codes` passed to generator) | No |
| Excluded sheet | No | No | Yes (ignored — filtered-out variants) |
| AF format | N/A | Decimal (e.g. `0.078`) | Percentage string (e.g. `7.8%`) — converted by `percent_to_decimal` transform |
| Optional columns | No | No | Yes — columns absent in older pipeline versions are marked `optional: true` |
| Ref genome | `sentinel_scan` in summary | Label scan, no default | `sentinel_scan` in summary |
| Clinical indication | Split into condition name + R-code | Not applicable | Not applicable |
| Null sentinels | None | `.` and `./.` (VCF-style) | `.` and `./.` (VCF-style) |

---

## Key files to read first

If you are new to the codebase, read these files in this order:

1. `configs/haemonc_uranus_v1.json` — understand the current HaemOnc config structure concretely
2. `configs/haemonc_uranus_v0.json` — see how optional columns, percent_to_decimal, and named_cells summary extraction differ
3. `augean/parser.py` — the extraction logic
3. `augean/main.py` — the pipeline orchestration
4. `augean/validator.py` — validation checks
5. `augean/transformer.py` — post-parse transformations
6. `augean/db.py` — database operations

The test files are also a useful reference — each module has a corresponding test file that shows inputs and expected outputs for each function.
