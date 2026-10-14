"""Run classifiers over the validation and held-out columns and keep every raw answer."""

import datetime
import json
from collections.abc import Callable, Sequence
from pathlib import Path

from pricor.adapters.gemma_classifier import GemmaColumnClassifier
from pricor.adapters.heuristic_classifier import HeuristicColumnClassifier
from pricor.adapters.laya_classifier import LayaColumnClassifier, resolve_device
from pricor.adapters.laya_state import QUESTIONS
from pricor.adapters.ollama_client import OllamaClient
from pricor.domain.roles import ColumnRole
from pricor.ports.column_classifier import ColumnClassification, ColumnClassifier
from pricor.ports.model_errors import ModelError
from tools.laya.dataset import Example
from tools.laya.evaluate import ZERO_SHOT_REPO, ZERO_SHOT_SUBFOLDER

from .datasets import CHUNK_SIZE, SheetCase, chunk_columns, held_out_cases, validation_examples
from .records import Record

CLASSIFIERS = ("heuristics", "laya_zero_shot", "laya_finetuned", "gemma")
_PLACEHOLDER_ROLE = ColumnRole.IGNORE.value


def _classify(classifier: ColumnClassifier, sheet) -> list[ColumnClassification] | None:
    """One sheet-level call with a single retry; None when the model gave no valid answer."""
    for _ in range(2):
        try:
            return classifier.classify_sheet(sheet)
        except ModelError:
            continue
    return None


def _record(
    result: ColumnClassification | None, expected: str, origin: str, source: str, header: str, sheet: str
) -> Record:
    if result is None:
        return Record(expected, _PLACEHOLDER_ROLE, 0.0, None, origin, source, header, sheet, failed=True)
    return Record(
        expected, result.role.value, result.score, result.latency_seconds, origin, source, header, sheet
    )


def collect_validation(
    classifier: ColumnClassifier,
    examples: Sequence[Example],
    chunk_size: int = CHUNK_SIZE,
    seed: int = 0,
) -> list[Record]:
    """Answers for the validation columns, in the order of `examples`.

    The columns come from many sheets, so they are regrouped into pseudo-sheets for the
    sheet-level classifiers.
    """
    columns = [example.profile for example in examples]
    records: list[Record | None] = [None] * len(examples)
    for number, (sheet, positions) in enumerate(chunk_columns(columns, chunk_size, seed)):
        results = _classify(classifier, sheet)
        for local, position in enumerate(positions):
            example = examples[position]
            result = results[local] if results else None
            records[position] = _record(
                result, example.role.value, example.origin, example.source, example.header, f"validation/{number}"
            )
    return [record for record in records if record is not None]


def collect_held_out(classifier: ColumnClassifier, cases: Sequence[SheetCase]) -> list[Record]:
    """Answers for the labeled held-out columns, from one whole-sheet call per sheet."""
    records = []
    for case in cases:
        results = _classify(classifier, case.profile)
        by_index = {result.index: result for result in results} if results else {}
        for index, expected in case.expected_in_order():
            header = case.profile.columns[index].raw_header
            records.append(
                _record(by_index.get(index), expected, "real", case.source_id, header, f"{case.source_id}/{case.sheet}")
            )
    return records


# -- real classifiers -------------------------------------------------------------


def _zero_shot_loader(device: str) -> Callable[[], object]:
    def load():
        import laya
        import torch

        agent = laya.load(
            ZERO_SHOT_REPO,
            subfolder=ZERO_SHOT_SUBFOLDER,
            device=resolve_device(device, torch.cuda.is_available),
        )
        agent.system_one("Column header: warm-up\nColumn type: text", QUESTIONS)
        return agent

    return load


def make_classifier(name: str, device: str, model_path: Path) -> ColumnClassifier:
    if name == "heuristics":
        return HeuristicColumnClassifier()
    if name == "laya_finetuned":
        return LayaColumnClassifier(model_path, device)
    if name == "laya_zero_shot":
        return LayaColumnClassifier(loader=_zero_shot_loader(device))
    if name == "gemma":
        return GemmaColumnClassifier(OllamaClient(timeout=300.0))
    raise ValueError(f"unknown classifier {name!r}; choose from {', '.join(CLASSIFIERS)}")


def collect_all(
    names: Sequence[str],
    device: str,
    raw_root: Path,
    labels_path: Path,
    model_path: Path,
    seed: int = 0,
) -> dict:
    """Every named classifier over both sets: the document written to `bench-results/`."""
    import torch

    examples = validation_examples(raw_root, labels_path, seed)
    cases = held_out_cases(raw_root, labels_path)
    result: dict = {
        "meta": {
            "created": datetime.datetime.now().isoformat(timespec="seconds"),
            "device_requested": device,
            "device_used": resolve_device(device, torch.cuda.is_available),
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "seed": seed,
            "validation_columns": len(examples),
            "held_out_columns": sum(len(case.expected) for case in cases),
        },
        "classifiers": {},
    }
    for name in names:
        classifier = make_classifier(name, device, model_path)
        print(f"{name}: validation ({len(examples)} columns)", flush=True)
        validation = collect_validation(classifier, examples, seed=seed)
        print(f"{name}: held-out ({result['meta']['held_out_columns']} columns)", flush=True)
        held_out = collect_held_out(classifier, cases)
        result["classifiers"][name] = {
            "validation": [record.to_dict() for record in validation],
            "held_out": [record.to_dict() for record in held_out],
        }
    return result


def write_json(path: Path, document: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=1), encoding="utf-8")
