"""`PlanAdvisor` implemented with Gemma through Ollama (prompt-only).

Gemma proposes parameter hypotheses and questions; it never writes the plan.
Its reply is validated strictly against the schema and the closed vocabularies
(`ParameterId`, value tokens): an unknown parameter, option value or key makes
the whole proposal fail with `ModelSchemaError`. Nothing is guessed or repaired.
"""

from typing import Any

from pricor.domain.profile import SheetProfile
from pricor.ports.column_classifier import ColumnClassification
from pricor.ports.plan_advisor import (
    VALUE_TOKENS,
    Evidence,
    ParameterHypothesis,
    ParameterId,
    PlanProposal,
    PlanQuestion,
    QuestionOption,
    parse_value,
)

from .gemma_classifier import ChatClient
from .gemma_prompts import UNTRUSTED_RULES, render_data_block
from .model_output import (
    expect_index,
    expect_list,
    expect_object,
    expect_text,
    expect_unit_interval,
    fail,
)

LANGUAGES = {"en": "English", "es": "Spanish (neutral, professional)"}
_IDS = [parameter.value for parameter in ParameterId]
_MAX_OPTIONS = 6
_MAX_EVIDENCE = 5

_EVIDENCE_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"column_index": {"type": "integer"}, "sample": {"type": "string"}},
        "required": ["column_index", "sample"],
    },
}

ADVISOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "hypotheses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "parameter": {"type": "string", "enum": _IDS},
                    "value": {"type": "string"},
                    "confidence": {"type": "number"},
                    "evidence": _EVIDENCE_SCHEMA,
                    "memory_refs": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 1},
                    },
                },
                "required": ["parameter", "value", "confidence", "evidence"],
            },
        },
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "enum": _IDS},
                    "text": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "value": {"type": "string"},
                            },
                            "required": ["label", "value"],
                        },
                    },
                    "evidence": _EVIDENCE_SCHEMA,
                },
                "required": ["id", "text", "options", "evidence"],
            },
        },
    },
    "required": ["hypotheses", "questions"],
}


def advisor_system(language: str) -> str:
    return (
        "You help a store owner import a supplier price list. Column roles were already "
        "assigned. Your job is to propose values for the plan parameters below and to ask "
        "the user about the ones that are unknown or ambiguous. You never write a plan, "
        "formulas or code: a deterministic program builds the plan from confirmed parameters.\n"
        "Parameters (closed set) and the value tokens allowed for each:\n"
        + "\n".join(f"- {pid.value}: {VALUE_TOKENS[pid]}" for pid in ParameterId)
        + "\nRules:\n"
        "- A hypothesis is your best guess for one parameter, with the columns and sample "
        "values that support it and your own confidence between 0 and 1.\n"
        "- Ask a question (2 to 6 options, each with one allowed value token) only when the "
        "data does not settle a parameter, for example whether prices include VAT or whether "
        "a price is per pack. Never invent a value without evidence.\n"
        "- Whether a price includes VAT, whether it is per pack and its currency cannot be "
        "inferred from the numbers alone: ask about them unless a header or a value states "
        "the answer explicitly (a units-per-pack column makes the per-pack question "
        "relevant).\n"
        "- Do not ask about parameters that do not apply to this sheet.\n"
        "- Never hypothesize fx_conversion: whether to convert currency, and with which "
        "exchange rate, is the user's own decision.\n"
        "- When a hypothesis relies on an earlier-import note, cite its shown 1-based "
        "number in memory_refs; never cite a number not shown.\n"
        f"- Write question text and option labels in {LANGUAGES[language]}.\n"
        + UNTRUSTED_RULES
    )


def _evidence(raw: Any, path: str, valid_columns: set[int]) -> tuple[Evidence, ...]:
    items = expect_list(raw, path, max_items=_MAX_EVIDENCE)
    result = []
    for position, item in enumerate(items):
        item_path = f"{path}[{position}]"
        obj = expect_object(item, item_path, ("column_index", "sample"))
        index = expect_index(obj["column_index"], f"{item_path}.column_index")
        if index not in valid_columns:
            raise fail(f"{item_path}.column_index", f"column {index} does not exist")
        sample = expect_text(obj["sample"], f"{item_path}.sample", allow_empty=True)
        result.append(Evidence(index, sample))
    return tuple(result)


def _parameter(raw: Any, path: str) -> ParameterId:
    if not isinstance(raw, str) or raw not in _IDS:
        raise fail(path, f"must be one of: {', '.join(_IDS)}")
    return ParameterId(raw)


def _value(parameter: ParameterId, raw: Any, path: str):
    if not isinstance(raw, str):
        raise fail(path, "must be a string token")
    try:
        return parse_value(parameter, raw)
    except ValueError as error:
        raise fail(path, str(error)) from error


def _memory_refs(raw: Any, path: str, memory_count: int) -> tuple[int, ...]:
    items = expect_list(raw, path, max_items=memory_count)
    refs = []
    for position, item in enumerate(items):
        item_path = f"{path}[{position}]"
        if isinstance(item, bool) or not isinstance(item, int) or not 1 <= item <= memory_count:
            raise fail(item_path, f"must name a shown memory from 1 to {memory_count}")
        refs.append(item)
    return tuple(refs)


def _hypotheses(
    raw: Any, valid_columns: set[int], memory_count: int
) -> tuple[ParameterHypothesis, ...]:
    items = expect_list(raw, "$.hypotheses", max_items=len(_IDS))
    result: dict[ParameterId, ParameterHypothesis] = {}
    for position, item in enumerate(items):
        path = f"$.hypotheses[{position}]"
        keys = ("parameter", "value", "confidence", "evidence")
        if isinstance(item, dict) and "memory_refs" in item:
            keys = (*keys, "memory_refs")
        obj = expect_object(item, path, keys)
        parameter = _parameter(obj["parameter"], f"{path}.parameter")
        if parameter in result:
            raise fail(path, f"more than one hypothesis for '{parameter.value}'")
        result[parameter] = ParameterHypothesis(
            parameter,
            _value(parameter, obj["value"], f"{path}.value"),
            expect_unit_interval(obj["confidence"], f"{path}.confidence"),
            _evidence(obj["evidence"], f"{path}.evidence", valid_columns),
            _memory_refs(obj.get("memory_refs", []), f"{path}.memory_refs", memory_count),
        )
    return tuple(result.values())


def _questions(raw: Any, valid_columns: set[int]) -> tuple[PlanQuestion, ...]:
    items = expect_list(raw, "$.questions", max_items=len(_IDS))
    result: dict[ParameterId, PlanQuestion] = {}
    for position, item in enumerate(items):
        path = f"$.questions[{position}]"
        obj = expect_object(item, path, ("id", "text", "options", "evidence"))
        parameter = _parameter(obj["id"], f"{path}.id")
        if parameter in result:
            raise fail(path, f"more than one question for '{parameter.value}'")
        raw_options = expect_list(
            obj["options"], f"{path}.options", min_items=2, max_items=_MAX_OPTIONS
        )
        options: list[QuestionOption] = []
        tokens: set[str] = set()
        for option_position, raw_option in enumerate(raw_options):
            option_path = f"{path}.options[{option_position}]"
            option = expect_object(raw_option, option_path, ("label", "value"))
            label = expect_text(option["label"], f"{option_path}.label")
            value = _value(parameter, option["value"], f"{option_path}.value")
            if option["value"] in tokens:
                raise fail(option_path, f"duplicate option value {option['value']!r}")
            tokens.add(option["value"])
            options.append(QuestionOption(label, value))
        result[parameter] = PlanQuestion(
            parameter,
            expect_text(obj["text"], f"{path}.text"),
            tuple(options),
            _evidence(obj["evidence"], f"{path}.evidence", valid_columns),
        )
    return tuple(result.values())


class GemmaPlanAdvisor:
    def __init__(self, client: ChatClient):
        self._client = client

    def propose(
        self,
        sheet: SheetProfile,
        classifications: list[ColumnClassification],
        memory_context: list[str] | None = None,  # reserved; not sent to the model yet
        language: str = "en",
    ) -> PlanProposal:
        if language not in LANGUAGES:
            raise ValueError(f"unsupported language {language!r}; use one of {sorted(LANGUAGES)}")
        user = (
            "Propose parameter hypotheses and questions for the sheet described in the data "
            "block below.\n"
            + render_data_block(sheet.columns, classifications, memory_context=memory_context)
        )
        reply = self._client.chat_json(advisor_system(language), user, ADVISOR_SCHEMA)
        root = expect_object(reply.content, "$", ("hypotheses", "questions"))
        valid_columns = {column.index for column in sheet.columns}
        return PlanProposal(
            hypotheses=_hypotheses(root["hypotheses"], valid_columns, len(memory_context or ())),
            questions=_questions(root["questions"], valid_columns),
            latency_seconds=reply.latency_seconds,
        )
