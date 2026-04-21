#!/usr/bin/env python3
"""Regenerate golden CSV files for acceptance tests.

Run this script whenever the pipeline output for a test workbook is
intentionally changed (e.g. a new column added, a normalisation updated).
After running, inspect the diff carefully and commit the updated file as
part of the same PR that caused the change.

Usage:
    python scripts/regenerate_golden.py

The script writes one golden file per workbook found in
tests/test_data/workbooks/haemonc/. It skips any workbook whose name
does not match the pattern used by the test suite.
"""
from pathlib import Path
import sys

# Allow running from the repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from augean import config as config_module, loader, parser, transformer  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parent.parent

CONFIGS_DIR = _REPO_ROOT / "configs"
WORKBOOKS_DIR = _REPO_ROOT / "tests" / "test_data" / "workbooks" / "haemonc"
GOLDEN_DIR = _REPO_ROOT / "tests" / "test_data" / "golden"
GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

# Columns generated at parse time — different on every run, excluded from golden
EXCLUDE_COLS = {"local_id", "linking_id"}

# Stable sort key for deterministic row order
SORT_COLS = ["chromosome", "start", "hgvsc", "variant_category"]


def regenerate(wb_path: Path, configs: list) -> None:
    workbook = loader.load_workbook(wb_path)
    cfg = loader.detect_format(workbook, configs)
    raw_df = parser.parse_workbook(workbook, cfg, wb_path)
    final_df = transformer.transform(raw_df, cfg)

    compare_cols = [c for c in final_df.columns if c not in EXCLUDE_COLS]
    final_df = (
        final_df[compare_cols]
        .sort_values(SORT_COLS)
        .reset_index(drop=True)
    )

    out = GOLDEN_DIR / f"{wb_path.stem}.csv"
    final_df.to_csv(out, index=False)
    print(f"  {wb_path.name} → {out}  ({len(final_df)} rows, {len(final_df.columns)} cols)")


def main() -> None:
    configs = config_module.load_configs(CONFIGS_DIR)
    workbooks = sorted(WORKBOOKS_DIR.glob("*.xlsx"))
    if not workbooks:
        print("No workbooks found in", WORKBOOKS_DIR)
        sys.exit(1)

    print(f"Regenerating {len(workbooks)} golden file(s)...")
    failures = []
    for wb_path in workbooks:
        try:
            regenerate(wb_path, configs)
        except Exception as exc:
            failures.append(wb_path.name)
            print(f"  FAILED {wb_path.name}: {exc}")

    print("\nDone. Review the diff before committing:")
    print("  git diff tests/test_data/golden/")
    if failures:
        print(f"\n{len(failures)} workbook(s) failed: {failures}")
        sys.exit(1)


if __name__ == "__main__":
    main()
