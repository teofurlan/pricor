"""In-memory fakes for the first-import use case (no files, no network)."""

from pathlib import Path

from pricor.domain.roles import ColumnRole
from pricor.ports.column_classifier import ColumnClassification
from pricor.ports.spreadsheet import Sheet


class FakeReader:
    def __init__(self, rows, name="Hoja1"):
        self.rows = tuple(tuple(row) for row in rows)
        self.name = name
        self.calls = []

    def sheet_names(self, path: Path):
        return [self.name]

    def read_sheet(self, path: Path, sheet=None):
        self.calls.append((path, sheet))
        return Sheet(self.name, self.rows)


class FakeClassifier:
    """Answers from a header -> (role, score) table; unknown headers get (IGNORE, 0.1)."""

    def __init__(self, table=None, error=None):
        self.table = table or {}
        self.error = error
        self.seen_indexes = []

    def classify_column(self, column, sheet=None):
        raise NotImplementedError

    def classify_sheet(self, sheet):
        self.seen_indexes.append([column.index for column in sheet.columns])
        if self.error:
            raise self.error
        results = []
        for column in sheet.columns:
            role, score = self.table.get(column.raw_header, (ColumnRole.IGNORE, 0.1))
            results.append(
                ColumnClassification(
                    index=column.index,
                    header=column.raw_header,
                    role=role,
                    score=score,
                    rationale=f"fake:{column.raw_header or 'headerless'}",
                )
            )
        return results


class FakeAdvisor:
    def __init__(self, proposal=None, error=None):
        self.proposal = proposal
        self.error = error
        self.calls = 0

    def propose(self, sheet, classifications, memory_context=None, language="en"):
        self.calls += 1
        if self.error:
            raise self.error
        return self.proposal
