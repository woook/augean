"""All PostgreSQL operations via SQLAlchemy."""
import datetime
import logging

import pandas as pd
from sqlalchemy import create_engine as _sa_create_engine, inspect as _sa_inspect, text
from sqlalchemy.engine import Engine, URL

from augean.errors import SchemaMismatchError

log = logging.getLogger(__name__)


def create_engine(db_creds: dict) -> Engine:
    """Build SQLAlchemy engine from credentials dict."""
    url = URL.create(
        "postgresql+psycopg2",
        username=db_creds["user"],
        password=db_creds["password"],
        host=db_creds["host"],
        port=db_creds.get("port", 5432),
        database=db_creds["database"],
    )
    return _sa_create_engine(url)


def add_workbook(
    engine: Engine, workbook_name: str, format_name: str = "",
    schema: str = "testdirectory", workbooks_table: str = "staging_workbooks",
) -> None:
    """INSERT into workbooks tracking table; ON CONFLICT DO NOTHING."""
    qualified = f"{schema}.{workbooks_table}"
    now = datetime.datetime.now(datetime.timezone.utc)
    with engine.begin() as conn:
        result = conn.execute(
            text(
                f"INSERT INTO {qualified} "
                "(workbook_name, date, format_name) "
                "VALUES (:wb, :date, :fmt) "
                "ON CONFLICT (workbook_name) DO NOTHING"
            ),
            {"wb": workbook_name, "date": now, "fmt": format_name},
        )
        log.debug("add_workbook '%s': %d row(s) affected", workbook_name, result.rowcount)


def mark_workbook_parsed(
    engine: Engine, workbook_name: str,
    schema: str = "testdirectory", workbooks_table: str = "staging_workbooks",
) -> None:
    """UPDATE workbooks tracking table SET parse_status=TRUE."""
    qualified = f"{schema}.{workbooks_table}"
    with engine.begin() as conn:
        conn.execute(
            text(f"UPDATE {qualified} SET parse_status = TRUE WHERE workbook_name = :wb"),
            {"wb": workbook_name},
        )
    log.debug("Marked '%s' as parsed", workbook_name)


def mark_workbook_failed(
    engine: Engine, workbook_name: str, errors: list[str],
    schema: str = "testdirectory", workbooks_table: str = "staging_workbooks",
) -> None:
    """UPDATE workbooks tracking table SET parse_status=FALSE, comment=<errors>."""
    qualified = f"{schema}.{workbooks_table}"
    error_str = "; ".join(str(e) for e in errors)
    with engine.begin() as conn:
        conn.execute(
            text(
                f"UPDATE {qualified} "
                "SET parse_status = FALSE, comment = :err "
                "WHERE workbook_name = :wb"
            ),
            {"err": error_str, "wb": workbook_name},
        )
    log.debug("Marked '%s' as failed", workbook_name)


def add_variants(engine: Engine, df: pd.DataFrame, table: str, schema: str) -> int:
    """df.to_sql(table, ..., if_exists='append'); return row count.

    Raises SchemaMismatchError if the DataFrame contains columns not present in
    the target table, with ALTER TABLE statements to resolve the mismatch.
    """
    if df.empty:
        log.debug("add_variants: DataFrame is empty, nothing to insert")
        return 0
    _check_schema(engine, df, table, schema)
    with engine.begin() as conn:
        rows = df.to_sql(table, conn, if_exists="append", schema=schema, index=False)
    count = rows if rows is not None else 0
    log.info("Inserted %d rows into %s.%s", count, schema, table)
    return count


_PD_TO_PG = {
    "object": "TEXT",
    "float64": "NUMERIC",
    "int64": "INTEGER",
    "datetime64[ns]": "DATE",
}


def migrate_schema(engine: Engine, df: pd.DataFrame, table: str, schema: str) -> None:
    """Add any DataFrame columns absent from the target table via ALTER TABLE.

    Skipped when the table does not yet exist. Logs each column added.
    Duplicate-column errors (race with a concurrent process) are treated as no-ops.
    """
    missing = _missing_columns(engine, df, table, schema)
    if not missing:
        log.info("Schema up to date for %s.%s", schema, table)
        return
    with engine.begin() as conn:
        for col in missing:
            pg_type = _PD_TO_PG.get(str(df[col].dtype), "TEXT")
            log.warning(
                "Adding column to %s.%s: %s %s", schema, table, col, pg_type
            )
            try:
                conn.execute(text(f"ALTER TABLE {schema}.{table} ADD COLUMN {col} {pg_type}"))
            except Exception as exc:
                if getattr(getattr(exc, "orig", None), "pgcode", None) == "42701":
                    log.debug("Column %s already exists in %s.%s (concurrent add), skipping", col, schema, table)
                else:
                    raise


def _check_schema(engine: Engine, df: pd.DataFrame, table: str, schema: str) -> None:
    """Raise SchemaMismatchError if df has columns absent from the target table.

    Skipped when the table does not yet exist (to_sql will create it).
    """
    missing = _missing_columns(engine, df, table, schema)
    if not missing:
        return
    statements = "\n".join(
        f"    ALTER TABLE {schema}.{table} ADD COLUMN {col}"
        f" {_PD_TO_PG.get(str(df[col].dtype), 'TEXT')};"
        for col in missing
    )
    raise SchemaMismatchError(
        f"The following columns are not present in {schema}.{table} "
        f"and must be added before inserting: {missing}\n\n"
        f"Run the following SQL to resolve:\n\n{statements}\n\n"
        f"Or re-run with --migrate to apply automatically."
    )


def _missing_columns(engine: Engine, df: pd.DataFrame, table: str, schema: str) -> list[str]:
    """Return DataFrame columns not present in the target table.

    Returns empty list if the table does not exist.
    """
    inspector = _sa_inspect(engine)
    if not inspector.has_table(table, schema=schema):
        return []
    existing = {col["name"] for col in inspector.get_columns(table, schema=schema)}
    return [col for col in df.columns if col not in existing]


def get_parsed_workbooks(
    engine: Engine,
    schema: str = "testdirectory", workbooks_table: str = "staging_workbooks",
) -> list[str]:
    """Return list of workbook_name where parse_status=TRUE."""
    qualified = f"{schema}.{workbooks_table}"
    with engine.connect() as conn:
        result = conn.execute(
            text(f"SELECT workbook_name FROM {qualified} WHERE parse_status = TRUE")
        )
        return [row[0] for row in result]


def get_failed_workbooks(
    engine: Engine,
    schema: str = "testdirectory", workbooks_table: str = "staging_workbooks",
) -> list[str]:
    """Return list of workbook_name where parse_status=FALSE."""
    qualified = f"{schema}.{workbooks_table}"
    with engine.connect() as conn:
        result = conn.execute(
            text(f"SELECT workbook_name FROM {qualified} WHERE parse_status = FALSE")
        )
        return [row[0] for row in result]
