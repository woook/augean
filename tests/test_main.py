"""Smoke tests for the CLI entry point (augean/main.py)."""
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from augean.main import _write_error_csv, main, parse_args

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
