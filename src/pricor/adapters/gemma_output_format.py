"""Gemma output mapping proposals, validated against the closed source vocabulary."""

from collections.abc import Sequence

from pricor.adapters.gemma_classifier import ChatClient
from pricor.adapters.gemma_prompts import OUTPUT_FORMAT_SYSTEM, render_output_format_data_block
from pricor.adapters.model_output import (
    expect_index, expect_list, expect_object, expect_unit_interval, fail,
)
from pricor.ports.output_format import OutputProposal, TemplateColumn, validate_source

OUTPUT_FORMAT_SCHEMA = {
    "type": "object",
    "properties": {"columns": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "index": {"type": "integer"},
                "source": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["index", "source", "confidence"],
            "additionalProperties": False,
        },
    }},
    "required": ["columns"],
    "additionalProperties": False,
}


class GemmaOutputFormat:
    def __init__(self, client: ChatClient):
        self._client = client

    def propose(self, columns: Sequence[TemplateColumn]) -> tuple[OutputProposal, ...]:
        reply = self._client.chat_json(
            OUTPUT_FORMAT_SYSTEM, render_output_format_data_block(columns), OUTPUT_FORMAT_SCHEMA
        )
        root = expect_object(reply.content, "$", ["columns"])
        items = expect_list(root["columns"], "$.columns", min_items=len(columns), max_items=len(columns))
        indexes = {column.index for column in columns}
        proposals = {}
        for position, raw in enumerate(items):
            path = f"$.columns[{position}]"
            item = expect_object(raw, path, ["index", "source", "confidence"])
            index = expect_index(item["index"], f"{path}.index")
            if index not in indexes or index in proposals:
                raise fail(f"{path}.index", "must name a requested column exactly once")
            try:
                source = validate_source(item["source"])
            except ValueError as error:
                raise fail(f"{path}.source", str(error)) from error
            confidence = expect_unit_interval(item["confidence"], f"{path}.confidence")
            proposals[index] = OutputProposal(source, "gemma", confidence)
        return tuple(proposals[column.index] for column in columns)
