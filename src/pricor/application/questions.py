"""Deterministic questions for the plan parameters the builder could not resolve.

Every unresolved parameter becomes a question with closed options, a stable id
(a `ParameterId`) and text in English and Spanish. A model may only *decorate*
a question: its hypothesis becomes a `Suggestion` (never applied) and its own
wording is kept as `model_phrasing`. The question exists whether or not a
model said anything.
"""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import Decimal

from pricor.application.errors import InvalidInputError
from pricor.domain.fx import MANUAL, MARKET_RATE_TYPES, SIDES
from pricor.domain.plan_builder import (
    ColumnSource,
    ConstantSource,
    FxChoice,
    KeepOriginalCurrency,
    UnresolvedParameter,
)
from pricor.ports.plan_advisor import (
    CURRENCY_MAP_PREFIX,
    ParameterId,
    ParameterValue,
    PlanProposal,
    SeparatorChoice,
    currency_map_token,
    parse_value,
)
from pricor.ports.question_model import LocalizedText, Option, Question, Suggestion


def _text(en: str, es: str) -> LocalizedText:
    return LocalizedText(en, es)


def _yes_no(yes: LocalizedText, no: LocalizedText) -> tuple[Option, ...]:
    return Option("yes", yes), Option("no", no)


def _constants(values: Sequence[str], suffix: str = "") -> tuple[Option, ...]:
    return tuple(
        Option(f"constant:{value}", _text(f"{value}{suffix}", f"{value}{suffix}")) for value in values
    )


_RATE_NAMES = {
    "oficial": _text("Official", "Oficial"),
    "blue": _text("Blue", "Blue"),
    "bolsa": _text("MEP (bolsa)", "MEP (bolsa)"),
    "contadoconliqui": _text("CCL (contado con liqui)", "CCL (contado con liqui)"),
    "mayorista": _text("Wholesale (mayorista)", "Mayorista"),
    "cripto": _text("Crypto", "Cripto"),
    "tarjeta": _text("Card (tarjeta)", "Tarjeta"),
}
_SIDE_NAMES = {
    "venta": _text("sell rate (venta)", "venta"),
    "compra": _text("buy rate (compra)", "compra"),
}


def _fx_options() -> tuple[Option, ...]:
    keep = Option(
        "keep",
        _text(
            "Keep the original currency (no conversion)",
            "Mantener la moneda original (sin conversión)",
        ),
    )
    rates = tuple(
        Option(
            f"{rate}:{side}",
            _text(
                f"Convert to ARS: {_RATE_NAMES[rate].en}, {_SIDE_NAMES[side].en}",
                f"Convertir a ARS: {_RATE_NAMES[rate].es}, {_SIDE_NAMES[side].es}",
            ),
        )
        for rate in MARKET_RATE_TYPES
        for side in SIDES
    )
    manual = Option(
        MANUAL,
        _text("Convert to ARS with a rate I type in", "Convertir a ARS con una cotización que escribo yo"),
    )
    return (keep, *rates, manual)


_TEXTS: dict[ParameterId, LocalizedText] = {
    ParameterId.NUMBER_FORMAT: _text(
        "How are decimals written in the price column?",
        "¿Cómo se escriben los decimales en la columna de precios?",
    ),
    ParameterId.PRICE_INCLUDES_VAT: _text(
        "Do the prices in this list already include VAT?",
        "¿Los precios de esta lista ya incluyen IVA?",
    ),
    ParameterId.VAT_RATE: _text(
        "Which VAT rate is included in the prices?",
        "¿Qué alícuota de IVA incluyen los precios?",
    ),
    ParameterId.PRICE_IS_PER_PACK: _text(
        "Is the price for a whole pack or for a single unit?",
        "¿El precio es por bulto completo o por unidad?",
    ),
    ParameterId.UNITS_PER_PACK: _text(
        "How many units does each pack contain?",
        "¿Cuántas unidades trae cada bulto?",
    ),
    ParameterId.CURRENCY: _text(
        "In which currency are the prices?",
        "¿En qué moneda están los precios?",
    ),
    ParameterId.FX_CONVERSION: _text(
        "Some prices are in a foreign currency. Convert them to ARS, and with which exchange rate?",
        "Hay precios en moneda extranjera. ¿Se convierten a ARS y con qué cotización?",
    ),
}

_OPTIONS: dict[ParameterId, tuple[Option, ...]] = {
    ParameterId.NUMBER_FORMAT: (
        Option("decimal_comma", _text("Decimal comma (1.234,56)", "Coma decimal (1.234,56)")),
        Option("decimal_point", _text("Decimal point (1,234.56)", "Punto decimal (1,234.56)")),
    ),
    ParameterId.PRICE_INCLUDES_VAT: _yes_no(
        _text("Yes, VAT is included", "Sí, incluyen IVA"),
        _text("No, prices are net of VAT", "No, son precios sin IVA"),
    ),
    ParameterId.VAT_RATE: _constants(("21", "10.5"), "%"),
    ParameterId.PRICE_IS_PER_PACK: _yes_no(
        _text("Per pack: divide by the units in the pack", "Por bulto: dividir por las unidades"),
        _text("Per unit: use the price as it is", "Por unidad: usar el precio tal cual"),
    ),
    ParameterId.UNITS_PER_PACK: _constants(("2", "6", "10", "12", "24", "50", "100")),
    ParameterId.CURRENCY: (
        Option("ARS", _text("Argentine pesos (ARS)", "Pesos argentinos (ARS)")),
        Option("USD", _text("US dollars (USD)", "Dólares estadounidenses (USD)")),
        Option("EUR", _text("Euros (EUR)", "Euros (EUR)")),
    ),
    ParameterId.FX_CONVERSION: _fx_options(),
}

_CUSTOM = frozenset({ParameterId.VAT_RATE, ParameterId.UNITS_PER_PACK})


def build_questions(
    unresolved: Sequence[UnresolvedParameter],
) -> tuple[tuple[Question, ...], tuple[str, ...]]:
    """Split the builder's unresolved parameters into questions and role issues.

    A parameter that is not a plan parameter (a missing or duplicated column)
    cannot be answered with a closed option: it is returned as an issue that
    the user fixes by changing column roles.
    """
    questions: dict[ParameterId, Question] = {}
    issues: list[str] = []
    for item in unresolved:
        try:
            parameter = ParameterId(item.parameter)
        except ValueError:
            issues.append(item.reason)
            continue
        if parameter not in _OPTIONS:
            issues.append(item.reason)
            continue
        question = Question(
            parameter,
            _TEXTS[parameter],
            _OPTIONS[parameter],
            item.reason,
            allows_custom=parameter in _CUSTOM,
        )
        if item.detected_map:
            question = _with_detected_map(question, item.detected_map)
        questions.setdefault(parameter, question)
    return tuple(questions.values()), tuple(issues)


def _with_detected_map(question: Question, detected: Mapping[str, str]) -> Question:
    """Offer what the column's values read as: a labeled option, suggested but never applied."""
    token = currency_map_token(dict(detected))
    listing = ", ".join(f"`{key}` → {code}" for key, code in detected.items())
    option = Option(token, _text(f"Detected: {listing}", f"Detectado: {listing}"))
    return replace(
        question,
        options=(option, *question.options),
        suggestion=Suggestion(token, 1.0, suggested_by="detected", calibrated=True),
    )


def question_for(parameter: ParameterId) -> Question | None:
    """The undecorated question for a plan parameter, if it can be asked at all."""
    if parameter not in _OPTIONS:
        return None
    return Question(
        parameter,
        _TEXTS[parameter],
        _OPTIONS[parameter],
        "",
        allows_custom=parameter in _CUSTOM,
    )


def value_token(parameter: ParameterId, value: ParameterValue) -> str | None:
    """Inverse of `parse_value`; `None` when the value has no token form."""
    match value:
        case bool():
            return "yes" if value else "no"
        case SeparatorChoice(decimal_sep=",", thousands_sep="."):
            return "decimal_comma"
        case SeparatorChoice(decimal_sep=".", thousands_sep=","):
            return "decimal_point"
        case ConstantSource(value=Decimal() as number):
            return f"constant:{format(number.normalize(), 'f')}"
        case ConstantSource(value=str() as text):
            return text
        case ColumnSource(value_map=table) if parameter is ParameterId.CURRENCY and table:
            return currency_map_token({key: str(code) for key, code in table.items()})
        case ColumnSource():
            return "column"
        case KeepOriginalCurrency():
            return "keep"
        case FxChoice(rate_type=rate_type) if rate_type == MANUAL:
            return MANUAL
        case FxChoice(rate_type=rate_type, side=side):
            return f"{rate_type}:{side}"
    return None


def accepted_value(question: Question, token: str) -> ParameterValue | None:
    """The typed value for `token` if the question accepts it, else `None`."""
    listed = any(option.token == token for option in question.options)
    custom = question.allows_custom and token.startswith("constant:")
    edited_map = question.id is ParameterId.CURRENCY and token.startswith(CURRENCY_MAP_PREFIX)
    if not (listed or custom or edited_map):
        return None
    try:
        return parse_value(question.id, token)
    except ValueError:
        return None


def parse_answer(question: Question, token: str) -> ParameterValue:
    value = accepted_value(question, token)
    if value is None:
        allowed = ", ".join(option.token for option in question.options)
        extra = " or a constant such as constant:<number>" if question.allows_custom else ""
        raise InvalidInputError(
            f"'{token}' is not an option for '{question.id.value}'; use one of: {allowed}{extra}"
        )
    return value


def decorate(questions: Sequence[Question], proposal: PlanProposal | None) -> tuple[Question, ...]:
    """Attach model suggestions and phrasing; never adds, removes or reorders options."""
    if proposal is None:
        return tuple(questions)
    hypotheses = {item.parameter: item for item in proposal.hypotheses}
    phrasings = {item.id: item.text for item in proposal.questions}
    decorated = []
    for question in questions:
        suggestion = question.suggestion  # a deterministic suggestion outranks a model's
        hypothesis = hypotheses.get(question.id)
        if suggestion is None and hypothesis is not None:
            token = value_token(question.id, hypothesis.value)
            if token is not None and accepted_value(question, token) is not None:
                memory_ids = [
                    proposal.memory_ids[reference - 1]
                    for reference in hypothesis.memory_refs
                ]
                suggestion = Suggestion(
                    token,
                    hypothesis.confidence,
                    hypothesis.evidence,
                    memory_ids=memory_ids,
                )
        decorated.append(
            replace(question, suggestion=suggestion, model_phrasing=phrasings.get(question.id))
        )
    return tuple(decorated)
