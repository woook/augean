"""CLI entry point for Hestia workbook staging extractor."""
import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

from hestia import config as config_module
from hestia import db, loader, parser, transformer, validator
from hestia.errors import AmbiguousWorkbookFormatError, WorkbookFormatUnknownError

log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Hestia: config-driven Excel workbook staging extractor"
    )
    ap.add_argument("--db_credentials", required=True, help="Path to JSON with DB credentials")
    ap.add_argument("--config_dir", required=True, help="Path to configs/ directory")

    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--workbooks_path", help="Directory containing .xlsx workbooks")
    group.add_argument("--samples_file", help="Text file with one workbook path per line")

    ap.add_argument("--output_dir", required=True, help="Directory for error CSVs")
    ap.add_argument("--organisation", choices=["CUH", "NUH"], help="Organisation label")
    ap.add_argument("--dry_run", action="store_true", help="Parse only, no DB writes")
    ap.add_argument(
        "--format",
        dest="format_override",
        metavar="FORMAT_NAME",
        help="Skip auto-detect and use this config format_name",
    )
    ap.add_argument(
        "--log_level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    ap.add_argument("--db_table", default="inca", help="Target DB table name")
    ap.add_argument("--db_schema", default="testdirectory", help="Target DB schema")
    return ap.parse_args()


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )

    configs = config_module.load_configs(Path(args.config_dir))

    if args.workbooks_path:
        workbook_files = sorted(Path(args.workbooks_path).glob("*.xlsx"))
    else:
        with open(args.samples_file) as f:
            workbook_files = [Path(line.strip()) for line in f if line.strip()]

    log.info("Found %d workbook(s) to process", len(workbook_files))

    engine = None
    if not args.dry_run:
        with open(args.db_credentials) as f:
            db_creds = json.load(f)
        engine = db.create_engine(db_creds)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for wb_path in workbook_files:
        wb_name = wb_path.name
        log.info("--- Processing: %s ---", wb_name)
        _process_workbook(
            wb_path=wb_path,
            wb_name=wb_name,
            configs=configs,
            engine=engine,
            output_dir=output_dir,
            args=args,
        )

    log.info("Done.")


def _process_workbook(*, wb_path, wb_name, configs, engine, output_dir, args) -> None:
    try:
        workbook = loader.load_workbook(wb_path)
    except OSError as exc:
        log.error("Cannot open '%s': %s", wb_name, exc)
        return

    # Format detection
    try:
        if args.format_override:
            matched = [c for c in configs if c["format_name"] == args.format_override]
            if not matched:
                log.error("Format override '%s' not found in configs", args.format_override)
                return
            cfg = matched[0]
        else:
            cfg = loader.detect_format(workbook, configs)
        log.info("Detected format: %s", cfg["format_name"])
    except (WorkbookFormatUnknownError, AmbiguousWorkbookFormatError) as exc:
        log.error("Format detection failed for '%s': %s", wb_name, exc)
        return

    if engine is not None:
        db.add_workbook(engine, wb_name, cfg["format_name"])

    # Parse
    try:
        raw_df = parser.parse_workbook(workbook, cfg, wb_path)
    except Exception as exc:
        log.error("Parsing failed for '%s': %s", wb_name, exc)
        errors = [f"Parsing error: {exc}"]
        if engine is not None:
            db.mark_workbook_failed(engine, wb_name, errors)
        _write_error_csv(output_dir, wb_name, errors)
        return

    # Validate
    errors = validator.validate_all(workbook, raw_df, cfg, wb_name)
    if errors:
        log.warning("%d validation error(s) for '%s'", len(errors), wb_name)
        for err in errors:
            log.warning("  %s", err)
        if engine is not None:
            db.mark_workbook_failed(engine, wb_name, errors)
        _write_error_csv(output_dir, wb_name, errors)
        return

    # Transform
    try:
        final_df = transformer.transform(raw_df, cfg)
    except Exception as exc:
        log.error("Transform failed for '%s': %s", wb_name, exc)
        errors = [f"Transform error: {exc}"]
        if engine is not None:
            db.mark_workbook_failed(engine, wb_name, errors)
        _write_error_csv(output_dir, wb_name, errors)
        return

    if args.dry_run:
        log.info("DRY RUN: would insert %d row(s) for '%s'", len(final_df), wb_name)
        return

    # Insert
    db_cfg = cfg.get("db", {})
    table = db_cfg.get("table", args.db_table)
    schema = db_cfg.get("schema", args.db_schema)
    rows = db.add_variants(engine, final_df, table, schema)
    log.info("Inserted %d row(s) for '%s'", rows, wb_name)
    db.mark_workbook_parsed(engine, wb_name)


def _write_error_csv(output_dir: Path, workbook_name: str, errors: list) -> None:
    rows = [{"workbook": workbook_name, "error": str(e)} for e in errors]
    out_path = output_dir / f"{workbook_name}_errors.csv"
    pd.DataFrame(rows).to_csv(out_path, index=False)
    log.info("Wrote errors to %s", out_path)


if __name__ == "__main__":
    main()
