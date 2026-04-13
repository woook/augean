"""Tests for the CLI entry point (augean/main.py)."""
import argparse
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

from augean.main import _apply_deployment_config, _write_error_csv, main, parse_args



CONFIGS_DIR = Path(__file__).parent.parent / "configs"
WORKBOOKS_DIR = Path(__file__).parent / "test_data" / "workbooks"


def test_package_importable():
    import augean
    assert augean is not None


def test_cli_help(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["augean", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        with redirect_stdout(io.StringIO()) as out:
            main()
    assert exc_info.value.code == 0
    assert "augean" in out.getvalue().lower() or "usage" in out.getvalue().lower()


def test_write_error_csv(tmp_path):
    _write_error_csv(tmp_path, "wb.xlsx", ["err one", "err two"])
    out = tmp_path / "wb.xlsx_errors.csv"
    assert out.exists()
    text = out.read_text()
    assert "err one" in text
    assert "err two" in text


def test_main_dry_run_rd_dias(tmp_path, monkeypatch):
    """End-to-end: parse + validate + transform RD Dias workbooks without DB."""
    if not list((WORKBOOKS_DIR / "rd_dias").glob("*.xlsx")):
        pytest.skip("No RD Dias test workbook available")
    monkeypatch.setattr(
        sys, "argv",
        [
            "augean",
            "--db_credentials", str(tmp_path / "unused.json"),
            "--config_dir", str(CONFIGS_DIR),
            "--workbooks_path", str(WORKBOOKS_DIR / "rd_dias"),
            "--output_dir", str(tmp_path),
            "--dry_run",
        ],
    )
    main()
    assert list(tmp_path.glob("*_errors.csv")) == []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _argv(tmp_path, *, workbooks_dir=None, samples_file=None, dry_run=True,
          db_creds=None, extra=None):
    argv = [
        "augean",
        "--db_credentials", str(db_creds or tmp_path / "unused.json"),
        "--config_dir", str(CONFIGS_DIR),
        "--output_dir", str(tmp_path),
    ]
    if workbooks_dir:
        argv += ["--workbooks_path", str(workbooks_dir)]
    if samples_file:
        argv += ["--samples_file", str(samples_file)]
    if dry_run:
        argv.append("--dry_run")
    if extra:
        argv.extend(extra)
    return argv


def _write_creds(tmp_path):
    p = tmp_path / "creds.json"
    p.write_text('{"host":"localhost","port":5432,"database":"db","user":"u","password":"p"}')
    return p


# ---------------------------------------------------------------------------
# Additional dry-run scenarios
# ---------------------------------------------------------------------------

def test_main_dry_run_haemonc(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, workbooks_dir=WORKBOOKS_DIR / "haemonc"))
    main()
    assert list(tmp_path.glob("*_errors.csv")) == []


def test_main_samples_file(tmp_path, monkeypatch):
    """--samples_file path resolves workbooks correctly."""
    haemonc_dir = WORKBOOKS_DIR / "haemonc"
    samples = tmp_path / "samples.txt"
    samples.write_text("\n".join(str(p) for p in sorted(haemonc_dir.glob("*.xlsx"))))
    monkeypatch.setattr(sys, "argv", _argv(tmp_path, samples_file=samples))
    main()
    assert list(tmp_path.glob("*_errors.csv")) == []


def test_main_format_override(tmp_path, monkeypatch):
    """--format bypasses auto-detection and uses the named config."""
    monkeypatch.setattr(sys, "argv", _argv(
        tmp_path,
        workbooks_dir=WORKBOOKS_DIR / "haemonc",
        extra=["--format", "haemonc_uranus_v1"],
    ))
    main()
    assert list(tmp_path.glob("*_errors.csv")) == []


# ---------------------------------------------------------------------------
# Deployment config
# ---------------------------------------------------------------------------

class TestDeploymentConfig:
    def test_deployment_file_fills_missing_args(self, tmp_path, monkeypatch):
        dep_file = tmp_path / "deployment.json"
        dep_file.write_text(json.dumps({
            "config_dir": str(CONFIGS_DIR),
            "output_dir": str(tmp_path),
        }))
        monkeypatch.setattr(sys, "argv", [
            "augean",
            "--db_credentials", str(tmp_path / "unused.json"),
            "--deployment", str(dep_file),
            "--workbooks_path", str(WORKBOOKS_DIR / "haemonc"),
            "--dry_run",
        ])
        main()
        assert list(tmp_path.glob("*_errors.csv")) == []

    def test_cli_overrides_deployment(self, tmp_path, monkeypatch):
        """CLI --config_dir takes precedence over deployment config value."""
        dep_file = tmp_path / "deployment.json"
        dep_file.write_text(json.dumps({
            "config_dir": "/nonexistent/path",
            "output_dir": str(tmp_path),
        }))
        monkeypatch.setattr(sys, "argv", [
            "augean",
            "--db_credentials", str(tmp_path / "unused.json"),
            "--deployment", str(dep_file),
            "--config_dir", str(CONFIGS_DIR),
            "--workbooks_path", str(WORKBOOKS_DIR / "haemonc"),
            "--dry_run",
        ])
        main()

    def test_defaults_applied(self, tmp_path):
        """db_schema, db_table, db_workbooks_table receive sensible defaults."""
        args = argparse.Namespace(
            deployment=None, config_dir=str(CONFIGS_DIR), output_dir=str(tmp_path),
            db_schema=None, db_table=None, db_workbooks_table=None, organisation=None,
        )
        _apply_deployment_config(args)
        assert args.db_schema == "testdirectory"
        assert args.db_table == "inca"
        assert args.db_workbooks_table == "staging_workbooks"

    def test_missing_config_dir_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", [
            "augean",
            "--db_credentials", str(tmp_path / "unused.json"),
            "--workbooks_path", str(WORKBOOKS_DIR / "haemonc"),
            "--output_dir", str(tmp_path),
            "--dry_run",
        ])
        with pytest.raises(SystemExit):
            main()

    def test_missing_output_dir_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", [
            "augean",
            "--db_credentials", str(tmp_path / "unused.json"),
            "--config_dir", str(CONFIGS_DIR),
            "--workbooks_path", str(WORKBOOKS_DIR / "haemonc"),
            "--dry_run",
        ])
        with pytest.raises(SystemExit):
            main()


# ---------------------------------------------------------------------------
# Error handling paths
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_unreadable_workbook_logs_and_continues(self, tmp_path, monkeypatch):
        """OSError on open → no CSV written, rest of batch continues."""
        samples = tmp_path / "samples.txt"
        samples.write_text("/nonexistent/bad.xlsx")
        monkeypatch.setattr(sys, "argv", _argv(tmp_path, samples_file=samples))
        main()
        assert list(tmp_path.glob("*_errors.csv")) == []

    def test_unknown_format_logs_and_continues(self, tmp_path, monkeypatch):
        from augean.errors import WorkbookFormatUnknownError
        monkeypatch.setattr(sys, "argv", _argv(tmp_path, workbooks_dir=WORKBOOKS_DIR / "haemonc"))
        with patch("augean.main.loader.detect_format", side_effect=WorkbookFormatUnknownError("?")):
            main()
        assert list(tmp_path.glob("*_errors.csv")) == []

    def test_format_override_unknown_name_logs_and_continues(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", _argv(
            tmp_path,
            workbooks_dir=WORKBOOKS_DIR / "haemonc",
            extra=["--format", "nonexistent_v99"],
        ))
        main()
        assert list(tmp_path.glob("*_errors.csv")) == []

    def test_validation_errors_write_csv(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", _argv(tmp_path, workbooks_dir=WORKBOOKS_DIR / "haemonc"))
        with patch("augean.main.validator.validate_all", return_value=["bad field value"]):
            main()
        csvs = list(tmp_path.glob("*_errors.csv"))
        assert len(csvs) > 0
        assert "bad field value" in csvs[0].read_text()

    def test_parse_error_writes_csv(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", _argv(tmp_path, workbooks_dir=WORKBOOKS_DIR / "haemonc"))
        with patch("augean.main.parser.parse_workbook", side_effect=RuntimeError("parse boom")):
            main()
        csvs = list(tmp_path.glob("*_errors.csv"))
        assert len(csvs) > 0
        assert "parse boom" in csvs[0].read_text()

    def test_transform_error_writes_csv(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", _argv(tmp_path, workbooks_dir=WORKBOOKS_DIR / "haemonc"))
        with patch("augean.main.transformer.transform", side_effect=RuntimeError("transform boom")):
            main()
        csvs = list(tmp_path.glob("*_errors.csv"))
        assert len(csvs) > 0
        assert "transform boom" in csvs[0].read_text()


# ---------------------------------------------------------------------------
# DB write path
# ---------------------------------------------------------------------------

_DB_MOCKS = [
    "augean.main.db.add_workbook",
    "augean.main.db.mark_workbook_parsed",
    "augean.main.db.mark_workbook_failed",
    "augean.main.db.migrate_schema",
]


@pytest.fixture
def db_argv(tmp_path):
    creds = _write_creds(tmp_path)
    return _argv(tmp_path, workbooks_dir=WORKBOOKS_DIR / "haemonc", dry_run=False, db_creds=creds)


class TestDbWrite:
    def test_successful_insert_marks_workbook_parsed(self, tmp_path, monkeypatch, db_argv):
        monkeypatch.setattr(sys, "argv", db_argv)
        with patch("augean.main.db.create_engine"), \
             patch("augean.main.db.add_workbook"), \
             patch("augean.main.db.add_variants", return_value=2), \
             patch("augean.main.db.mark_workbook_parsed") as mock_parsed, \
             patch("augean.main.db.mark_workbook_failed"), \
             patch("augean.main.db.migrate_schema"):
            main()
        assert mock_parsed.called

    def test_schema_mismatch_writes_csv(self, tmp_path, monkeypatch, db_argv):
        from augean.errors import SchemaMismatchError
        monkeypatch.setattr(sys, "argv", db_argv)
        with patch("augean.main.db.create_engine"), \
             patch("augean.main.db.add_workbook"), \
             patch("augean.main.db.add_variants", side_effect=SchemaMismatchError("col mismatch")), \
             patch("augean.main.db.mark_workbook_parsed"), \
             patch("augean.main.db.mark_workbook_failed"), \
             patch("augean.main.db.migrate_schema"):
            main()
        csvs = list(tmp_path.glob("*_errors.csv"))
        assert len(csvs) > 0
        assert "col mismatch" in csvs[0].read_text()

    def test_migrate_flag_calls_migrate_schema(self, tmp_path, monkeypatch, db_argv):
        monkeypatch.setattr(sys, "argv", db_argv + ["--migrate"])
        with patch("augean.main.db.create_engine"), \
             patch("augean.main.db.add_workbook"), \
             patch("augean.main.db.add_variants", return_value=2), \
             patch("augean.main.db.mark_workbook_parsed"), \
             patch("augean.main.db.mark_workbook_failed"), \
             patch("augean.main.db.migrate_schema") as mock_migrate:
            main()
        assert mock_migrate.called

    def test_validation_error_marks_workbook_failed(self, tmp_path, monkeypatch, db_argv):
        monkeypatch.setattr(sys, "argv", db_argv)
        with patch("augean.main.db.create_engine"), \
             patch("augean.main.db.add_workbook"), \
             patch("augean.main.db.add_variants"), \
             patch("augean.main.db.mark_workbook_parsed"), \
             patch("augean.main.db.mark_workbook_failed") as mock_failed, \
             patch("augean.main.db.migrate_schema"), \
             patch("augean.main.validator.validate_all", return_value=["bad value"]):
            main()
        assert mock_failed.called
