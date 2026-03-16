import json
import logging
import re
from pathlib import Path

from hestia.errors import AmbiguousWorkbookFormatError, ConfigValidationError, WorkbookFormatUnknownError

log = logging.getLogger(__name__)

_REQUIRED_KEYS = {"format_name", "format_version", "fingerprint", "sheets"}


def load_configs(config_dir: Path) -> list[dict]:
    """Load and validate all JSON configs from config_dir."""
    configs = []
    for path in sorted(Path(config_dir).glob("*.json")):
        with open(path) as f:
            cfg = json.load(f)
        missing = _REQUIRED_KEYS - cfg.keys()
        if missing:
            raise ConfigValidationError(
                f"Config {path.name} is missing required keys: {missing}"
            )
        configs.append(cfg)
        log.debug("Loaded config: %s v%s", cfg["format_name"], cfg["format_version"])
    log.info("Loaded %d configs from %s", len(configs), config_dir)
    return configs


def get_config_for_workbook(workbook, configs: list[dict]) -> dict:
    """Evaluate fingerprints; return matching config or raise."""
    matches = [cfg for cfg in configs if _evaluate_fingerprint(workbook, cfg["fingerprint"])]
    if not matches:
        raise WorkbookFormatUnknownError(
            f"No config matched workbook with sheets: {workbook.sheetnames}"
        )
    if len(matches) > 1:
        names = [c["format_name"] for c in matches]
        raise AmbiguousWorkbookFormatError(
            f"Multiple configs matched workbook: {names}"
        )
    return matches[0]


def _evaluate_fingerprint(workbook, fingerprint: list[dict]) -> bool:
    """Return True only if all fingerprint checks pass."""
    for check in fingerprint:
        if not _evaluate_single_check(workbook, check):
            return False
    return True


def _evaluate_single_check(workbook, check: dict) -> bool:
    if "sheet_pattern" in check:
        pattern = check["sheet_pattern"]
        should_exist = check.get("exists", True)
        matched = any(re.match(pattern, s, re.IGNORECASE) for s in workbook.sheetnames)
        return matched == should_exist

    sheet_name = check.get("sheet", "")

    if "exists" in check and "cell" not in check and "has_columns" not in check:
        # Sheet existence check
        return (sheet_name in workbook.sheetnames) == check["exists"]

    if sheet_name not in workbook.sheetnames:
        return False

    sheet = workbook[sheet_name]

    if "has_columns" in check:
        headers = [cell.value for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
        return all(col in headers for col in check["has_columns"])

    if "cell" in check:
        raw = sheet[check["cell"]].value
        val = str(raw) if raw is not None else ""

        if "equals" in check:
            return val == str(check["equals"])

        if "matches_pattern" in check:
            return bool(re.match(check["matches_pattern"], val))

    return True
