from datetime import UTC, datetime
from decimal import Decimal

import pytest

from pricor.domain.engine import execute_plan
from pricor.domain.fx import FxSnapshot, FxSnapshotMismatchError, FxSnapshotRequiredError
from pricor.domain.plan import parse_plan

HEADERS = ["Code", "Name", "Price", "Currency"]
QUOTED_AT = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)


def snapshot(
    rate="1535",
    rate_type="oficial",
    side="venta",
    source="dolarapi",
    from_currency="USD",
    quoted_at=QUOTED_AT,
    **fields,
):
    return FxSnapshot(
        Decimal(rate),
        rate_type,
        side,
        source,
        quoted_at,
        from_currency=from_currency,
        to_currency="ARS",
        **fields,
    )


def plan_dict(*, convert=True, rounding=2, **convert_fields) -> dict:
    steps = [
        {"op": "normalize_text", "column": {"index": 0, "header": "Code"}, "to": "supplier_code"},
        {"op": "normalize_text", "column": {"index": 1, "header": "Name"}, "to": "description"},
        {"op": "parse_number", "column": {"index": 2, "header": "Price"}, "decimal_sep": ".", "thousands_sep": ","},
        {
            "op": "map_values",
            "column": {"index": 3, "header": "Currency"},
            "table": {"$": "ARS", "u$s": "USD", "eur": "EUR"},
            "to": "currency",
        },
    ]
    if convert:
        steps.append(
            {"op": "convert_currency", "from": "USD", "to": "ARS", "rate_type": "oficial", **convert_fields}
        )
    return {
        "contract_version": "1",
        "engine_version": "0.1.0",
        "supplier": "Emilio",
        "steps": steps,
        "rounding": {"decimals": rounding, "mode": "half_up"},
    }


def run(rows, fx=None, **plan_fields):
    return execute_plan(parse_plan(plan_dict(**plan_fields)), HEADERS, rows, fx=fx)


def test_a_usd_row_gets_converted_fields_and_keeps_its_original_cost():
    result = run([["A1", "Antenna", "2.50", "u$s"]], snapshot("1535"))

    record = result.accepted[0].record
    assert record.unit_cost_net == Decimal("2.50")
    assert record.currency == "USD"
    assert record.unit_cost_net_converted == Decimal("3837.50")
    assert record.fx_rate == Decimal("1535")
    assert record.fx_source == "dolarapi:oficial:venta"
    assert record.fx_date == "2026-10-14"


def test_conversion_uses_the_unrounded_cost_and_rounds_once_at_the_end():
    # 1.004 USD rounds to 1.00; converting the rounded value would give 2.50, not 2.51.
    result = run([["A1", "Item", "1.004", "u$s"]], snapshot("2.5"))

    record = result.accepted[0].record
    assert record.unit_cost_net == Decimal("1.00")
    assert record.unit_cost_net_converted == Decimal("2.51")


def test_the_conversion_is_exact_decimal_math():
    result = run([["A1", "Item", "0.1", "u$s"]], snapshot("1535.10"), rounding=4)

    assert result.accepted[0].record.unit_cost_net_converted == Decimal("153.5100")


def test_the_converted_value_rounds_half_up_to_the_plan_decimals():
    result = run([["A1", "Item", "0.1", "u$s"], ["A2", "Item", "0.3", "u$s"]], snapshot("0.025"), rounding=3)

    first, second = (item.record.unit_cost_net_converted for item in result.accepted)
    assert first == Decimal("0.003")  # 0.0025 rounds half up
    assert second == Decimal("0.008")  # 0.0075 rounds half up


def test_rows_already_in_the_target_currency_are_not_converted():
    result = run([["A1", "Item", "100", "$"]], snapshot())

    record = result.accepted[0].record
    assert record.unit_cost_net == Decimal("100.00")
    assert record.unit_cost_net_converted is None
    assert record.fx_rate is None and record.fx_source is None and record.fx_date is None


def test_a_mixed_currency_list_converts_only_the_foreign_rows():
    rows = [["A1", "Item", "100", "$"], ["A2", "Item", "2", "u$s"], ["A3", "Item", "50", "$"]]

    result = run(rows, snapshot("1000"))

    assert [item.record.unit_cost_net_converted for item in result.accepted] == [
        None,
        Decimal("2000.00"),
        None,
    ]
    assert result.rejected == ()


def test_a_currency_that_is_neither_source_nor_target_is_rejected_with_a_reason():
    result = run([["A1", "Item", "10", "eur"]], snapshot())

    assert result.accepted == ()
    assert result.rejected[0].reasons == ("currency EUR cannot be converted: the plan converts USD to ARS",)


def test_the_trace_shows_the_converted_value_after_the_final_cost():
    result = run([["A1", "Item", "2.50", "u$s"]], snapshot("1535"))

    steps = [(item.step, item.value) for item in result.accepted[0].trace]
    assert steps[-2:] == [("rounding", Decimal("2.50")), ("convert_currency", Decimal("3837.50"))]


def test_a_plan_that_converts_needs_a_snapshot_and_never_guesses():
    with pytest.raises(FxSnapshotRequiredError):
        run([["A1", "Item", "2", "u$s"]], fx=None)


def test_a_plan_without_a_conversion_ignores_the_snapshot():
    result = run([["A1", "Item", "2", "u$s"]], snapshot(), convert=False)

    assert result.accepted[0].record.unit_cost_net_converted is None


@pytest.mark.parametrize(
    "wrong",
    [snapshot(rate_type="blue"), snapshot(side="compra"), snapshot(from_currency="EUR")],
    ids=["other rate type", "other side", "other currency pair"],
)
def test_a_snapshot_for_another_rate_or_pair_is_refused(wrong):
    with pytest.raises(FxSnapshotMismatchError):
        run([["A1", "Item", "2", "u$s"]], wrong)


def test_a_manual_snapshot_satisfies_any_rate_type():
    manual = snapshot("1400", rate_type="manual", source="manual")

    record = run([["A1", "Item", "2", "u$s"]], manual).accepted[0].record

    assert record.unit_cost_net_converted == Decimal("2800.00")
    assert record.fx_source == "manual"


def test_a_stale_snapshot_still_converts_and_keeps_its_own_date():
    old = snapshot("1500", quoted_at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC), stale=True)

    record = run([["A1", "Item", "2", "u$s"]], old).accepted[0].record

    assert record.fx_date == "2026-10-01"
    assert record.unit_cost_net_converted == Decimal("3000.00")
