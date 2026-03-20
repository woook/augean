# Augean

Config-driven Excel workbook staging extractor for ClinVar submissions.

## What does this app do?

Augean reads NHS genomics laboratory interpretation workbooks (`.xlsx`), validates their structure and content against a format-specific config, normalises the extracted data, and loads variant records into a PostgreSQL staging database ready for ClinVar submission. It generalises the extraction layer originally developed in the Pandora tool so that new workbook formats can be supported by writing a JSON config rather than modifying code.

## Typical use cases

- **Rare Disease (RD Dias) germline variant submissions** — batch-process interpretation workbooks from CUH or NUH laboratories, each containing a `summary` sheet, an `included` variants table, and one or more `interpret_*` ACGS-classification sheets.
- **HaemOnc (Uranus) somatic variant submissions** — process haematology oncology workbooks whose summary data is stored as labelled key-value pairs and whose variant table uses an `included` sheet with a somatic classification column.
- **Dry-run validation** — parse and validate workbooks without writing anything to the database; useful for quality-checking new workbook versions before production runs.
- **Adding a new workbook format** — write a JSON config describing the fingerprint, sheet layouts, field mappings, validations, and normalisations; no code changes required.

## Inputs

### Required

| Input | Flag | Format / Notes |
|---|---|---|
| Excel workbook(s) | `--workbooks_path DIR` or `--samples_file FILE` | `.xlsx` files. Use `--workbooks_path` to process every `.xlsx` in a directory, or `--samples_file` to provide a plain-text file with one absolute workbook path per line. |
| Config directory | `--config_dir DIR` | Directory containing one or more format config files (see [Config files](#config-files) below). The bundled `configs/` directory contains the two built-in formats. |
| Database credentials | `--db_credentials FILE` | JSON file with keys `user`, `password`, `host`, `database`, and optionally `port` (default 5432). Not required when `--dry_run` is set. |
| Output directory | `--output_dir DIR` | Directory where per-workbook error CSVs are written. Created automatically if it does not exist. |

### Optional

| Flag | Description |
|---|---|
| `--organisation {CUH,NUH}` | Label appended to log output to identify the source organisation. |
| `--dry_run` | Parse and validate only; no database writes. |
| `--format FORMAT_NAME` | Skip auto-detection and force a specific format (e.g. `rd_dias_v1`). |
| `--db_table TABLE` | Target table name (default: `inca`). |
| `--db_schema SCHEMA` | Target schema name (default: `testdirectory`). |
| `--log_level {DEBUG,INFO,WARNING,ERROR}` | Logging verbosity (default: `INFO`). |

### Config files

Each format config is a JSON file in the config directory. Two built-in configs are provided:

| Config file | Format name | Workbook type |
|---|---|---|
| `configs/rd_dias_v1.json` | `rd_dias_v1` | RD Dias germline interpretation workbooks (CUH / NUH) |
| `configs/haemonc_uranus_v1.json` | `haemonc_uranus_v1` | HaemOnc Uranus somatic variant workbooks |

Augean auto-detects the format by matching each workbook against the `fingerprint` rules in every config. Custom configs can be dropped into any directory passed via `--config_dir`.

### Workbook format requirements

**rd_dias_v1**
- Sheet `summary`: cell B1 must contain a sample ID matching the pattern `^\d{9}-` (9 digits followed by a dash); cell F1 must contain a clinical indication in `<preferred_condition_name> (<R-code>)` format.
- Sheet `included`: must have columns `CHROM`, `POS`, `REF`, `ALT`, `SYMBOL`, `HGVSc`, `Consequence`, `Interpreted`, `Comment`.
- One or more sheets whose names match the pattern `^interpret`: each must contain the ACMG/ACGS classification criteria in the expected cell layout.

**haemonc_uranus_v1**
- Sheet `summary`: cell A5 must equal `Subpanel analysed`; cell A6 must equal `M-code`; sample metadata is stored as label (column A) / value (column B) pairs.
- Sheet `included`: must have columns `CHROM`, `POS`, `SYMBOL`, `HGVSc`, `Consequence`, `AF`, `Classification`, `Latest Classification Date`, `Comment`, `Interpreted`.
- Sheet `m_codes` must exist.

## Outputs

### Database (live run)

Two tables in the target PostgreSQL database are written:

| Table | Content |
|---|---|
| `testdirectory.staging_workbooks` | One row per workbook: filename, processing date, detected format, and parse status (`TRUE` = success, `FALSE` = failed with error message). |
| `<schema>.<table>` (default `testdirectory.inca`) | One row per variant per sample, containing all extracted, validated, and normalised fields (chromosome, position, alleles, gene symbol, HGVSc, classification, ACGS criteria, clinical indication, sample metadata, etc.). |

### Error CSVs (written on failure)

When a workbook fails validation or parsing, a CSV is written to `--output_dir`:

```text
<output_dir>/<workbook_filename>_errors.csv
```

Columns: `workbook`, `error`. One row per error message.

## Installation

```bash
pip install -e .
```

## Usage example

```bash
augean \
  --db_credentials /path/to/creds.json \
  --config_dir configs/ \
  --workbooks_path /path/to/workbooks/ \
  --output_dir /path/to/errors/ \
  --organisation CUH
```

Dry run (no database writes):

```bash
augean \
  --config_dir configs/ \
  --workbooks_path /path/to/workbooks/ \
  --output_dir /path/to/errors/ \
  --dry_run
```

## Testing

Run the full test suite:

```bash
pytest
```

### Test structure

| Module | What it covers |
|---|---|
| `test_config.py` | Config loading, fingerprint matching, format auto-detection |
| `test_loader.py` | Workbook opening, format identification |
| `test_parser.py` | All extraction types (`named_cells`, `label_scan`, `tabular`, `named_cells_multi`, `sentinel_scan`), merge logic, `parse_workbook` integration |
| `test_validator.py` | Structural, field, cross-sheet and ACGS validators |
| `test_transformer.py` | Normalisations, ACGS criteria nulling, comment building |
| `test_db.py` | SQLAlchemy staging insert/upsert operations |
| `test_main.py` | CLI entry point |

Most parser and validator tests use mock workbooks built in-memory. Integration tests in `test_parser.py` and `test_validator.py` run against real workbooks in `tests/test_data/workbooks/`.

### HaemOnc smoke tests

`test_parser.py` contains a parametrized smoke test that runs against every `.xlsx` file in `tests/test_data/workbooks/haemonc/`. It asserts that each workbook parses without error and produces a non-empty DataFrame with the expected columns.

To add a new workbook to smoke testing:

1. Copy the file into `tests/test_data/workbooks/haemonc/`
2. Inspect the output using dry-run:
   ```bash
   python -m augean.main --dry_run path/to/workbook.xlsx
   ```
3. Run the smoke tests to confirm it passes:
   ```bash
   pytest tests/test_parser.py::test_haemonc_workbook_smoke -v
   ```

No test code changes are needed — the parametrized test picks up any new `.xlsx` in that directory automatically.
