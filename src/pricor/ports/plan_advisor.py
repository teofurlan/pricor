"""Port for proposing plan parameters and the questions that settle them.

A `PlanAdvisor` never produces a plan. It returns *hypotheses* about the
parameters in `ParameterId` (each with the evidence it relied on) and
*questions* whose options each map to one concrete parameter value. The
deterministic builder assembles the plan from confirmed parameters.

`confidence` is whatever the model reported: it is NOT a calibrated
probability and must not drive automatic decisions.
"""

import json
import re
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from pricor.domain.fx import DEFAULT_SIDE, MANUAL, MARKET_RATE_TYPES, SIDES
from pricor.domain.plan_builder import (
    ColumnSource,
    ConstantSource,
    FxChoice,
    KeepOriginalCurrency,
    PlanParameters,
)
from pricor.domain.parsing import lookup_key
from pricor.domain.profile import SheetProfile
from pricor.ports.column_classifier import ColumnClassification


class ParameterId(StrEnum):
    """Closed set of plan parameters a model may talk about."""

    PRICE_INCLUDES_VAT = "price_includes_vat"
    PRICE_IS_PER_PACK = "price_is_per_pack"
    VAT_RATE = "vat_rate"
    UNITS_PER_PACK = "units_per_pack"
    DISCOUNTS = "discounts"
    CURRENCY = "currency"
    NUMBER_FORMAT = "number_format"
    FX_CONVERSION = "fx_conversion"


@dataclass(frozen=True)
class SeparatorChoice:
    decimal_sep: str
    thousands_sep: str


ParameterValue = (
    bool | ColumnSource | ConstantSource | SeparatorChoice | FxChoice | KeepOriginalCurrency
)

CURRENCIES = ("ARS", "USD", "EUR")
CURRENCY_MAP_PREFIX = "map:"  # `map:{"$":"ARS","u$s":"USD"}`: what each value of a currency column means
_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?", re.ASCII)
_HUNDRED = Decimal(100)

# Value tokens a model may use, per parameter. `constant:N` carries a number.
VALUE_TOKENS: dict[ParameterId, str] = {
    ParameterId.PRICE_INCLUDES_VAT: "yes | no",
    ParameterId.PRICE_IS_PER_PACK: "yes | no",
    ParameterId.VAT_RATE: "column | constant:21 (the number is a percentage from 0 to 100)",
    ParameterId.UNITS_PER_PACK: "column | constant:12 (the number is a positive count)",
    ParameterId.DISCOUNTS: "column | none | constant:10+5 (chained percentages)",
    ParameterId.CURRENCY: " | ".join(CURRENCIES),
    ParameterId.NUMBER_FORMAT: "decimal_comma | decimal_point",
    ParameterId.FX_CONVERSION: (
        "keep | manual | <rate_type>:<side>, such as oficial:venta "
        "(rate types: oficial, blue, bolsa, contadoconliqui, mayorista, cripto, tarjeta; "
        "sides: compra, venta)"
    ),
}


def _percent(text: str) -> Decimal:
    if not _NUMBER.fullmatch(text) or Decimal(text) > _HUNDRED:
        raise ValueError(f"not a percentage between 0 and 100: {text!r}")
    return Decimal(text)


def _positive(text: str) -> Decimal:
    if not _NUMBER.fullmatch(text) or Decimal(text) == 0:
        raise ValueError(f"not a positive number: {text!r}")
    return Decimal(text)


def currency_map_token(table: dict[str, str]) -> str:
    """The canonical answer token for a currency map (stable key order, no padding)."""
    return CURRENCY_MAP_PREFIX + json.dumps(
        table, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )


def _currency_map(text: str) -> ColumnSource:
    try:
        raw = json.loads(text)
    except ValueError:
        raise ValueError("a currency map must be a JSON object") from None
    if not isinstance(raw, dict) or not raw:
        raise ValueError("a currency map must be a non-empty JSON object")
    table: dict[str, str] = {}
    for key, code in raw.items():
        if not lookup_key(key) or code not in CURRENCIES:
            raise ValueError(f"a currency map needs non-empty values and codes in {CURRENCIES}")
        if table.setdefault(lookup_key(key), code) != code:
            raise ValueError(f"the currency map maps {key!r} to two codes")
    return ColumnSource(table)


def _constant(token: str) -> str | None:
    return token.removeprefix("constant:") if token.startswith("constant:") else None


def parse_value(parameter: ParameterId, token: str) -> ParameterValue:
    """Turn a model-supplied value token into a typed value, or raise `ValueError`."""
    constant = _constant(token)
    match parameter:
        case ParameterId.PRICE_INCLUDES_VAT | ParameterId.PRICE_IS_PER_PACK:
            if token in ("yes", "no"):
                return token == "yes"
        case ParameterId.VAT_RATE:
            if token == "column":
                return ColumnSource()
            if constant is not None:
                return ConstantSource(_percent(constant))
        case ParameterId.UNITS_PER_PACK:
            if token == "column":
                return ColumnSource()
            if constant is not None:
                return ConstantSource(_positive(constant))
        case ParameterId.DISCOUNTS:
            if token == "column":
                return ColumnSource()
            if token == "none":
                return ConstantSource(())
            if constant is not None:
                return ConstantSource(tuple(_percent(part) for part in constant.split("+")))
        case ParameterId.CURRENCY:
            if token in CURRENCIES:
                return ConstantSource(token)
            if token.startswith(CURRENCY_MAP_PREFIX):
                return _currency_map(token.removeprefix(CURRENCY_MAP_PREFIX))
        case ParameterId.FX_CONVERSION:
            if token == "keep":
                return KeepOriginalCurrency()
            if token == MANUAL:
                return FxChoice(MANUAL, DEFAULT_SIDE)
            rate_type, _, side = token.partition(":")
            if rate_type in MARKET_RATE_TYPES and side in SIDES:
                return FxChoice(rate_type, side)
        case ParameterId.NUMBER_FORMAT:
            if token == "decimal_comma":
                return SeparatorChoice(",", ".")
            if token == "decimal_point":
                return SeparatorChoice(".", ",")
    raise ValueError(f"invalid value {token!r} for parameter '{parameter.value}'")


def with_answer(
    parameters: PlanParameters, parameter: ParameterId, value: ParameterValue
) -> PlanParameters:
    """Return `parameters` with one confirmed value filled in."""
    match parameter, value:
        case ParameterId.PRICE_INCLUDES_VAT, bool():
            return replace(parameters, price_includes_vat=value)
        case ParameterId.PRICE_IS_PER_PACK, bool():
            return replace(parameters, price_is_per_pack=value)
        case ParameterId.VAT_RATE, ColumnSource() | ConstantSource():
            return replace(parameters, vat_source=value)
        case ParameterId.UNITS_PER_PACK, ColumnSource() | ConstantSource():
            return replace(parameters, units_source=value)
        case ParameterId.DISCOUNTS, ColumnSource() | ConstantSource():
            return replace(parameters, discounts=value)
        case ParameterId.CURRENCY, ColumnSource() | ConstantSource():
            return replace(parameters, currency=value)
        case ParameterId.FX_CONVERSION, FxChoice() | KeepOriginalCurrency():
            return replace(parameters, fx=value)
        case ParameterId.NUMBER_FORMAT, SeparatorChoice():
            return replace(
                parameters, decimal_sep=value.decimal_sep, thousands_sep=value.thousands_sep
            )
    raise ValueError(f"a {type(value).__name__} value does not fit parameter '{parameter.value}'")


@dataclass(frozen=True)
class Evidence:
    """A column (and a sample value from it) the model relied on."""

    column_index: int
    sample: str


@dataclass(frozen=True)
class ParameterHypothesis:
    parameter: ParameterId
    value: ParameterValue
    confidence: float  # as reported by the model; not calibrated
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class QuestionOption:
    label: str
    value: ParameterValue


@dataclass(frozen=True)
class PlanQuestion:
    id: ParameterId
    text: str
    options: tuple[QuestionOption, ...]
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class PlanProposal:
    hypotheses: tuple[ParameterHypothesis, ...]
    questions: tuple[PlanQuestion, ...]
    latency_seconds: float | None = None


class PlanAdvisor(Protocol):
    def propose(
        self,
        sheet: SheetProfile,
        classifications: list[ColumnClassification],
        memory_context: list[str] | None = None,
        language: str = "en",
    ) -> PlanProposal:
        """Propose parameter hypotheses and questions; `language` is for user-facing text.

        `memory_context` is reserved for retrieved memories and is currently unused.
        Raises a `ModelError` subclass when the model cannot be trusted.
        """
        ...
