"""Opt-in smoke test against a running Ollama with `gemma4:e4b` pulled.

Deselected by default. Run it with:

    uv run pytest -m live -s

It reads real corpus files from `data/raw/` (gitignored) through the normal
reader and profiler, runs the heuristic and Gemma classifiers and the Gemma plan
advisor, and prints a comparison. It asserts only that outputs are valid or fail
with a typed `ModelError`; judging quality is left to whoever reads the report.
"""

import os
import time
import urllib.request
from pathlib import Path

import pytest

from pricor.adapters.gemma_advisor import GemmaPlanAdvisor
from pricor.adapters.gemma_classifier import GemmaColumnClassifier
from pricor.adapters.heuristic_classifier import HeuristicColumnClassifier
from pricor.adapters.ollama_client import DEFAULT_BASE_URL, OllamaClient
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.domain.profile import profile_sheet
from pricor.ports.model_errors import ModelError

pytestmark = pytest.mark.live

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
FILES = [
    "distrilap-libreria/2026-10-13/lista_libreria.xlsx",
    "bulonera-camba-completa/2026-10-13/completa-lista-formato-sabana_2026-10-04.xlsx",
    "distribucion-masiva-ferreteria/2026-10-13/ferreteria.xls",
]
MODEL = os.environ.get("PRICOR_LIVE_MODEL", "gemma4:e4b")


def _ollama_up() -> bool:
    try:
        urllib.request.urlopen(f"{DEFAULT_BASE_URL}/api/tags", timeout=2).read()
    except OSError:
        return False
    return True


@pytest.mark.skipif(not _ollama_up(), reason="Ollama is not running")
@pytest.mark.parametrize("relative", FILES)
def test_gemma_adapters_on_real_corpus_file(relative):
    path = RAW / relative
    if not path.exists():
        pytest.skip(f"{path} is not downloaded")
    sheet_data = FileSpreadsheetReader().read_sheet(path)
    profile = profile_sheet(sheet_data.rows)
    heuristic = HeuristicColumnClassifier().classify_sheet(profile)
    client = OllamaClient(model=MODEL, timeout=300)

    print(f"\n=== {relative}  sheet={sheet_data.name!r}  columns={len(profile.columns)}")
    gemma = None
    try:
        started = time.perf_counter()
        gemma = GemmaColumnClassifier(client).classify_sheet(profile)
        print(f"classifier latency: {time.perf_counter() - started:.1f}s")
        for h, g in zip(heuristic, gemma, strict=True):
            mark = "" if h.role is g.role else "   <-- differs"
            print(
                f"  [{h.index:>2}] {h.header[:28]:<28} heuristic={h.role.value:<14}"
                f"({h.score:.2f}) gemma={g.role.value:<14}({g.score:.2f}){mark}"
            )
    except ModelError as error:
        print(f"classifier INVALID/FAILED: {type(error).__name__}: {error}")

    roles = gemma or heuristic
    try:
        proposal = GemmaPlanAdvisor(client).propose(profile, roles, language="en")
        print(f"advisor latency: {proposal.latency_seconds:.1f}s")
        for hyp in proposal.hypotheses:
            print(f"  hypothesis {hyp.parameter.value} = {hyp.value!r} (reported {hyp.confidence})")
        for question in proposal.questions:
            print(f"  question [{question.id.value}] {question.text}")
            for option in question.options:
                print(f"      - {option.label}  ->  {option.value!r}")
    except ModelError as error:
        print(f"advisor INVALID/FAILED: {type(error).__name__}: {error}")
