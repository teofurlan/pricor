"""Command line of the benchmark: collect, calibrate, cascade, report.

Run from the repository root as `python -m tools.benchmark <command>` (see `docs/benchmark.md`).
Raw answers go to `bench-results/` (gitignored); the thresholds file and the report are committed.
"""

import argparse
import datetime
import json
from pathlib import Path

from pricor.application.cascade import ClassifierStage
from pricor.entrypoints.calibration_file import DEFAULT_CALIBRATION_PATH, load_calibration

from .calibrate import STAGE_OF, calibrate_stages, thresholds_document
from .cascade_eval import DEFAULT_ORDER, choose_order, run_real_cascade, variant_summaries
from .collect import CLASSIFIERS, collect_all, make_classifier, write_json
from .datasets import held_out_cases
from .metrics import Answer, summarize_cascade
from .records import Record
from .report import render_report

RESULTS = Path("bench-results")
RAW = Path("data/raw")
LABELS = Path("tools/laya/labels.json")
MODEL = Path("models/laya-pricor")
REPORT = Path("docs/benchmark.md")


def _load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _records(collected: dict, split: str) -> dict[str, list[Record]]:
    return {
        name: [Record.from_dict(item) for item in data[split]]
        for name, data in collected["classifiers"].items()
    }


def cmd_collect(args) -> None:
    names = args.classifiers.split(",")
    document = collect_all(names, args.device, args.raw, args.labels, args.model, args.seed)
    write_json(args.out, document)
    print(f"wrote {args.out}")


def cmd_calibrate(args) -> None:
    validation = _records(_load(args.collect), "validation")
    calibrations = calibrate_stages(validation, args.target_precision, args.min_support)
    document = thresholds_document(calibrations, validation, args.date)
    Path(args.out).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    for stage, calibration in calibrations.items():
        print(f"{stage}: threshold={calibration.threshold} support={calibration.support} "
              f"precision={calibration.precision} n={calibration.total} ({calibration.reason})")
    print(f"wrote {args.out}")


def _by_stage(records: dict[str, list[Record]]) -> dict[str, list[Answer]]:
    return {
        STAGE_OF[name]: [Answer(r.predicted, r.score) for r in items]
        for name, items in records.items()
        if name in STAGE_OF
    }


def cmd_cascade(args) -> None:
    collected = _load(args.collect)
    calibration = load_calibration(args.thresholds)
    thresholds = {stage: calibration.threshold_for(stage)[0] for stage in ("laya", "heuristics", "gemma")}

    validation, held_out = _records(collected, "validation"), _records(collected, "held_out")
    any_name = next(name for name in validation if name in STAGE_OF)
    validation_orders = variant_summaries(
        [r.expected for r in validation[any_name]], _by_stage(validation), thresholds
    )
    held_out_replay = variant_summaries(
        [r.expected for r in held_out[any_name]], _by_stage(held_out), thresholds
    )
    chosen = choose_order(validation_orders, calibration_target(args), DEFAULT_ORDER)
    print(f"order chosen on validation: {chosen}")

    stages = []
    for stage in chosen.split(">"):
        name = {value: key for key, value in STAGE_OF.items()}[stage]
        threshold, calibrated = calibration.threshold_for(stage)
        stages.append(
            ClassifierStage(stage, make_classifier(name, args.device, args.model), threshold, calibrated)
        )
    cases = held_out_cases(args.raw, args.labels)
    outcomes = run_real_cascade(cases, stages)
    document = {
        "default_order": DEFAULT_ORDER,
        "chosen_order": chosen,
        "validation_orders": validation_orders,
        "held_out_replay": held_out_replay,
        "real_held_out": {
            "order": chosen,
            "thresholds": {stage.name: stage.threshold for stage in stages},
            "summary": summarize_cascade(outcomes, chosen.split(">")),
            "outcomes": [o.__dict__ for o in outcomes],
        },
    }
    write_json(args.out, document)
    print(json.dumps(document["real_held_out"]["summary"], indent=1))
    print(f"wrote {args.out}")


def calibration_target(args) -> float:
    return float(_load(args.thresholds)["target_precision"])


def cmd_report(args) -> None:
    cpu = _load(args.cpu) if args.cpu.is_file() else None
    text = render_report(
        _load(args.collect), cpu, _load(args.thresholds), _load(args.cascade), args.note
    )
    Path(args.out).write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {args.out}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m tools.benchmark", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="run classifiers over validation and held-out columns")
    collect.add_argument("--classifiers", default=",".join(CLASSIFIERS))
    collect.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    collect.add_argument("--raw", type=Path, default=RAW)
    collect.add_argument("--labels", type=Path, default=LABELS)
    collect.add_argument("--model", type=Path, default=MODEL)
    collect.add_argument("--seed", type=int, default=0)
    collect.add_argument("--out", type=Path, default=RESULTS / "collect-gpu.json")
    collect.set_defaults(run=cmd_collect)

    calibrate = sub.add_parser("calibrate", help="choose thresholds from the validation answers only")
    calibrate.add_argument("--collect", type=Path, default=RESULTS / "collect-gpu.json")
    calibrate.add_argument("--target-precision", type=float, default=0.95)
    calibrate.add_argument("--min-support", type=int, default=20)
    calibrate.add_argument("--date", default=datetime.date.today().isoformat())
    calibrate.add_argument("--out", type=Path, default=DEFAULT_CALIBRATION_PATH)
    calibrate.set_defaults(run=cmd_calibrate)

    cascade = sub.add_parser("cascade", help="compare stage orders and run the real cascade on held-out")
    cascade.add_argument("--collect", type=Path, default=RESULTS / "collect-gpu.json")
    cascade.add_argument("--thresholds", type=Path, default=DEFAULT_CALIBRATION_PATH)
    cascade.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    cascade.add_argument("--raw", type=Path, default=RAW)
    cascade.add_argument("--labels", type=Path, default=LABELS)
    cascade.add_argument("--model", type=Path, default=MODEL)
    cascade.add_argument("--out", type=Path, default=RESULTS / "cascade.json")
    cascade.set_defaults(run=cmd_cascade)

    report = sub.add_parser("report", help="write docs/benchmark.md")
    report.add_argument("--collect", type=Path, default=RESULTS / "collect-gpu.json")
    report.add_argument("--cpu", type=Path, default=RESULTS / "collect-cpu.json")
    report.add_argument("--thresholds", type=Path, default=DEFAULT_CALIBRATION_PATH)
    report.add_argument("--cascade", type=Path, default=RESULTS / "cascade.json")
    report.add_argument("--note", action="append", default=[], help="a change made after seeing held-out numbers")
    report.add_argument("--out", type=Path, default=REPORT)
    report.set_defaults(run=cmd_report)

    args = parser.parse_args(argv)
    args.run(args)


if __name__ == "__main__":
    main()
