# Test Suite Reference

164 unit/integration tests across 7 modules (163 passing, 1 skipped), plus acceptance tests requiring a live database. All tests use pytest with pytest-xdist (`-n auto` in `pyproject.toml`).

## Running tests

Install dependencies from the pinned lockfile before running:

```bash
pip install --upgrade pip
pip install -r requirements-dev.txt
pip install -e . --no-deps
```

```bash
# Unit and integration suite (parallel, ~30s)
pytest

# Acceptance tests — parser check only (no DB needed)
pytest tests/test_acceptance.py -m acceptance -k "parser" \
    --override-ini="addopts="

# Acceptance tests — full (workbook must be inserted into DB first)
pytest tests/test_acceptance.py -m acceptance \
    --db_credentials /path/to/creds.json \
    [--acceptance_schema testdirectory] \
    --override-ini="addopts="

# Verbose output for documentation
pytest tests/test_acceptance.py -m acceptance \
    --db_credentials /path/to/creds.json \
    --acceptance_schema testdirectory \
    -v -s --log-cli-level=INFO \
    --override-ini="addopts=" 2>&1 | tee results.txt
```

---

## `test_config.py` — 22 tests

| Class | Tests |
|-------|-------|
| `TestLoadConfigs` | Loads all three configs from dir; validates required keys present; raises `ConfigValidationError` on missing key; handles empty dir |
| `TestFingerprintEvaluation` | Each fingerprint rule type — `equals`, `matches_pattern`, `sheet_exists`, `sheet_pattern`, `has_columns` — pass and fail variants; all rules must match |
| `TestGetConfigForWorkbook` | Raises `WorkbookFormatUnknownError` on unknown format; raises `AmbiguousWorkbookFormatError` on ambiguous match |
| `TestRealWorkbookFingerprint` | **Anonymised workbooks**: RD Dias and HaemOnc v1 correctly auto-detected; v1 detects without `m_codes` sheet; v0 fingerprint (A8=`Sample ID`, F12=`Subpanel analysed`) detects correctly |

---

## `test_db.py` — 16 tests

| Class | Tests |
|-------|-------|
| `TestCreateEngine` | Passes `sslmode=require` by default; `sslmode` overridable via credentials dict |
| `TestAddWorkbook` | Executes insert with correct workbook name and format |
| `TestMarkWorkbookParsed` | Sets parse status to true |
| `TestMarkWorkbookFailed` | Sets parse status false with error string; handles empty error list |
| `TestAddVariants` | Returns row count; empty df returns zero; raises `SchemaMismatchError` on unknown columns; skips schema check when table absent |
| `TestMigrateSchema` | Executes `ALTER TABLE` for missing columns; no-op when schema matches; skips when table absent |
| `TestGetParsedWorkbooks` / `TestGetFailedWorkbooks` | Returns workbook names filtered by parse status |

---

## `test_loader.py` — 6 tests

| Class | Tests |
|-------|-------|
| `TestLoadWorkbook` | Opens valid xlsx; raises on missing file; raises on invalid file |
| `TestDetectFormat` | RD Dias detected; HaemOnc detected; unknown format raises |

---

## `test_parser.py` — 44 tests

**Where to start depending on your goal:**
- New to the codebase → `TestParseWorkbook` (integration tests against real workbooks) and the smoke tests
- Debugging an extraction problem → the `TestExtract*` class matching the extraction type in question
- Adding or modifying a config → `TestExtractTabular` + smoke tests
- Pindel-specific work → `TestParseWorkbookPindel` + `test_haemonc_smoke_pindel_sheet_present`

| Class | Tests |
|-------|-------|
| `TestSplitClinicalIndication` | Single indication; multiple semicolon-separated; `None` input; no underscore |
| `TestExtractNamedCells` | Simple fields; sentinel scan (found / not found); `clinical_indication_split`; date default today; `sample_id_split` |
| `TestExtractLabelScan` | Fields by label; missing label uses default; date default today; `sample_id_split` |
| `TestExtractNamedCellsMulti` | One row per matching sheet; no matching sheets returns empty |
| `TestExtractTabular` | RD Dias included sheet; lowercase transform; unique `local_id`; `linking_id` equals `local_id` |
| `TestExtractTabularConstantFields` | Sheet-level `constant_fields` stamped on rows; multiple keys; no regression when absent |
| `TestExtractTabularOptionalColumns` | Optional column absent → silently skipped, db_column absent from result; optional column present → extracted normally; required column absent → raises `ValueError`; `percent_to_decimal` transform strips `%` and divides by 100; `to_string` transform casts mixed int/str column to uniform string type |
| `TestMergeDataframes` | Cross join then left join; no interpret sheet skips join |
| `TestParseWorkbook` | **Anonymised workbooks**: RD Dias shape/columns/constant fields; HaemOnc shape/somatic `allele_origin`/`variant_category` |
| `TestParseWorkbookPindel` | Pindel rows concatenated with included; `variant_category` values per source; absent pindel sheet skipped gracefully; top-level constants broadcast to all rows |
| Smoke tests | Guard that test workbooks are present; pindel sheet precondition; parametrized smoke test for every HaemOnc `.xlsx` in `tests/test_data/workbooks/haemonc/` |

### `sample_id_split` tests

Both `TestExtractNamedCells` and `TestExtractLabelScan` include a dedicated test for the composite sample ID split:

- Input: `100033006-22363S0007-23NGSHO1-8128-M-96527893`
- Expected output columns: `instrument_id`, `specimen_id`, `batch_id`, `test_code`, `probeset_id`
- Sex (index 4) is ignored; `sample_id` does not appear in the output

---

## `test_transformer.py` — 32 tests

| Class | Tests |
|-------|-------|
| `TestApplyNullSentinels` | `.` → NaN; `./.` → NaN; empty sentinel list is no-op |
| `TestApplyNormalisations` | Replaces mapped values; missing field skipped; empty list no-op; two-pass chaining (e.g. `VUS` → `Uncertain_significance` → `Uncertain significance`) |
| `TestMakeAcgsCriteriaNull` | `"NA"` → NaN; nulls evidence when criterion null; preserves evidence when criterion set; missing columns no error |
| `TestBuildAcgsComment` | Default strength — no suffix; non-default strength — appended; null criterion excluded; multiple criteria comma-separated; empty df |
| `TestApplyDerivedFields` | ACGS comment dispatched; unknown type logged and skipped |
| `TestTransform` | Full pipeline: null sentinels → normalisations → coerce dates → ACGS null → derived fields |
| `TestCoerceDateLastEvaluated` | Slash separator (`/`) takes last date; same-month boundary; year-end boundary; hyphen separator (`-`) takes last date; plain string date parsed (DD/MM/YYYY); existing datetime unchanged; NaN unchanged; column absent is no-op; leading backtick stripped; leading apostrophe stripped; all-NaT column returns datetime dtype (not object) |

---

## `test_validator.py` — 20 tests

| Class | Tests |
|-------|-------|
| `TestValidateStructural` | Cell match passes; mismatch errors; pattern sheet checks all matching sheets; empty config |
| `TestValidateFields` | `in_list` pass/fail; nulls ignored by `in_list`; `not_null` pass/fail; missing field skipped |
| `TestValidateCrossSheet` | Interpreted + classification consistency: valid; `yes` with no classification; `no` with classification; multiple errors all captured |
| `TestValidateAcgs` | Valid strengths; invalid strength; BA1 separate dropdown; null criteria ignored; no acgs config |
| `TestValidateAll` | Accumulates errors from all four validation stages |

---

## `test_main.py` — 27 tests

UUID generation uses `uuid.uuid1().hex` directly with no sleep, so `test_main.py` tests run at full speed with no fixture patching needed.

### Dry run

| Test | What it covers |
|------|----------------|
| `test_main_dry_run_rd_dias` | Full pipeline on RD Dias workbooks, no DB write, no error CSVs |
| `test_main_dry_run_haemonc` | Full pipeline on HaemOnc workbook, no DB write, no error CSVs |
| `test_main_samples_file` | `--samples_file` path resolves and processes workbooks correctly |
| `test_main_format_override` | `--format rd_dias_v1` bypasses auto-detection |

### Deployment config

| Test | What it covers |
|------|----------------|
| `test_deployment_file_fills_missing_args` | `--deployment` JSON fills `config_dir` and `output_dir` |
| `test_cli_overrides_deployment` | CLI `--config_dir` takes precedence over deployment value |
| `test_defaults_applied` | `db_schema`, `db_table`, `db_workbooks_table` get correct defaults |
| `test_missing_config_dir_raises` | `SystemExit` when `config_dir` absent from both CLI and deployment |
| `test_missing_output_dir_raises` | `SystemExit` when `output_dir` absent from both CLI and deployment |

### Error handling

| Test | What it covers |
|------|----------------|
| `test_unreadable_workbook_logs_and_continues` | `OSError` on open → logs error, no CSV, continues to next workbook |
| `test_unknown_format_logs_and_continues` | `WorkbookFormatUnknownError` → logs error, no CSV |
| `test_format_override_unknown_name_logs_and_continues` | Unknown `--format` value → logs error, no CSV |
| `test_validation_errors_write_csv` | Validation errors → CSV written with error messages |
| `test_parse_error_writes_csv` | `parse_workbook` raises → CSV written |
| `test_transform_error_writes_csv` | `transformer.transform` raises → CSV written |

### DB write path (engine mocked)

| Test | What it covers |
|------|----------------|
| `test_successful_insert_marks_workbook_parsed` | Full insert path; `mark_workbook_parsed` called |
| `test_schema_mismatch_writes_csv` | `SchemaMismatchError` → CSV written, `mark_workbook_failed` called |
| `test_migrate_flag_calls_migrate_schema` | `--migrate` → `migrate_schema` called before insert |
| `test_validation_error_marks_workbook_failed` | Validation failure with live engine → `mark_workbook_failed` called |
| `test_already_parsed_workbooks_are_skipped` | Workbook in `already_parsed` set not passed to `add_workbook` |
| `test_duplicate_in_samples_file_raises` | Same path listed twice in `--samples_file` → `SystemExit` with duplicate basename message |
| `test_cross_directory_duplicate_basenames_raises` | Two different paths with same basename → `SystemExit` with duplicate basename message |
| `test_add_workbook_failure_writes_csv_and_continues` | `add_workbook()` raises → error CSV written, `add_variants` not called, returns `False` |
| `test_mark_workbook_parsed_failure_writes_csv` | `mark_workbook_parsed()` raises → error CSV written, returns `False` |

---

## `test_acceptance.py` — acceptance tests (excluded from default run)

Two orthogonal checks per workbook using a committed golden CSV snapshot as the shared reference:

| Test | DB needed | What it catches |
|---|---|---|
| `test_parser_matches_golden` | No | Parser/transformer regression — pipeline output changed unexpectedly |
| `test_db_matches_golden` | Yes | DB round-trip bug — insert/retrieve dropped rows, extra rows, or corrupted values |

The golden file is the key: it is independent of both the pipeline and the database, verified by human inspection when first created. When pipeline output is intentionally changed, run `python scripts/regenerate_golden.py`, inspect the diff, and commit it in the same PR.

Acceptance tests are parametrized automatically from the golden files in `tests/test_data/golden/`. Adding a new workbook to acceptance testing:

1. Ensure the workbook is in `tests/test_data/workbooks/haemonc/` (anonymised)
2. Run `python scripts/regenerate_golden.py` to create its golden file
3. Inspect the golden file, commit it
4. The acceptance tests pick it up automatically — no code changes needed

### Comparison approach

All column values are coerced to string before comparison to avoid dtype differences between the pipeline (where ID columns are `str`) and the CSV-loaded golden file (where pandas reads numeric-looking strings as `int64`). Datetime columns are normalised to `YYYY-MM-DD`. NaN/None values are normalised to empty string.

Columns excluded from comparison:
- `local_id`, `linking_id` — time-based UUIDs generated at parse time, different on every run
- DB-only columns not written by augean (`id`, `east_panels_id`, `submission_id`, etc.)

---

## Test data

Anonymised workbooks (no patient data) are committed to the repo and used by CI:

```text
tests/test_data/
  workbooks/
    rd_dias/
      148888811-45664R057-66NGWTY2-9116-M-111118.xlsx   ← committed (anonymised)
    haemonc/
      999999999-99999K9999-99NGSH999-9999-M-99999999.xlsx  ← committed (anonymised)
      <additional workbooks for smoke testing — gitignored>
  golden/
    999999999-99999K9999-99NGSH999-9999-M-99999999.csv   ← committed golden snapshot
```

Real patient workbooks placed in `workbooks/` are gitignored and will never be committed.

Tests that depend on workbook fixtures skip gracefully if the file is absent, so the suite remains runnable in any environment.

Drop additional HaemOnc workbooks into `tests/test_data/workbooks/haemonc/` and they are automatically picked up by the parametrized smoke test — no code changes needed. To also include them in acceptance testing, run `scripts/regenerate_golden.py` afterwards.

---

## CI workflow

Three jobs run on every push and PR to `main` (`.github/workflows/pytest.yml`):

| Job | Trigger | What it does |
|---|---|---|
| `test` | push / PR | Installs from `requirements-dev.txt`, runs full pytest suite with coverage |
| `security` | push / PR | Runs `bandit -r augean/ -ll` (SAST) and `pip-audit` (CVE scan); both gate on zero findings |
| `release-artefacts` | push to `main` only | Generates `requirements-hashed.txt` and `sbom.json` (CycloneDX SBOM); uploads as workflow artefact `release-artefacts-<sha>` with 90-day retention |

All three jobs install from the committed lockfiles (`requirements-dev.txt`) rather than resolving from version ranges, ensuring reproducible builds.

For CRMF filing: download the `release-artefacts-<sha>` artefact from the GitHub Actions run corresponding to each release commit and file alongside the CSCR in `CRMF/evidence/release_configs/`.
