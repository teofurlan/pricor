"""Render `docs/benchmark.md` from the raw collection, the calibration and the cascade results."""

from collections import Counter
from collections.abc import Mapping, Sequence

from .metrics import ROLE_NAMES, label_metrics, latency_summary
from .records import Record

NAMES = {
    "heuristics": "Heuristics",
    "laya_zero_shot": "Laya zero-shot",
    "laya_finetuned": "Laya fine-tuned",
    "gemma": "Gemma",
}
STAGE_NAMES = {
    "agreement": "Agreement (heuristics + Laya)",
    "laya": "Laya",
    "heuristics": "Heuristics",
    "gemma": "Gemma",
    "user": "User",
}


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _num(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _records(collected: Mapping, name: str, split: str) -> list[Record]:
    return [Record.from_dict(item) for item in collected["classifiers"][name][split]]


def _present(collected: Mapping) -> list[str]:
    return [name for name in NAMES if name in collected["classifiers"]]


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def _accuracy_section(collected: Mapping) -> str:
    rows, failures = [], []
    for name in _present(collected):
        records = _records(collected, name, "held_out")
        correct = sum(r.predicted == r.expected and not r.failed for r in records)
        failed = sum(r.failed for r in records)
        if failed:
            failures.append(f"{NAMES[name]}: {failed} failed")
        rows.append(
            [NAMES[name], str(len(records)), str(correct), _pct(correct / len(records) if records else None)]
        )
    text = _table(["Classifier", "Columns", "Correct", "Accuracy"], rows)
    if failures:
        text += (
            "\n\nA sheet the model failed to answer validly (after one retry) counts every one of its "
            "columns as wrong. " + "; ".join(failures) + " columns."
        )
    return text


def _label_section(collected: Mapping) -> str:
    present = _present(collected)
    metrics = {
        name: label_metrics([(r.expected, r.predicted) for r in _records(collected, name, "held_out")])
        for name in present
    }
    rows = []
    for role in ROLE_NAMES:
        support = next((metrics[name][role]["support"] for name in present), 0)
        predicted = sum(metrics[name][role]["predicted"] for name in present)
        if not support and not predicted:
            continue
        cells = [
            f"{_num(metrics[name][role]['precision'])} / {_num(metrics[name][role]['recall'])}"
            for name in present
        ]
        rows.append([role, str(support), *cells])
    header = ["Label", "Support", *[f"{NAMES[name]} (P / R)" for name in present]]
    return (
        _table(header, rows)
        + "\n\nP is precision and R is recall; `n/a` means the label was never predicted (P) or never occurs (R)."
    )


def _calibration_section(calibration: Mapping) -> str:
    rows = []
    for stage, entry in calibration["stages"].items():
        real = entry.get("real_only")
        threshold = "not calibrated" if entry["threshold"] is None else f"{entry['threshold']:.4f}"
        validated, note = str(entry["n"]), entry["reason"]
        if "members" in entry:  # the agreement stage: only agreed columns are candidates
            validated = f"{entry['agreed']} agreed"
            note += (
                f"; precision of the agreed answers is {_pct(entry['agreed_precision'])} without a confidence "
                "bar, and the threshold is a bar the higher of the two scores must reach"
            )
            if entry["threshold"] is None:
                note += "; the stage is not enabled"
        rows.append(
            [
                stage,
                threshold,
                validated,
                str(entry["support"]),
                _pct(entry["precision"]),
                "n/a" if real is None else f"{real['support']} / {_pct(real['precision'])}",
                note,
            ]
        )
    validation = calibration["validation"]
    header = [
        "Stage",
        "Threshold",
        "Validation n",
        "Accepted",
        "Precision of accepted",
        "Real only (accepted / precision)",
        "Note",
    ]
    return (
        f"Method: {calibration['method']}. Calibrated on {calibration['calibrated_on']} on "
        f"{validation['n']} validation columns ({validation['real']} real resamples, "
        f"{validation['synthetic']} synthetic).\n\n" + _table(header, rows)
    )


def _summary_rows(summary: Mapping) -> list[list[str]]:
    total = summary["total"]
    return [
        [STAGE_NAMES.get(stage, stage), str(count), _pct(count / total if total else None)]
        for stage, count in summary["resolved_by"].items()
    ]


def _cascade_section(cascade: Mapping) -> str:
    real = cascade["real_held_out"]
    summary = real["summary"]
    thresholds = ", ".join(f"{stage} {value:.4f}" for stage, value in real["thresholds"].items())
    return "\n\n".join(
        [
            f"Order: `{real['order']}` (decided on the validation set, see below). Thresholds in force: "
            f"{thresholds}. This is the application's own cascade run over whole held-out sheets, so Gemma "
            "only sees the columns the earlier stage left over.",
            _table(["Settled by", "Columns", "Share"], _summary_rows(summary)),
            f"Automatically settled: {summary['auto_resolved']} of {summary['total']}, of which "
            f"{summary['auto_correct']} are correct (**{_pct(summary['auto_accuracy'])}**). "
            f"Escalated to the user: {summary['resolved_by']['user']} "
            f"(escalation rate {_pct(summary['escalation_rate'])}); the best-scoring proposal was right for "
            f"{summary['escalated_best_guess_correct']} of them.",
        ]
    )


def _orders_section(cascade: Mapping) -> str:
    def rows(summaries: Mapping) -> list[list[str]]:
        return [
            [
                f"`{label}`" + (" (default)" if label == cascade["default_order"] else ""),
                _pct(s["escalation_rate"]),
                _pct(s["auto_accuracy"]),
            ]
            for label, s in summaries.items()
        ]

    header = ["Order", "Escalated to user", "Accuracy of automatic answers"]
    return (
        "The order is chosen on the validation set: the order that escalates least while its automatic "
        "answers meet the target precision; ties and the case where none meets it keep the default "
        f"`{cascade['default_order']}`. Chosen: `{cascade['chosen_order']}`. A stage with no calibrated "
        "threshold is replayed at the 0.75 placeholder.\n\n"
        "Validation set (used for the decision; replayed from each stage's answers):\n\n"
        + _table(header, rows(cascade["validation_orders"]))
        + "\n\nHeld-out set (informational only, not used for the decision; replayed from cached answers, "
        "so Gemma saw whole sheets here instead of only the leftovers):\n\n"
        + _table(header, rows(cascade["held_out_replay"]))
    )


def _latency_rows(collected: Mapping, device: str) -> list[list[str]]:
    rows = []
    for name in _present(collected):
        records = _records(collected, name, "held_out")
        if name == "gemma":
            per_call = {r.sheet: r.latency_seconds for r in records if r.latency_seconds is not None}
            seconds, unit, label = list(per_call.values()), "per sheet", "Gemma (Ollama)"
        else:
            seconds = [r.latency_seconds for r in records if r.latency_seconds is not None]
            unit = "per column"
            label = f"{NAMES[name]} ({device})" if name.startswith("laya") else NAMES[name]
        summary = latency_summary(seconds)
        rows.append(
            [
                label,
                unit,
                str(summary["n"]),
                _num(summary["mean_ms"], 1),
                _num(summary["median_ms"], 1),
                _num(summary["p95_ms"], 1),
            ]
        )
    return rows


def _latency_section(collected: Mapping, cpu: Mapping | None) -> str:
    rows = _latency_rows(collected, collected["meta"]["device_used"])
    note = f"GPU: {collected['meta'].get('gpu') or 'none'}."
    if cpu is None:
        note += " CPU run: not available."
    else:
        rows += [r for r in _latency_rows(cpu, cpu["meta"]["device_used"]) if r[0].startswith("Laya")]
    return (
        _table(["Classifier", "Unit", "Calls", "Mean ms", "Median ms", "p95 ms"], rows)
        + f"\n\n{note} Laya latency is the model call for one column after a warm-up call; Gemma latency is "
        "the one request that classifies a whole sheet (a different unit, not comparable per column). "
        "Heuristics are not timed."
    )


def _data_section(collected: Mapping) -> str:
    held = _records(collected, _present(collected)[0], "held_out")
    support = Counter(r.expected for r in held)
    labels = ", ".join(f"{role} {support[role]}" for role in ROLE_NAMES if support[role])
    missing = ", ".join(role for role in ROLE_NAMES if not support[role]) or "none"
    meta = collected["meta"]
    return (
        f"- **Validation set:** {meta['validation_columns']} columns carved from the training distributors "
        "(header-disjoint from training; real resamples plus synthetic columns). Used only to calibrate "
        "thresholds.\n"
        f"- **Held-out test set:** {meta['held_out_columns']} labeled columns of Dipel and DistriLap, profiled "
        f"whole-sheet like the app does ({labels}). Roles with no held-out column: {missing}."
    )


def _bullets(lines: Sequence[str]) -> str:
    return "\n".join(f"- {line}" for line in lines)


LIMITS = """\
- The held-out set is small (see its size above), so every accuracy has a wide uncertainty: one column is several percentage points. Treat the numbers as a signal, not a precise estimate.
- It has no column for several roles (listed above), so nothing here says how any classifier does on them. The training pool has no real `retail_price` or `vat_rate` column either.
- Dipel's files share most of their columns, so the number of distinct columns is smaller than the count; DistriLap's lists have no header row, which is a hard case by construction.
- The validation set is partly synthetic and its synthetic share comes from the same generator as the training data, so thresholds calibrated on it can be optimistic for real lists. The real-only precision at each threshold is shown next to it. The held-out test set was never used for calibration or for any choice of threshold or stage order.
- **The heuristics are not a clean baseline on this held-out set.** Their keyword rules, such as the cost-vs-retail modifiers `lista`, `venta` and `sugerido`, were written after the Dipel headers had been seen during exploration and smoke runs. Their held-out score is therefore optimistic. On the synthetic-heavy validation set, no confidence threshold reached the precision target. Laya and Gemma never saw the held-out distributors. Any stage that leans on the heuristics, the agreement stage included, inherits that advantage.
- The reference labels are one person's judgment (ambiguous columns are noted in `tools/laya/labels.json`).
- Gemma runs at temperature 0 through Ollama with `think: false`; its reported confidence is the model's own number, not a probability.
- Latency depends on this machine (an 8 GB laptop GPU) and on what else it was running.
"""

REPRODUCE = """\
```text
uv sync --extra laya
uv run python -m tools.benchmark collect --out bench-results/collect-gpu.json
uv run python -m tools.benchmark collect --device cpu --classifiers laya_zero_shot,laya_finetuned --out bench-results/collect-cpu.json
uv run python -m tools.benchmark calibrate --collect bench-results/collect-gpu.json
uv run python -m tools.benchmark cascade --collect bench-results/collect-gpu.json
uv run python -m tools.benchmark report
```

The raw lists are not committed (`data/raw/`, see `tools/corpus`); Gemma needs `OLLAMA_FLASH_ATTENTION=0 ollama serve`.
"""

METHOD = """\
Each classifier assigns one of ten roles to every labeled column of a supplier price list. All of them receive the same deterministic column profile: Laya reads the serialized state (`src/pricor/adapters/laya_state.py`), the heuristics and Gemma read the profile directly.

- **Heuristics:** keyword and type rules.
- **Laya zero-shot:** the `multilingual` base checkpoint, no fine-tuning.
- **Laya fine-tuned:** that checkpoint fine-tuned on the training distributors plus synthetic columns (`tools/laya`).
- **Gemma:** `gemma4:e4b` through Ollama, one request per sheet.
- **Agreement:** a cascade stage that runs the heuristics and fine-tuned Laya together and settles a column only when both pick the same role (optionally also requiring that at least one of them reaches a calibrated confidence).
- **Cascade:** the application's own stages with calibrated thresholds; a column a stage scores at or above its threshold is settled, the rest go on, and what is left goes to the user.
"""


def render_report(
    collected: Mapping,
    cpu: Mapping | None,
    calibration: Mapping,
    cascade: Mapping,
    post_hoc_notes: Sequence[str] = (),
    previous_run: Sequence[str] = (),
) -> str:
    meta = collected["meta"]
    notes = (
        "\n".join(f"- {note}" for note in post_hoc_notes)
        or "None: nothing was changed after the held-out numbers were seen."
    )
    sections = [
        "# Benchmark: column classifiers and cascade",
        f"Generated {meta['created']} on {meta.get('gpu') or 'CPU'}. Raw answers are in `bench-results/` "
        "(not committed).",
        "## Method",
        METHOD,
        "## Data",
        _data_section(collected),
        "## Held-out results",
        _accuracy_section(collected),
        _label_section(collected),
        "## Calibration",
        _calibration_section(calibration),
        "## Cascade on the held-out set",
        _cascade_section(cascade),
        "### Stage order",
        _orders_section(cascade),
        "## Latency",
        _latency_section(collected, cpu),
        "## Changes made after seeing held-out numbers",
        notes,
        *(["## Previous run", _bullets(previous_run)] if previous_run else []),
        "## Limits",
        LIMITS,
        "## Reproduce",
        REPRODUCE,
    ]
    return "\n\n".join(section.rstrip("\n") for section in sections) + "\n"
