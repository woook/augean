"""Smoke tests for the CLI entry point (augean/main.py)."""
import subprocess
import sys
from pathlib import Path

import pytest

from augean.main import _write_error_csv, main, parse_args

CONFIGS_DIR = Path(__file__).parent.parent / "configs"
WORKBOOKS_DIR = Path(__file__).parent / "test_data" / "workbooks"


def test_package_importable():
    import augean
    assert augean is not None


def test_cli_help():
    result = subprocess.run(["augean", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "augean" in result.stdout.lower() or "usage" in result.stdout.lower()


def test_write_error_csv(tmp_path):
    _write_error_csv(tmp_path, "wb.xlsx", ["err one", "err two"])
    out = tmp_path / "wb.xlsx_errors.csv"
    assert out.exists()
    text = out.read_text()
    assert "err one" in text
    assert "err two" in text


def test_main_dry_run_rd_dias(tmp_path, monkeypatch):
    """End-to-end: parse + validate + transform RD Dias workbooks without DB."""
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
