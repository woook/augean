from dataclasses import dataclass


@dataclass
class ParseError:
    workbook: str
    stage: str  # "structural" | "field" | "cross_sheet" | "acgs"
    message: str

    def __str__(self) -> str:
        return f"[{self.stage}] {self.message}"


class WorkbookFormatUnknownError(Exception):
    pass


class AmbiguousWorkbookFormatError(Exception):
    pass


class ConfigValidationError(Exception):
    pass


class SchemaMismatchError(Exception):
    pass
