from pricor.application.questions import question_for
from pricor.ports.plan_advisor import ParameterId


def test_spanish_option_labels_use_a_decimal_comma_and_a_spaced_percent():
    vat = question_for(ParameterId.VAT_RATE)
    labels = {option.token: (option.label.en, option.label.es) for option in vat.options}
    assert labels["constant:10.5"] == ("10.5%", "10,5 %")
    assert labels["constant:21"] == ("21%", "21 %")
    units = question_for(ParameterId.UNITS_PER_PACK)
    assert {option.label.es for option in units.options} >= {"12", "24"}
