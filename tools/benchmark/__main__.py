"""Command line of the benchmark: collect, calibrate, cascade, report.

Run from the repository root as `python -m tools.benchmark <command>` (see `docs/benchmark.md`).
Raw answers go to `bench-results/` (gitignored); the thresholds file and the report are committed.
"""

import argparse
import datetime
import json
from pathlib import Path

from pricor.application.cascade import AgreementStage, ClassifierStage, Member
from pricor.entrypoints.calibration_file import DEFAULT_CALIBRATION_PATH, load_calibration

from .calibrate import AGREEMENT_STAGE, STAGE_OF, calibrate_agreement, calibrate_stages, thresholds_document
from .cascade_eval import DEFAULT_ORDER, choose_order, run_real_cascade, stage_outputs, variant_summaries
from .collect import CLASSIFIERS, collect_all, make_classifier, write_json
from .datasets import held_out_cases
from .metrics import summarize_cascade
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
    agreement = calibrate_agreement(validation, args.target_precision, args.min_support)
    document = thresholds_document(calibrations, validation, args.date, agreement)
    Path(args.out).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    for stage, calibration in calibrations.items():
        print(f"{stage}: threshold={calibration.threshold} support={calibration.support} "
              f"precision={calibration.precision} n={calibration.total} ({calibration.reason})")
    if agreement is not None:
        print(f"agreement: threshold={agreement.calibration.threshold} support={agreement.calibration.support} "
              f"precision={agreement.calibration.precision} agreed={agreement.agreed} "
              f"agreed_precision={agreement.agreed_precision} ({agreement.calibration.reason})")
    print(f"wrote {args.out}")


def cmd_cascade(args) -> None:
    collected = _load(args.collect)
    calibration = load_calibration(args.thresholds)
    thresholds = {stage: calibration.threshold_for(stage)[0] for stage in ("laya", "heuristics", "gemma")}
    agreement_on = calibration.threshold_for(AGREEMENT_STAGE)[1]
    if agreement_on:
        thresholds[AGREEMENT_STAGE] = calibration.threshold_for(AGREEMENT_STAGE)[0]

    validation, held_out = _records(collected, "validation"), _records(collected, "held_out")
    any_name = next(name for name in validation if name in STAGE_OF)
    validation_orders = variant_summaries(
        [r.expected for r in validation[any_name]], stage_outputs(validation, agreement_on), thresholds
    )
    held_out_replay = variant_summaries(
        [r.expected for r in held_out[any_name]], stage_outputs(held_out, agreement_on), thresholds
    )
    chosen = choose_order(validation_orders, calibration_target(args), DEFAULT_ORDER)
    print(f"order chosen on validation: {chosen}")

    classifiers: dict = {}

    def classifier(name: str):
        if name not in classifiers:
            classifiers[name] = make_classifier(name, args.device, args.model)
        return classifiers[name]

    stages = []
    for stage in chosen.split(">"):
        threshold, calibrated = calibration.threshold_for(stage)
        if stage == AGREEMENT_STAGE:
            stages.append(
                AgreementStage(
                    stage, Member("heuristics", classifier("heuristics")),
                    Member("laya", classifier("laya_finetuned")), threshold, calibrated,
                )
            )
            continue
        name = {value: key for key, value in STAGE_OF.items()}[stage]
        stages.append(ClassifierStage(stage, classifier(name), threshold, calibrated))
    cases = held_out_cases(args.raw, args.labels)
    outcomes = run_real_cascade(cases, stages)
    document = {
        "default_order": DEFAULT_ORDER,
        "chosen_order": chosen,
        "validation_orders": validation_orders,
        "held_out_replay": held_out_replay,
        "real_held_out": {
            "order": chosen,
            "thresholds": {
                stage.name: getattr(stage, "threshold", getattr(stage, "min_confidence", None))
                for stage in stages
            },
            "summary": summarize_cascade(outcomes, chosen.split(">")),
            "outcomes": [o.__dict__ for o in outcomes],
        },
    }
    write_json(args.out, document)
    record_order(args.thresholds, chosen)
    print(json.dumps(document["real_held_out"]["summary"], indent=1))
    print(f"wrote {args.out}")


def record_order(path: Path, order: str) -> None:
    """Write the order chosen on validation into the thresholds file the app reads."""
    document = _load(path)
    document["cascade_order"] = order
    Path(path).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def calibration_target(args) -> float:
    return float(_load(args.thresholds)["target_precision"])


def cmd_report(args) -> None:
    cpu = _load(args.cpu) if args.cpu.is_file() else None
    text = render_report(
        _load(args.collect), cpu, _load(args.thresholds), _load(args.cascade), args.note, args.previous
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
    report.add_argument("--previous", action="append", default=[], help="a line about the previous run")
    report.add_argument("--out", type=Path, default=REPORT)
    report.set_defaults(run=cmd_report)

    args = parser.parse_args(argv)
    args.run(args)


if __name__ == "__main__":
    main()
