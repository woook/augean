"""CLI entry point for Augean workbook staging extractor."""
import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

from augean import config as config_module
from augean import db, loader, parser, transformer, validator
from augean.errors import AmbiguousWorkbookFormatError, SchemaMismatchError, WorkbookFormatUnknownError

log = logging.getLogger(__name__)


_DEPLOYMENT_KEYS = {"config_dir", "output_dir", "organisation", "db_schema", "db_table", "db_workbooks_table"}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Augean: config-driven Excel workbook staging extractor"
    )
    ap.add_argument("--deployment", help="Path to deployment config JSON")
    ap.add_argument("--db_credentials", required=True, help="Path to JSON with DB credentials")
    ap.add_argument("--config_dir", default=None, help="Path to configs/ directory")

    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--workbooks_path", help="Directory containing .xlsx workbooks")
    group.add_argument("--samples_file", help="Text file with one workbook path per line")

    ap.add_argument("--output_dir", default=None, help="Directory for error CSVs")
    ap.add_argument("--organisation", default=None, choices=["CUH", "NUH"], help="Organisation label")
    ap.add_argument("--dry_run", action="store_true", help="Parse only, no DB writes")
    ap.add_argument("--migrate", action="store_true", help="Add missing DB columns before inserting")
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
    ap.add_argument("--db_table", default=None, help="Target DB table name (overrides deployment config)")
    ap.add_argument("--db_schema", default=None, help="Target DB schema (overrides deployment config)")
    ap.add_argument("--db_workbooks_table", default=None, help="Workbook tracking table name (overrides deployment config)")
    args = ap.parse_args()
    _apply_deployment_config(args)
    return args


def _apply_deployment_config(args: argparse.Namespace) -> None:
    """Load deployment config and fill in any args not set on the CLI."""
    deployment = {}
    deployment_dir = None
    if args.deployment:
        deployment_path = Path(args.deployment)
        deployment_dir = deployment_path.parent.resolve()
        with deployment_path.open(encoding="utf-8") as f:
            deployment = json.load(f)

    # Deployment config fills in; CLI flags override
    for key in _DEPLOYMENT_KEYS:
        if getattr(args, key, None) is None:
            value = deployment.get(key)
            if (
                deployment_dir is not None
                and key in {"config_dir", "output_dir"}
                and value is not None
                and not Path(value).is_absolute()
            ):
                value = str((deployment_dir / value).resolve())
            setattr(args, key, value)

    # Final fallback defaults
    if args.db_schema is None:
        args.db_schema = "testdirectory"
    if args.db_table is None:
        args.db_table = "inca"
    if args.db_workbooks_table is None:
        args.db_workbooks_table = "staging_workbooks"

    missing = [f"--{k}" for k in ("config_dir", "output_dir") if getattr(args, k, None) is None]
    if missing:
        raise SystemExit(
            f"error: the following arguments are required (via CLI or deployment config): {', '.join(missing)}"
        )


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

    basenames = [f.name for f in workbook_files]
    duplicates = {n for n in basenames if basenames.count(n) > 1}
    if duplicates:
        raise SystemExit(
            f"error: duplicate workbook filename(s) in batch — each workbook name must be "
            f"unique as it is used as the database key: {sorted(duplicates)}"
        )

    engine = None
    if not args.dry_run:
        with open(args.db_credentials) as f:
            db_creds = json.load(f)
        engine = db.create_engine(db_creds)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    already_parsed: set[str] = set()
    if engine is not None:
        already_parsed = set(
            db.get_parsed_workbooks(engine, schema=args.db_schema, workbooks_table=args.db_workbooks_table)
        )
        if already_parsed:
            log.info("%d workbook(s) already in database and will be skipped", len(already_parsed))

    for wb_path in workbook_files:
        wb_name = wb_path.name
        if wb_name in already_parsed:
            log.info("Skipping '%s': already successfully parsed", wb_name)
            continue
        log.info("--- Processing: %s ---", wb_name)
        processed = _process_workbook(
            wb_path=wb_path,
            wb_name=wb_name,
            configs=configs,
            engine=engine,
            output_dir=output_dir,
            args=args,
        )
        if processed:
            already_parsed.add(wb_name)

    log.info("Done.")


def _process_workbook(*, wb_path, wb_name, configs, engine, output_dir, args) -> bool:
    try:
        workbook = loader.load_workbook(wb_path)
    except OSError as exc:
        log.error("Cannot open '%s': %s", wb_name, exc)
        return False

    # Format detection
    try:
        if args.format_override:
            matched = [c for c in configs if c["format_name"] == args.format_override]
            if not matched:
                log.error("Format override '%s' not found in configs", args.format_override)
                return False
            cfg = matched[0]
        else:
            cfg = loader.detect_format(workbook, configs)
        log.info("Detected format: %s", cfg["format_name"])
    except (WorkbookFormatUnknownError, AmbiguousWorkbookFormatError) as exc:
        log.error("Format detection failed for '%s': %s", wb_name, exc)
        return False

    wb_schema = args.db_schema
    wb_table = args.db_workbooks_table

    if engine is not None:
        try:
            db.add_workbook(engine, wb_name, cfg["format_name"], schema=wb_schema, workbooks_table=wb_table)
        except Exception as exc:
            log.error("Workbook tracking insert failed for '%s': %s", wb_name, exc)
            _write_error_csv(output_dir, wb_name, [f"Workbook tracking error: {exc}"])
            return False

    # Parse
    try:
        raw_df = parser.parse_workbook(workbook, cfg, wb_path)
    except Exception as exc:
        log.error("Parsing failed for '%s': %s", wb_name, exc)
        errors = [f"Parsing error: {exc}"]
        if engine is not None:
            db.mark_workbook_failed(engine, wb_name, errors, schema=wb_schema, workbooks_table=wb_table)
        _write_error_csv(output_dir, wb_name, errors)
        return False

    # Validate
    errors = validator.validate_all(workbook, raw_df, cfg, wb_name)
    if errors:
        log.warning("%d validation error(s) for '%s'", len(errors), wb_name)
        for err in errors:
            log.warning("  %s", err)
        if engine is not None:
            db.mark_workbook_failed(engine, wb_name, errors, schema=wb_schema, workbooks_table=wb_table)
        _write_error_csv(output_dir, wb_name, errors)
        return False

    # Transform
    try:
        final_df = transformer.transform(raw_df, cfg)
    except Exception as exc:
        log.error("Transform failed for '%s': %s", wb_name, exc)
        errors = [f"Transform error: {exc}"]
        if engine is not None:
            db.mark_workbook_failed(engine, wb_name, errors, schema=wb_schema, workbooks_table=wb_table)
        _write_error_csv(output_dir, wb_name, errors)
        return False

    if args.dry_run:
        log.info("DRY RUN: would insert %d row(s) for '%s'", len(final_df), wb_name)
        return False

    # Insert
    db_cfg = cfg.get("db", {})
    table = db_cfg.get("table", args.db_table)
    schema = db_cfg.get("schema", args.db_schema)
    try:
        if args.migrate:
            db.migrate_schema(engine, final_df, table, schema)
        rows = db.add_variants(engine, final_df, table, schema)
    except SchemaMismatchError as exc:
        log.error("Schema mismatch for '%s': %s", wb_name, exc)
        db.mark_workbook_failed(engine, wb_name, [str(exc)], schema=wb_schema, workbooks_table=wb_table)
        _write_error_csv(output_dir, wb_name, [str(exc)])
        return False
    except Exception as exc:
        log.error("DB write failed for '%s': %s", wb_name, exc)
        errors = [f"DB write error: {exc}"]
        db.mark_workbook_failed(engine, wb_name, errors, schema=wb_schema, workbooks_table=wb_table)
        _write_error_csv(output_dir, wb_name, errors)
        return False
    log.info("Inserted %d row(s) for '%s'", rows, wb_name)
    try:
        db.mark_workbook_parsed(engine, wb_name, schema=wb_schema, workbooks_table=wb_table)
    except Exception as exc:
        log.error("Failed to mark workbook parsed for '%s': %s", wb_name, exc)
        _write_error_csv(output_dir, wb_name, [f"Workbook tracking error: {exc}"])
        return False
    return True


def _write_error_csv(output_dir: Path, workbook_name: str, errors: list) -> None:
    rows = [{"workbook": workbook_name, "error": str(e)} for e in errors]
    out_path = output_dir / f"{workbook_name}_errors.csv"
    pd.DataFrame(rows).to_csv(out_path, index=False)
    log.info("Wrote errors to %s", out_path)


if __name__ == "__main__":
    main()
