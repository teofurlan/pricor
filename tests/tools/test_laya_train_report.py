import json

from pricor.domain.roles import ColumnRole
from tools.laya.build import Datasets
from tools.laya.dataset import Example
from tools.laya.evaluate import format_summary, score
from tools.laya.train import TRAIN_SETTINGS, training_report


def example(role, origin="synthetic", source="synthetic", header="h"):
    return Example(f"state of {header}", role, origin, source, header)


def datasets():
    return Datasets(
        train=(example(ColumnRole.CODE), example(ColumnRole.CODE, "real", "electricidad-emilio"), example(ColumnRole.IGNORE)),
        validation=(example(ColumnRole.CODE),),
        held_out=(example(ColumnRole.COST_PRICE, "real", "dipel-lista-pagina-web"),),
        banned_headers=frozenset({"codigo"}),
        dropped=(),
    )


def report(**overrides):
    values = {
        "seed": 3,
        "duration_seconds": 61.234,
        "peak_vram_mb": {"allocated": 6200.5, "reserved": 6400.0},
        "versions": {"laya": "0.4.6", "torch": "2.14.1+cu126"},
        "summary": {"train_items": 3, "calibration_items": 0, "epoch_loss": [1.2, 0.5], "temperature": 1.1},
    }
    return training_report(datasets(), **{**values, **overrides})


def test_the_report_counts_examples_per_label_and_origin():
    counts = report()["examples"]

    assert counts["train"]["by_label"]["code"] == 2 and counts["train"]["by_label"]["barcode"] == 0
    assert counts["train"]["by_origin"] == {"synthetic": 2, "real": 1}
    assert counts["validation"]["total"] == 1
    assert counts["held_out"]["by_label"]["cost_price"] == 1


def test_the_report_records_the_run_settings_and_environment():
    document = report()

    assert document["seed"] == 3 and document["duration_seconds"] == 61.2
    assert document["settings"]["epochs"] == TRAIN_SETTINGS["epochs"] == 3
    assert document["peak_vram_mb"] == {"allocated": 6200.5, "reserved": 6400.0}
    assert document["versions"] == {"laya": "0.4.6", "torch": "2.14.1+cu126"}
    assert document["summary"]["epoch_loss"] == [1.2, 0.5]


def test_the_report_states_the_split_and_has_no_cell_text():
    document = report()

    assert document["split"]["held_out_distributors"] == ["dipel", "distrilap"]
    assert document["split"]["banned_headers"] == 1
    text = json.dumps(document)
    assert "state of" not in text  # counts and settings only, never example text


def test_the_report_warns_that_laya_calibrates_on_a_slice_of_the_training_data():
    assert "calibration" in report()["notes"][0].lower()


# -- scoring --


def test_scores_count_accuracy_per_label_and_the_confusion():
    pairs = [("code", "code"), ("code", "ignore"), ("cost_price", "retail_price"), ("ignore", "ignore")]

    scores = score(pairs)

    assert (scores.correct, scores.total, scores.accuracy) == (2, 4, 0.5)
    assert scores.per_label["code"] == {"support": 2, "correct": 1, "predicted": 1}
    assert scores.per_label["retail_price"] == {"support": 0, "correct": 0, "predicted": 1}
    assert scores.confusion[("cost_price", "retail_price")] == 1
    assert ("code", "code") not in scores.confusion or scores.confusion[("code", "code")] == 1


def test_the_summary_lists_the_labels_with_support_and_the_errors():
    text = format_summary("fine-tuned", score([("code", "code"), ("code", "ignore")]))

    assert "fine-tuned" in text and "1/2" in text and "50.0%" in text
    assert "code -> ignore: 1" in text
    assert "code" in text.splitlines()[2]


def test_an_empty_evaluation_scores_zero_without_dividing():
    assert score([]).accuracy == 0.0
