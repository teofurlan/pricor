import pytest

from pricor.domain.plan import Operation, PlanValidationError, parse_plan, plan_to_dict

from .golden import golden_plan_dict


def convert_step(**overrides) -> dict:
    step = {"op": "convert_currency", "from": "USD", "to": "ARS", "rate_type": "oficial"}
    return {**step, **overrides}


def plan_with(step: dict | None = None, position: int | None = None) -> dict:
    data = golden_plan_dict()
    if step is not None:
        if position is None:
            data["steps"].append(step)
        else:
            data["steps"].insert(position, step)
    return data


def problems_for(data) -> list[str]:
    with pytest.raises(PlanValidationError) as excinfo:
        parse_plan(data)
    return excinfo.value.problems


def parameters(step) -> tuple:
    return (step.op.value, step.from_currency, step.to_currency, step.rate_type, step.side)


def test_convert_currency_is_part_of_the_closed_catalog():
    assert "convert_currency" in {op.value for op in Operation}


def test_a_conversion_parses_with_venta_as_the_default_side():
    plan = parse_plan(plan_with(convert_step()))

    assert parameters(plan.steps[-1]) == ("convert_currency", "USD", "ARS", "oficial", "venta")


def test_the_side_can_be_compra():
    plan = parse_plan(plan_with(convert_step(side="compra", rate_type="blue")))

    assert parameters(plan.steps[-1]) == ("convert_currency", "USD", "ARS", "blue", "compra")


@pytest.mark.parametrize(
    "rate_type", ["oficial", "blue", "bolsa", "contadoconliqui", "mayorista", "cripto", "tarjeta", "manual"]
)
def test_every_catalog_rate_type_is_accepted(rate_type):
    parse_plan(plan_with(convert_step(rate_type=rate_type)))


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"rate_type": "paralelo"}, "rate_type"),
        ({"rate_type": ["oficial"]}, "rate_type"),
        ({"side": "medio"}, "side"),
        ({"from": "dolar"}, "from"),
        ({"to": "ars"}, "to"),
        ({"to": "USD"}, "differ"),
        ({"rate": "1500"}, "unexpected parameter 'rate'"),
    ],
)
def test_invalid_conversions_are_rejected(override, fragment):
    problems = problems_for(plan_with(convert_step(**override)))

    assert any(fragment in problem for problem in problems)


def test_a_conversion_must_come_after_per_unit():
    data = plan_with(convert_step(), position=3)

    assert any("order" in problem for problem in problems_for(data))


def test_a_conversion_runs_after_every_other_cost_step():
    assert parse_plan(plan_with(convert_step())).steps[-1].op.value == "convert_currency"


def test_only_one_conversion_is_allowed():
    data = plan_with(convert_step())
    data["steps"].append(convert_step(rate_type="blue"))

    assert any("more than once" in problem for problem in problems_for(data))


def test_the_plan_stores_the_rate_type_but_never_a_rate():
    plan = parse_plan(plan_with(convert_step(side="compra")))

    stored = plan_to_dict(plan)["steps"][-1]
    assert stored == {
        "op": "convert_currency",
        "from": "USD",
        "to": "ARS",
        "rate_type": "oficial",
        "side": "compra",
    }
    assert parse_plan(plan_to_dict(plan)) == plan
