# Test Suite Reference

140 tests across 7 modules (139 passing, 1 skipped when only one RD Dias workbook is present). All tests use pytest.

## Running tests

```bash
# Full suite (sequential)
pytest

# Parallel by file group (~34s wall clock)
pytest tests/test_config.py tests/test_db.py tests/test_loader.py \
       tests/test_transformer.py tests/test_validator.py &
pytest tests/test_parser.py &
pytest tests/test_main.py &
wait
```

---

## `test_config.py` — 20 tests

| Class | Tests |
|-------|-------|
| `TestLoadConfigs` | Loads both configs from dir; validates required keys present; raises `ConfigValidationError` on missing key; handles empty dir |
| `TestFingerprintEvaluation` | Each fingerprint rule type — `equals`, `matches_pattern`, `sheet_exists`, `sheet_pattern`, `has_columns` — pass and fail variants; all rules must match |
| `TestGetConfigForWorkbook` | Raises `WorkbookFormatUnknownError` on unknown format; raises `AmbiguousWorkbookFormatError` on ambiguous match |
| `TestRealWorkbookFingerprint` | **Anonymised workbooks**: RD Dias and HaemOnc correctly auto-detected |

---

## `test_db.py` — 14 tests

| Class | Tests |
|-------|-------|
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

## `test_parser.py` — 39 tests

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
| `TestMergeDataframes` | Cross join then left join; no interpret sheet skips join |
| `TestParseWorkbook` | **Anonymised workbooks**: RD Dias shape/columns/constant fields; HaemOnc shape/somatic allele_origin/variant_category |
| `TestParseWorkbookPindel` | Pindel rows concatenated with included; `variant_category` values per source; absent pindel sheet skipped gracefully; top-level constants broadcast to all rows |
| Smoke tests | Guard that test workbooks are present; pindel sheet precondition; parametrized smoke test for every HaemOnc `.xlsx` in `tests/test_data/workbooks/haemonc/` |

### `sample_id_split` tests

Both `TestExtractNamedCells` and `TestExtractLabelScan` include a dedicated test for the composite sample ID split:

- Input: `100033006-22363S0007-23NGSHO1-8128-M-96527893`
- Expected output columns: `instrument_id`, `specimen_id`, `batch_id`, `test_code`, `probeset_id`
- Sex (index 4) is ignored; `sample_id` does not appear in the output

---

## `test_transformer.py` — 19 tests

| Class | Tests |
|-------|-------|
| `TestApplyNullSentinels` | `.` → NaN; `./.` → NaN; empty sentinel list is no-op |
| `TestApplyNormalisations` | Replaces mapped values; missing field skipped; empty list no-op |
| `TestMakeAcgsCriteriaNull` | `"NA"` → NaN; nulls evidence when criterion null; preserves evidence when criterion set; missing columns no error |
| `TestBuildAcgsComment` | Default strength — no suffix; non-default strength — appended; null criterion excluded; multiple criteria comma-separated; empty df |
| `TestApplyDerivedFields` | ACGS comment dispatched; unknown type logged and skipped |
| `TestTransform` | Full pipeline: null sentinels → normalisations → ACGS null → derived fields |

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

## `test_main.py` — 22 tests

An autouse fixture `mock_parser_sleep` patches `augean.parser.time.sleep` to a no-op in all tests, eliminating UUID generation delays (~0.5s per variant row).

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

---

## Test data

Anonymised workbooks (no patient data) are committed to the repo and used by CI:

```
tests/test_data/workbooks/
  rd_dias/
    148888811-45664R057-66NGWTY2-9116-M-111118.xlsx   ← committed (anonymised)
  haemonc/
    999999999-99999K9999-99NGSH999-9999-M-99999999.xlsx  ← committed (anonymised)
    <additional workbooks for smoke testing — gitignored>
```

Real patient workbooks placed in these directories are gitignored by pattern and will never be committed. The gitignore explicitly allowlists only the two anonymised filenames above.

Tests that depend on workbook fixtures skip gracefully if the file is absent, so the suite remains runnable in any environment.

Drop additional HaemOnc workbooks into `tests/test_data/workbooks/haemonc/` and they are automatically picked up by the parametrized smoke test — no code changes needed.
