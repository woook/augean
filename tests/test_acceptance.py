"""Acceptance tests: pipeline output vs golden file vs database.

These tests require a live PostgreSQL connection and are excluded from the
default pytest run. Run them explicitly with:

    pytest tests/test_acceptance.py -m acceptance \
        --db_credentials /path/to/db_credentials.json \
        [--acceptance_schema testdirectory]

Two orthogonal checks per workbook:

  1. parser_matches_golden  — pipeline output matches the committed CSV snapshot.
     Catches regressions in parsing, transformation, or normalisation.

  2. db_matches_golden      — database content for this workbook matches the
     committed CSV snapshot.
     Catches bugs in the DB write path: wrong column mapping, dropped rows,
     extra phantom rows, type corruption on insert.

The golden file is the shared reference — it is independent of both the
pipeline and the database. When the pipeline output is intentionally changed
(new column, new normalisation), regenerate the golden file with:

    python scripts/regenerate_golden.py

then inspect the diff and commit it as part of the same PR.
"""
import pandas as pd
import pytest
from pathlib import Path
from sqlalchemy import text

from augean import config as config_module, loader, parser, transformer

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIGS_DIR = Path(__file__).parent.parent / "configs"
GOLDEN_DIR = Path(__file__).parent / "test_data" / "golden"
WORKBOOKS_DIR = Path(__file__).parent / "test_data" / "workbooks" / "haemonc"

# Columns generated at parse time — UUID, different on every run
_EXCLUDE = {"local_id", "linking_id"}

# Stable sort key so row order is deterministic across both paths
_SORT = ["chromosome", "start", "hgvsc", "variant_category"]

# DB-only columns that augean never writes — exclude from DB query comparison
_DB_ONLY = {"id", "east_panels_id", "submission_id", "accession_id", "clinvar_status",
            "condition_id_type", "condition_id_value", "r_code", "preferred_condition_name",
            "organisation", "institution", "organisation_id", "associated_disease",
            "known_inheritance", "prevalence",
            "pvs1", "pvs1_evidence", "ps1", "ps1_evidence", "ps2", "ps2_evidence",
            "ps3", "ps3_evidence", "ps4", "ps4_evidence",
            "pm1", "pm1_evidence", "pm2", "pm2_evidence", "pm3", "pm3_evidence",
            "pm4", "pm4_evidence", "pm5", "pm5_evidence", "pm6", "pm6_evidence",
            "pp1", "pp1_evidence", "pp2", "pp2_evidence", "pp3", "pp3_evidence",
            "pp4", "pp4_evidence",
            "ba1", "ba1_evidence", "bs1", "bs1_evidence", "bs2", "bs2_evidence",
            "bs3", "bs3_evidence", "bs4", "bs4_evidence",
            "bp1", "bp1_evidence", "bp2", "bp2_evidence", "bp3", "bp3_evidence",
            "bp4", "bp4_evidence", "bp5", "bp5_evidence", "bp7", "bp7_evidence",
            "germline_classification", "comment_on_classification",
            "reference_allele", "alternate_allele"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Select, sort, reset index, and coerce all values to string for comparison.

    Converting to string is the most robust way to compare pipeline output
    (where ID columns are str) against CSV-loaded data (where pandas reads
    all-numeric columns as int64). NaN is normalised to the empty string.
    """
    present = [c for c in cols if c in df.columns]
    result = (
        df[present]
        .sort_values(_SORT)
        .reset_index(drop=True)
    )
    # Coerce to string, normalising NaN/None/pd.NaT to empty string
    result = result.astype(object).where(result.notna(), other="")
    # Normalise datetimes to ISO date (YYYY-MM-DD) to avoid time-component noise
    for col in result.columns:
        result[col] = result[col].apply(
            lambda v: v.strftime("%Y-%m-%d") if hasattr(v, "strftime") else str(v)
        )
    return result


def _pipeline_df(wb_path: Path, configs: list) -> pd.DataFrame:
    """Run workbook through augean pipeline; return final DataFrame."""
    workbook = loader.load_workbook(wb_path)
    cfg = loader.detect_format(workbook, configs)
    raw_df = parser.parse_workbook(workbook, cfg, wb_path)
    return transformer.transform(raw_df, cfg)


def _load_golden(wb_path: Path) -> pd.DataFrame:
    golden_path = GOLDEN_DIR / f"{wb_path.stem}.csv"
    if not golden_path.exists():
        pytest.skip(f"No golden file at {golden_path} — run scripts/regenerate_golden.py")
    return pd.read_csv(golden_path)


def _query_db(engine, schema: str, specimen_id: str, batch_id: str) -> pd.DataFrame:
    """Query inca for all rows belonging to this workbook."""
    with engine.connect() as conn:
        result = conn.execute(
            text(
                f"SELECT * FROM {schema}.inca "
                "WHERE specimen_id = :sid AND batch_id = :bid"
            ),
            {"sid": specimen_id, "bid": batch_id},
        )
        rows = result.fetchall()
        columns = list(result.keys())
    return pd.DataFrame(rows, columns=columns)


# ---------------------------------------------------------------------------
# Parametrize over all workbooks that have a golden file
# ---------------------------------------------------------------------------

def _acceptance_params():
    """Return (wb_path, specimen_id, batch_id) for each golden-file workbook.

    Never raises — invalid entries are included with sentinel None values so
    that errors surface at test execution time, not at collection time. This
    prevents a stale golden file from breaking the default pytest run.
    """
    params = []
    for golden in sorted(GOLDEN_DIR.glob("*.csv")):
        wb_path = WORKBOOKS_DIR / f"{golden.stem}.xlsx"
        parts = golden.stem.split("-", 5)
        specimen_id = parts[1] if len(parts) >= 3 else None
        batch_id = parts[2] if len(parts) >= 3 else None
        params.append(pytest.param(wb_path, specimen_id, batch_id, id=golden.stem))
    return params


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.acceptance
class TestWorkbookAcceptance:

    @pytest.fixture(scope="class")
    def configs(self):
        return config_module.load_configs(CONFIGS_DIR)

    # --- parser vs golden ---------------------------------------------------

    @pytest.mark.parametrize("wb_path,specimen_id,batch_id", _acceptance_params())
    def test_parser_matches_golden(self, wb_path, specimen_id, batch_id, configs):
        """Pipeline output matches the committed golden CSV snapshot.

        Fails if parsing, transformation, or normalisation produces different
        output from when the golden file was last regenerated and verified.
        """
        if not wb_path.exists():
            pytest.fail(
                f"Golden file has no matching workbook at '{wb_path}'. "
                "Either add the workbook or remove the orphaned golden file."
            )
        if specimen_id is None or batch_id is None:
            pytest.fail(
                f"Golden file '{wb_path.stem}.csv' does not follow the expected "
                "[instrument]-[specimen]-[batch]-... naming pattern."
            )
        golden_df = _load_golden(wb_path)
        pipeline_df = _pipeline_df(wb_path, configs)

        compare_cols = [c for c in golden_df.columns if c not in _EXCLUDE]
        pipeline_cols = [c for c in pipeline_df.columns if c not in _EXCLUDE]
        assert set(pipeline_cols) == set(compare_cols), (
            f"Column mismatch between pipeline and golden file for {wb_path.name}.\n"
            f"  In pipeline only: {sorted(set(pipeline_cols) - set(compare_cols))}\n"
            f"  In golden only:   {sorted(set(compare_cols) - set(pipeline_cols))}\n"
            "Run scripts/regenerate_golden.py if this change is intentional."
        )

        pd.testing.assert_frame_equal(
            _normalise(pipeline_df, compare_cols),
            _normalise(golden_df, compare_cols),
            check_dtype=False,
            check_like=False,
            obj=f"parser vs golden for {wb_path.name}",
        )

    # --- db vs golden -------------------------------------------------------

    @pytest.mark.parametrize("wb_path,specimen_id,batch_id", _acceptance_params())
    def test_db_matches_golden(
        self, wb_path, specimen_id, batch_id, configs,
        acceptance_engine, acceptance_schema,
    ):
        """Database content matches the committed golden CSV snapshot.

        Fails if the DB write path dropped rows, inserted extra rows, corrupted
        a value, or mapped a column incorrectly.

        Requires the workbook to have been inserted already. Run augean first:
            augean --deployment deployment.json --db_credentials <creds> \\
                   --workbooks_path tests/test_data/workbooks/haemonc/
        """
        if not wb_path.exists():
            pytest.fail(
                f"Golden file has no matching workbook at '{wb_path}'. "
                "Either add the workbook or remove the orphaned golden file."
            )
        if specimen_id is None or batch_id is None:
            pytest.fail(
                f"Golden file '{wb_path.stem}.csv' does not follow the expected "
                "[instrument]-[specimen]-[batch]-... naming pattern."
            )
        golden_df = _load_golden(wb_path)
        db_df = _query_db(acceptance_engine, acceptance_schema, specimen_id, batch_id)

        if db_df.empty:
            pytest.skip(
                f"No rows found in {acceptance_schema}.inca for specimen_id={specimen_id} "
                f"batch_id={batch_id} — insert the workbook first"
            )

        # Columns to compare: in golden, not excluded, not DB-only
        compare_cols = [
            c for c in golden_df.columns
            if c not in _EXCLUDE and c not in _DB_ONLY
        ]

        assert len(db_df) == len(golden_df), (
            f"Row count mismatch: DB has {len(db_df)} rows, golden has {len(golden_df)}"
        )

        pd.testing.assert_frame_equal(
            _normalise(db_df, compare_cols),
            _normalise(golden_df, compare_cols),
            check_dtype=False,
            check_like=False,
            obj=f"db vs golden for {wb_path.name}",
        )
