"""Score role predictions and run a held-out comparison of Laya checkpoints.

    uv run python -m tools.laya.evaluate [--model models/laya-pricor]

It classifies the held-out distributors' columns with the zero-shot `multilingual` checkpoint
and with the fine-tuned one, using the same state serializer the runtime adapter uses, and
prints accuracy plus a per-label and confusion summary. This is a preview; the formal benchmark
(heuristics, Gemma, calibrated thresholds) belongs to the evaluation task.
"""

import argparse
import json
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pricor.adapters.laya_state import QUESTION_ID, QUESTIONS
from pricor.domain.roles import ColumnRole

from .build import build_held_out
from .dataset import Example

ZERO_SHOT_REPO = "convaiinnovations/laya"
ZERO_SHOT_SUBFOLDER = "multilingual"


@dataclass(frozen=True)
class Scores:
    correct: int
    total: int
    per_label: dict[str, dict[str, int]]
    confusion: Counter  # (expected, predicted) -> count, errors and hits alike

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0


def score(pairs: list[tuple[str, str]]) -> Scores:
    """Accuracy, per-label support/correct/predicted counts and the confusion of (expected, predicted)."""
    per_label = {role.value: {"support": 0, "correct": 0, "predicted": 0} for role in ColumnRole}
    confusion: Counter = Counter()
    correct = 0
    for expected, predicted in pairs:
        per_label[expected]["support"] += 1
        per_label[predicted]["predicted"] += 1
        confusion[(expected, predicted)] += 1
        if expected == predicted:
            per_label[expected]["correct"] += 1
            correct += 1
    return Scores(correct, len(pairs), per_label, confusion)


def format_summary(name: str, scores: Scores) -> str:
    lines = [
        f"{name}: {scores.correct}/{scores.total} = {scores.accuracy:.1%}",
        f"{'label':16} {'support':>7} {'correct':>7} {'predicted':>9}",
    ]
    for role in ColumnRole:
        row = scores.per_label[role.value]
        if row["support"] or row["predicted"]:
            lines.append(f"{role.value:16} {row['support']:>7} {row['correct']:>7} {row['predicted']:>9}")
    errors = sorted(
        ((pair, n) for pair, n in scores.confusion.items() if pair[0] != pair[1]),
        key=lambda item: (-item[1], item[0]),
    )
    if errors:
        lines.append("errors (expected -> predicted: count):")
        lines += [f"  {expected} -> {predicted}: {n}" for (expected, predicted), n in errors]
    return "\n".join(lines)


# -- running a checkpoint (needs the `laya` extra and a GPU) -----------------------


def predict(agent, examples: list[Example]) -> list[dict]:
    """Classify each example's state; returns the label, its confidence and the latency."""
    import torch

    results = []
    agent.system_one(examples[0].state, QUESTIONS)  # warm-up
    for example in examples:
        started = time.perf_counter()
        answer = agent.system_one(example.state, QUESTIONS)["answers"][QUESTION_ID]
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        results.append(
            {
                "source": example.source,
                "header": example.header,
                "expected": example.role.value,
                "predicted": answer["choice"],
                "confidence": round(float(answer["confidence"]), 4),
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            }
        )
    return results


def _evaluate(name: str, load, examples: list[Example]) -> dict:
    import torch

    agent = load()
    rows = predict(agent, examples)
    del agent
    torch.cuda.empty_cache()
    scores = score([(row["expected"], row["predicted"]) for row in rows])
    print(format_summary(name, scores), flush=True)
    return {"accuracy": scores.accuracy, "correct": scores.correct, "total": scores.total, "rows": rows}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", type=Path, default=Path("models/laya-pricor"))
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--labels", type=Path, default=Path(__file__).with_name("labels.json"))
    args = parser.parse_args(argv)

    import laya

    examples = build_held_out(args.raw, args.labels)
    print(f"{len(examples)} held-out columns from {len({e.source for e in examples})} sources", flush=True)
    device = "cuda"
    result = {
        "zero_shot": _evaluate(
            "zero-shot multilingual",
            lambda: laya.load(ZERO_SHOT_REPO, subfolder=ZERO_SHOT_SUBFOLDER, device=device),
            examples,
        ),
        "fine_tuned": _evaluate(
            "fine-tuned", lambda: laya.load(str(args.model), device=device), examples
        ),
    }
    target = args.model / "heldout_eval.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
