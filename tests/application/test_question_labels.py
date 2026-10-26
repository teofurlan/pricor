from dataclasses import replace

from pricor.application.questions import option_groups, question_for
from pricor.ports.plan_advisor import ParameterId
from pricor.ports.question_model import Suggestion


def test_spanish_option_labels_use_a_decimal_comma_and_a_spaced_percent():
    vat = question_for(ParameterId.VAT_RATE)
    labels = {option.token: (option.label.en, option.label.es) for option in vat.options}
    assert labels["constant:10.5"] == ("10.5%", "10,5 %")
    assert labels["constant:21"] == ("21%", "21 %")
    units = question_for(ParameterId.UNITS_PER_PACK)
    assert {option.label.es for option in units.options} >= {"12", "24"}


def _groups(question):
    groups = option_groups(question)
    assert groups is not None
    return {token for token, group in groups.items() if group == "primary"}, {
        token for token, group in groups.items() if group == "more"
    }


def test_the_conversion_options_are_grouped_into_a_primary_few_and_the_rest():
    question = question_for(ParameterId.FX_CONVERSION)

    primary, more = _groups(question)

    assert primary == {"keep", "oficial:venta", "manual"}
    assert more == {option.token for option in question.options} - primary
    assert "blue:compra" in more and len(more) == 13


def test_the_configured_default_rate_is_the_primary_rate():
    question = replace(
        question_for(ParameterId.FX_CONVERSION),
        suggestion=Suggestion("blue:venta", 1.0, suggested_by="setting", calibrated=True),
    )

    primary, more = _groups(question)

    assert primary == {"keep", "blue:venta", "manual"}
    assert "oficial:venta" in more


def test_a_model_suggestion_does_not_change_which_options_are_primary():
    question = replace(
        question_for(ParameterId.FX_CONVERSION), suggestion=Suggestion("bolsa:compra", 0.8)
    )

    assert _groups(question)[0] == {"keep", "oficial:venta", "manual"}


def test_questions_without_a_long_list_have_no_groups():
    assert option_groups(question_for(ParameterId.PRICE_INCLUDES_VAT)) is None
    assert option_groups(question_for(ParameterId.CURRENCY)) is None
