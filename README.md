# Augean

Config-driven extractor for variant classification Excel workbooks.

## What does this app do?

Augean reads NHS genomics laboratory interpretation workbooks (`.xlsx`), validates their structure and content against a format-specific config, normalises the extracted data, and loads variant records into a PostgreSQL staging database ready for ClinVar submission. It generalises the extraction layer originally developed in the Pandora tool so that new workbook formats can be supported by writing a JSON config rather than modifying code.

## Developer documentation

| Document | Description |
|----------|-------------|
| [`docs/architecture.md`](docs/architecture.md) | System overview, pipeline, module responsibilities, key design decisions |
| [`docs/config-guide.md`](docs/config-guide.md) | How to write and extend format configs |
| [`docs/testing.md`](docs/testing.md) | Full test suite reference |

---

> **Note:** RD Dias workbook parsing is currently non-functional. The `rd_dias_v1` config and its supporting code are present in the repository but have not been validated against the live database schema. Do not use RD Dias processing in production until this has been reviewed and tested end-to-end.

## Typical use cases

- **Rare Disease (RD Dias) germline variant submissions** — batch-process interpretation workbooks from CUH or NUH laboratories, each containing a `summary` sheet, an `included` variants table, and one or more `interpret_*` ACGS-classification sheets. *(Currently non-functional — see note above.)*
- **HaemOnc (Uranus) somatic variant submissions** — process haematology oncology workbooks whose summary data is stored as labelled key-value pairs and whose variant table uses an `included` sheet with a somatic classification column.
- **Dry-run validation** — parse and validate workbooks without writing anything to the database; useful for quality-checking new workbook versions before production runs.
- **Adding a new workbook format** — write a JSON config describing the fingerprint, sheet layouts, field mappings, validations, and normalisations; no code changes required.

## Inputs

### Required

| Input | Flag | Format / Notes |
|---|---|---|
| Excel workbook(s) | `--workbooks_path DIR` or `--samples_file FILE` | `.xlsx` files. Use `--workbooks_path` to process every `.xlsx` in a directory, or `--samples_file` to provide a plain-text file with one absolute workbook path per line. |
| Database credentials | `--db_credentials FILE` | JSON file with keys `user`, `password`, `host`, `database`, and optionally `port` (default 5432). Always required by the CLI, but the file is not opened when `--dry_run` is set. |

### Deployment config (recommended)

Deployment-specific settings that rarely change between runs can be placed in a JSON file and passed via `--deployment`. This avoids repeating flags on every invocation. A template is provided at `deployment.template.json`.

```json
{
  "config_dir": "configs/",
  "output_dir": "/path/to/error-output/",
  "db_schema": "testdirectory",
  "db_table": "inca",
  "db_workbooks_table": "staging_workbooks",
  "organisation": "CUH"
}
```

`config_dir` and `output_dir` are required — either in the deployment config or as CLI flags. All other deployment values fall back to the defaults shown above if not specified.

CLI flags always override values in the deployment config.

### Optional flags

| Flag | Description |
|---|---|
| `--deployment FILE` | Path to deployment config JSON. |
| `--config_dir DIR` | Path to configs/ directory. Overrides deployment config. |
| `--output_dir DIR` | Directory for error CSVs. Overrides deployment config. |
| `--organisation {CUH,NUH}` | Organisation label. Overrides deployment config. |
| `--dry_run` | Parse and validate only; no database writes. |
| `--migrate` | Add missing columns to the target table before inserting (see [Schema migration](#schema-migration)). |
| `--format FORMAT_NAME` | Skip auto-detection and force a specific format (e.g. `rd_dias_v1`). |
| `--db_table TABLE` | Target variant table name. Overrides deployment config. |
| `--db_schema SCHEMA` | Target schema. Overrides deployment config. |
| `--db_workbooks_table TABLE` | Workbook tracking table name. Overrides deployment config. |
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

With a deployment config:

```bash
augean \
  --deployment /path/to/deployment.json \
  --db_credentials /path/to/creds.json \
  --workbooks_path /path/to/workbooks/
```

Dry run (no database writes):

```bash
augean \
  --deployment /path/to/deployment.json \
  --db_credentials /path/to/creds.json \
  --workbooks_path /path/to/workbooks/ \
  --dry_run
```

## Schema migration

Before inserting, Augean compares the DataFrame columns against the columns present in the target PostgreSQL table. If any columns are missing, the workbook is marked as failed and an error is written to the error CSV containing the `ALTER TABLE` statements needed to resolve the mismatch:

```
Schema mismatch: The following columns are not present in testdirectory.inca
and must be added before inserting: ['prev_classification_date']

Run the following SQL to resolve:

    ALTER TABLE testdirectory.inca ADD COLUMN prev_classification_date TEXT;

Or re-run with --migrate to apply automatically.
```

This behaviour ensures that new config fields cannot silently go unrecorded — a schema change requires explicit action.

### Automatic migration with `--migrate`

To apply the schema changes and insert in a single step, pass `--migrate`:

```bash
augean \
  --db_credentials /path/to/creds.json \
  --config_dir configs/ \
  --workbooks_path /path/to/workbooks/ \
  --output_dir /path/to/errors/ \
  --migrate
```

Each column added is logged at `WARNING` level so the change is always visible. Column types are inferred from the DataFrame dtype (`TEXT`, `NUMERIC`, `INTEGER`, or `DATE`); adjust the column type manually afterwards if a different type is required.

## Testing

Run the full test suite:

```bash
pytest
```

130 tests across 7 modules. For a detailed breakdown see [`docs/testing.md`](docs/testing.md).

### Test structure

| Module | Tests | What it covers |
|---|---|---|
| `test_config.py` | 20 | Config loading, fingerprint rule types, format auto-detection against real workbooks |
| `test_db.py` | 14 | SQLAlchemy insert/status/migrate operations |
| `test_loader.py` | 6 | Workbook opening, format identification |
| `test_parser.py` | 29 | All extraction types, split parse types, merge logic, real-workbook integration |
| `test_transformer.py` | 19 | Null sentinels, normalisations, ACGS criteria nulling, comment building |
| `test_validator.py` | 15 | Structural, field, cross-sheet, and ACGS validators |
| `test_main.py` | 22 | CLI pipeline: dry run, deployment config, all error paths, DB write path |

Most tests use mock workbooks built in-memory. Integration tests in `test_parser.py` and `test_main.py` run against real workbooks in `tests/test_data/workbooks/` (gitignored).

### Running in parallel

The test suite can be parallelised by file group for faster feedback:

```bash
pytest tests/test_config.py tests/test_db.py tests/test_loader.py \
       tests/test_transformer.py tests/test_validator.py &
pytest tests/test_parser.py &
pytest tests/test_main.py &
wait
```

Wall clock time: ~34s (vs ~215s sequential).

### HaemOnc smoke tests

`test_parser.py` contains a parametrized smoke test that runs against every `.xlsx` in `tests/test_data/workbooks/haemonc/`. It asserts each workbook parses without error and produces a non-empty DataFrame.

To add a new workbook to smoke testing:

1. Copy the file into `tests/test_data/workbooks/haemonc/`
2. Inspect the output using dry-run:
   ```bash
   augean \
     --deployment /path/to/deployment.json \
     --db_credentials /path/to/creds.json \
     --workbooks_path tests/test_data/workbooks/haemonc/ \
     --dry_run
   ```
3. Run the smoke tests to confirm it passes:
   ```bash
   pytest tests/test_parser.py::test_haemonc_workbook_smoke -v
   ```

No test code changes are needed — the parametrized test picks up any new `.xlsx` automatically.
