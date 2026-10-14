"""Deterministic questions for the plan parameters the builder could not resolve.

Every unresolved parameter becomes a question with closed options, a stable id
(a `ParameterId`) and text in English and Spanish. A model may only *decorate*
a question: its hypothesis becomes a `Suggestion` (never applied) and its own
wording is kept as `model_phrasing`. The question exists whether or not a
model said anything.
"""

from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal

from pricor.application.errors import InvalidInputError
from pricor.domain.plan_builder import ColumnSource, ConstantSource, UnresolvedParameter
from pricor.ports.plan_advisor import (
    ParameterId,
    ParameterValue,
    PlanProposal,
    SeparatorChoice,
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
        questions.setdefault(
            parameter,
            Question(
                parameter,
                _TEXTS[parameter],
                _OPTIONS[parameter],
                item.reason,
                allows_custom=parameter in _CUSTOM,
            ),
        )
    return tuple(questions.values()), tuple(issues)


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
        case ColumnSource():
            return "column"
    return None


def accepted_value(question: Question, token: str) -> ParameterValue | None:
    """The typed value for `token` if the question accepts it, else `None`."""
    listed = any(option.token == token for option in question.options)
    if not listed and not (question.allows_custom and token.startswith("constant:")):
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
        suggestion = None
        hypothesis = hypotheses.get(question.id)
        if hypothesis is not None:
            token = value_token(question.id, hypothesis.value)
            if token is not None and accepted_value(question, token) is not None:
                suggestion = Suggestion(token, hypothesis.confidence, hypothesis.evidence)
        decorated.append(
            replace(question, suggestion=suggestion, model_phrasing=phrasings.get(question.id))
        )
    return tuple(decorated)
