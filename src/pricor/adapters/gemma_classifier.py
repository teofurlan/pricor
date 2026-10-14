"""`ColumnClassifier` implemented with Gemma through Ollama (prompt-only).

The model picks one role per column from the closed `ColumnRole` set and
reports its own confidence. Ollama gives no per-role distribution under
structured output, so `scores` holds only the chosen role's self-reported
confidence, which is not calibrated. `latency_seconds` is the duration of the
model call that produced the classification (shared by every column of a sheet).
"""

from typing import Any, Protocol

from pricor.domain.profile import ColumnProfile, SheetProfile
from pricor.ports.column_classifier import ColumnClassification, ColumnRole

from .gemma_prompts import CLASSIFIER_SYSTEM, render_data_block
from .model_output import (
    expect_choice,
    expect_index,
    expect_list,
    expect_object,
    expect_text,
    expect_unit_interval,
    fail,
)
from .ollama_client import ChatReply

_ROLES = [role.value for role in ColumnRole]
_ITEM_KEYS = ("index", "role", "confidence", "rationale")

CLASSIFIER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "columns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "role": {"type": "string", "enum": _ROLES},
                    "confidence": {"type": "number"},
                    "rationale": {"type": "string"},
                },
                "required": list(_ITEM_KEYS),
            },
        }
    },
    "required": ["columns"],
}


class ChatClient(Protocol):
    def chat_json(self, system: str, user: str, schema: dict[str, Any]) -> ChatReply: ...


class GemmaColumnClassifier:
    def __init__(self, client: ChatClient):
        self._client = client

    def classify_column(
        self, column: ColumnProfile, sheet: SheetProfile | None = None
    ) -> ColumnClassification:
        neighbours = (
            [other.raw_header for other in sheet.columns if other.index != column.index]
            if sheet
            else None
        )
        (result,) = self._classify([column], neighbours)
        return result

    def classify_sheet(self, sheet: SheetProfile) -> list[ColumnClassification]:
        return self._classify(list(sheet.columns), None)

    def _classify(
        self, columns: list[ColumnProfile], neighbours: list[str] | None
    ) -> list[ColumnClassification]:
        if not columns:
            return []
        user = "Classify every column listed in the data block below.\n" + render_data_block(
            columns, neighbour_headers=neighbours
        )
        reply = self._client.chat_json(CLASSIFIER_SYSTEM, user, CLASSIFIER_SCHEMA)
        return self._validate(reply, columns)

    @staticmethod
    def _validate(reply: ChatReply, columns: list[ColumnProfile]) -> list[ColumnClassification]:
        root = expect_object(reply.content, "$", ["columns"])
        items = expect_list(root["columns"], "$.columns", min_items=len(columns), max_items=500)
        by_index = {column.index: column for column in columns}
        results: dict[int, ColumnClassification] = {}
        for position, raw in enumerate(items):
            path = f"$.columns[{position}]"
            item = expect_object(raw, path, _ITEM_KEYS)
            index = expect_index(item["index"], f"{path}.index")
            if index not in by_index:
                raise fail(f"{path}.index", f"column {index} was not part of the request")
            if index in results:
                raise fail(f"{path}.index", f"column {index} appears more than once")
            role = ColumnRole(expect_choice(item["role"], f"{path}.role", _ROLES))
            confidence = expect_unit_interval(item["confidence"], f"{path}.confidence")
            rationale = expect_text(item["rationale"], f"{path}.rationale", allow_empty=True)
            results[index] = ColumnClassification(
                index=index,
                header=by_index[index].raw_header,
                role=role,
                score=confidence,
                rationale=rationale,
                scores={role: confidence},
                latency_seconds=reply.latency_seconds,
            )
        if len(results) != len(columns):
            raise fail("$.columns", "not every requested column was classified")
        return [results[column.index] for column in columns]
