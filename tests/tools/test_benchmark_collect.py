from pricor.domain.profile import profile_sheet
from pricor.domain.roles import ColumnRole
from pricor.ports.column_classifier import ColumnClassification
from pricor.ports.model_errors import ModelSchemaError
from tests.application.fakes import FakeClassifier
from tools.benchmark.collect import collect_held_out, collect_validation
from tools.benchmark.datasets import SheetCase
from tools.laya.dataset import Example

ROWS = (("Codigo", "Detalle", "Costo"), ("A1", "Tornillo", "10,5"), ("A2", "Tuerca", "20,0"))
TABLE = {
    "Codigo": (ColumnRole.CODE, 0.9),
    "Detalle": (ColumnRole.DESCRIPTION, 0.8),
    "Costo": (ColumnRole.COST_PRICE, 0.7),
}


def examples():
    profile = profile_sheet(ROWS)
    return [
        Example("s", ColumnRole.CODE, "real", "acme-1", "Codigo", profile.columns[0]),
        Example("s", ColumnRole.COST_PRICE, "synthetic", "synthetic", "Costo", profile.columns[2]),
        Example("s", ColumnRole.DESCRIPTION, "real", "acme-1", "Detalle", profile.columns[1]),
    ]


def test_validation_answers_come_back_in_the_order_of_the_examples():
    records = collect_validation(FakeClassifier(TABLE), examples(), chunk_size=2, seed=0)

    assert [(r.header, r.expected, r.predicted, r.score, r.origin) for r in records] == [
        ("Codigo", "code", "code", 0.9, "real"),
        ("Costo", "cost_price", "cost_price", 0.7, "synthetic"),
        ("Detalle", "description", "description", 0.8, "real"),
    ]
    assert not any(r.failed for r in records)


def test_held_out_answers_are_taken_from_the_whole_sheet_call():
    case = SheetCase("acme-1", "S", profile_sheet(ROWS), {0: "code", 2: "cost_price"})
    classifier = FakeClassifier(TABLE)

    records = collect_held_out(classifier, [case])

    assert classifier.seen_indexes == [[0, 1, 2]]
    assert [(r.header, r.expected, r.predicted) for r in records] == [
        ("Codigo", "code", "code"),
        ("Costo", "cost_price", "cost_price"),
    ]
    assert {r.sheet for r in records} == {"acme-1/S"}


def test_a_model_failure_is_recorded_as_a_failed_answer_after_one_retry():
    case = SheetCase("acme-1", "S", profile_sheet(ROWS), {0: "code"})
    classifier = FakeClassifier(error=ModelSchemaError("not json"))

    records = collect_held_out(classifier, [case])

    assert len(classifier.seen_indexes) == 2
    assert [(r.failed, r.score) for r in records] == [(True, 0.0)]
