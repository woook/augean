"""All PostgreSQL operations via SQLAlchemy."""
import datetime
import logging

import pandas as pd
from sqlalchemy import create_engine as _sa_create_engine, text
from sqlalchemy.engine import Engine

from hestia.errors import ParseError

log = logging.getLogger(__name__)

_WORKBOOKS_TABLE = "testdirectory.staging_workbooks"


def create_engine(db_creds: dict) -> Engine:
    """Build SQLAlchemy engine from credentials dict."""
    url = (
        f"postgresql+psycopg2://{db_creds['user']}:{db_creds['password']}"
        f"@{db_creds['host']}:{db_creds.get('port', 5432)}/{db_creds['database']}"
    )
    return _sa_create_engine(url)


def add_workbook(engine: Engine, workbook_name: str, format_name: str = "") -> None:
    """INSERT into staging_workbooks; ON CONFLICT DO NOTHING."""
    now = datetime.datetime.now()
    with engine.begin() as conn:
        result = conn.execute(
            text(
                f"INSERT INTO {_WORKBOOKS_TABLE} "
                "(workbook_name, date, format_name) "
                "VALUES (:wb, :date, :fmt) "
                "ON CONFLICT (workbook_name) DO NOTHING"
            ),
            {"wb": workbook_name, "date": now, "fmt": format_name},
        )
        log.debug("add_workbook '%s': %d row(s) affected", workbook_name, result.rowcount)


def mark_workbook_parsed(engine: Engine, workbook_name: str) -> None:
    """UPDATE staging_workbooks SET parse_status=TRUE."""
    with engine.begin() as conn:
        conn.execute(
            text(
                f"UPDATE {_WORKBOOKS_TABLE} SET parse_status = TRUE "
                "WHERE workbook_name = :wb"
            ),
            {"wb": workbook_name},
        )
    log.debug("Marked '%s' as parsed", workbook_name)


def mark_workbook_failed(
    engine: Engine, workbook_name: str, errors: list[ParseError]
) -> None:
    """UPDATE staging_workbooks SET parse_status=FALSE, comment=<errors>."""
    error_str = "; ".join(str(e) for e in errors)
    with engine.begin() as conn:
        conn.execute(
            text(
                f"UPDATE {_WORKBOOKS_TABLE} "
                "SET parse_status = FALSE, comment = :err "
                "WHERE workbook_name = :wb"
            ),
            {"err": error_str, "wb": workbook_name},
        )
    log.debug("Marked '%s' as failed", workbook_name)


def add_variants(engine: Engine, df: pd.DataFrame, table: str, schema: str) -> int:
    """df.to_sql(table, ..., if_exists='append'); return row count."""
    if df.empty:
        log.debug("add_variants: DataFrame is empty, nothing to insert")
        return 0
    with engine.begin() as conn:
        rows = df.to_sql(table, conn, if_exists="append", schema=schema, index=False)
    count = rows if rows is not None else 0
    log.info("Inserted %d rows into %s.%s", count, schema, table)
    return count


def get_parsed_workbooks(engine: Engine) -> list[str]:
    """Return list of workbook_name where parse_status=TRUE."""
    with engine.connect() as conn:
        result = conn.execute(
            text(f"SELECT workbook_name FROM {_WORKBOOKS_TABLE} WHERE parse_status = TRUE")
        )
        return [row[0] for row in result]


def get_failed_workbooks(engine: Engine) -> list[str]:
    """Return list of workbook_name where parse_status=FALSE."""
    with engine.connect() as conn:
        result = conn.execute(
            text(f"SELECT workbook_name FROM {_WORKBOOKS_TABLE} WHERE parse_status = FALSE")
        )
        return [row[0] for row in result]
