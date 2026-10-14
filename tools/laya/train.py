"""Build the datasets and fine-tune the Laya column classifier on them.

    uv sync --extra laya
    uv run python -m tools.laya.train [--seed 0] [--out models/laya-pricor]

Training uses the real columns of the training distributors (resampled) plus synthetic ones;
two whole distributors stay held out (see README.md). The model, the datasets (they contain
sample cell values from real lists) and the training report are written under `--out`, which is
gitignored. Weights are never published from here.
"""

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from .build import Datasets, build_datasets
from .dataset import Example, label_counts, write_jsonl
from .split import HELD_OUT_DISTRIBUTORS

BASE_MODEL = "multilingual"
TRAIN_SETTINGS: dict[str, Any] = {
    "epochs": 3,
    "micro_batch": 4,
    "grad_accum": 2,
    "loss": "soft-ce",
    "amp": True,
    "gradient_checkpointing": True,
    "question_id": "role",
    "shuffle_options": ["choice"],
    "log_every": 10,
}


def _counts(examples: tuple[Example, ...]) -> dict[str, Any]:
    return {
        "total": len(examples),
        "by_label": label_counts(examples),
        "by_origin": dict(Counter(example.origin for example in examples)),
    }


def training_report(
    datasets: Datasets,
    seed: int,
    duration_seconds: float,
    peak_vram_mb: dict[str, float],
    versions: dict[str, str],
    summary: dict[str, Any],
) -> dict[str, Any]:
    """The JSON-serializable record of one run: counts, settings, environment. No example text."""
    return {
        "seed": seed,
        "duration_seconds": round(duration_seconds, 1),
        "peak_vram_mb": peak_vram_mb,
        "versions": versions,
        "settings": TRAIN_SETTINGS,
        "examples": {
            "train": _counts(datasets.train),
            "validation": _counts(datasets.validation),
            "held_out": _counts(datasets.held_out),
        },
        "split": {
            "held_out_distributors": sorted(HELD_OUT_DISTRIBUTORS),
            "banned_headers": len(datasets.banned_headers),
            "dropped_training_columns": len(datasets.dropped),
        },
        "summary": summary,
        "notes": [
            "Laya fits temperature and abstention on a random 10% calibration slice of the "
            "training file, so those numbers are in-sample with respect to headers; the cascade "
            "threshold is recalibrated on held-out data in the evaluation task.",
            "The validation set is carved by header from the training distributors and is "
            "passed to Laya as the evaluation set.",
        ],
    }


def run_training(datasets: Datasets, out: Path, seed: int) -> dict[str, Any]:
    """Write the datasets, fine-tune on the GPU, write the model and the report."""
    import laya
    import torch
    from laya.train import TrainConfig, finetune

    if not torch.cuda.is_available():
        raise SystemExit("no CUDA device: install the CUDA build of torch (uv sync --extra laya)")
    data_dir = out / "datasets"
    write_jsonl(data_dir / "train.jsonl", datasets.train)
    write_jsonl(data_dir / "validation.jsonl", datasets.validation)
    write_jsonl(data_dir / "held_out.jsonl", datasets.held_out)

    settings = {**TRAIN_SETTINGS, "shuffle_options": tuple(TRAIN_SETTINGS["shuffle_options"])}
    config = TrainConfig(**settings, seed=seed, eval_data=str(data_dir / "validation.jsonl"))
    torch.cuda.reset_peak_memory_stats()
    started = time.time()
    summary = finetune(str(data_dir / "train.jsonl"), BASE_MODEL, str(out), config, device="cuda")
    duration = time.time() - started
    peak = {
        "allocated": round(torch.cuda.max_memory_allocated() / 2**20, 1),
        "reserved": round(torch.cuda.max_memory_reserved() / 2**20, 1),
    }
    # The laya summary nests the full train report and the per-epoch history; keep the compact parts.
    compact = {
        key: summary.get(key)
        for key in ("train_items", "calibration_items", "eval_items", "epoch_loss", "temperature")
    }
    compact["evaluation"] = {
        "before": (summary.get("train_report") or {}).get("before"),
        "after": (summary.get("train_report") or {}).get("after"),
        "note": (summary.get("train_report") or {}).get("note"),
    }
    report = training_report(
        datasets, seed, duration, peak, {"laya": laya.__version__, "torch": torch.__version__}, compact
    )
    (out / "training_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=Path("models/laya-pricor"))
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--labels", type=Path, default=Path(__file__).with_name("labels.json"))
    args = parser.parse_args(argv)

    datasets = build_datasets(args.raw, args.labels, args.seed)
    print(
        f"train {len(datasets.train)}, validation {len(datasets.validation)}, "
        f"held-out {len(datasets.held_out)} examples",
        flush=True,
    )
    report = run_training(datasets, args.out, args.seed)
    print(json.dumps({k: report[k] for k in ("duration_seconds", "peak_vram_mb", "versions")}, indent=1))


if __name__ == "__main__":
    main()
