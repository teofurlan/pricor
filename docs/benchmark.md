# Benchmark: column classifiers and cascade

Generated 2026-10-14T15:40:57 on NVIDIA GeForce RTX 4060 Laptop GPU. Raw answers are in `bench-results/` (not committed).

## Method

Each classifier assigns one of ten roles to every labeled column of a supplier price list. All of them receive the same deterministic column profile: Laya reads the serialized state (`src/pricor/adapters/laya_state.py`), the heuristics and Gemma read the profile directly.

- **Heuristics:** keyword and type rules.
- **Laya zero-shot:** the `multilingual` base checkpoint, no fine-tuning.
- **Laya fine-tuned:** that checkpoint fine-tuned on the training distributors plus synthetic columns (`tools/laya`).
- **Gemma:** `gemma4:e4b` through Ollama, one request per sheet.
- **Cascade:** the application's own stages with calibrated thresholds; a column a stage scores at or above its threshold is settled, the rest go on, and what is left goes to the user.

## Data

- **Validation set:** 161 columns carved from the training distributors (header-disjoint from training; real resamples plus synthetic columns). Used only to calibrate thresholds.
- **Held-out test set:** 29 labeled columns of Dipel and DistriLap, profiled whole-sheet like the app does (code 5, description 5, cost_price 4, retail_price 3, ignore 12). Roles with no held-out column: vat_rate, units_per_pack, barcode, discount, currency.

## Held-out results

| Classifier | Columns | Correct | Accuracy |
|---|---|---|---|
| Heuristics | 29 | 26 | 89.7% |
| Laya zero-shot | 29 | 16 | 55.2% |
| Laya fine-tuned | 29 | 24 | 82.8% |
| Gemma | 29 | 27 | 93.1% |

| Label | Support | Heuristics (P / R) | Laya zero-shot (P / R) | Laya fine-tuned (P / R) | Gemma (P / R) |
|---|---|---|---|---|---|
| code | 5 | 1.00 / 0.60 | 1.00 / 0.60 | 1.00 / 0.60 | 1.00 / 1.00 |
| description | 5 | 1.00 / 1.00 | 1.00 / 0.80 | 1.00 / 0.80 | 0.71 / 1.00 |
| cost_price | 4 | 0.80 / 1.00 | n/a / 0.00 | 1.00 / 0.50 | 1.00 / 1.00 |
| retail_price | 3 | 1.00 / 1.00 | 0.20 / 0.33 | 0.43 / 1.00 | 1.00 / 1.00 |
| vat_rate | 0 | n/a / n/a | 0.00 / n/a | n/a / n/a | n/a / n/a |
| barcode | 0 | n/a / n/a | 0.00 / n/a | n/a / n/a | n/a / n/a |
| currency | 0 | n/a / n/a | 0.00 / n/a | n/a / n/a | n/a / n/a |
| ignore | 12 | 0.85 / 0.92 | 0.67 / 0.67 | 0.92 / 1.00 | 1.00 / 0.83 |

P is precision and R is recall; `n/a` means the label was never predicted (P) or never occurs (R).

## Calibration

Method: lowest validation confidence whose accepted answers (score >= threshold) have precision >= 0.95 with support >= 20. Calibrated on 2026-10-14 on 161 validation columns (48 real resamples, 113 synthetic).

| Stage | Threshold | Validation n | Accepted | Precision of accepted | Real only (accepted / precision) | Note |
|---|---|---|---|---|---|---|
| heuristics | not calibrated | 161 | 0 | n/a | n/a | no threshold meets the target precision with the minimum support |
| laya | 0.9959 | 161 | 42 | 97.6% | 1 / 0.0% | met |
| gemma | 0.9800 | 161 | 37 | 100.0% | 6 / 100.0% | met |

## Cascade on the held-out set

Order: `laya>gemma` (decided on the validation set, see below). Thresholds in force: laya 0.9959, gemma 0.9800. This is the application's own cascade run over whole held-out sheets, so Gemma only sees the columns the earlier stage left over.

| Settled by | Columns | Share |
|---|---|---|
| Laya | 3 | 10.3% |
| Gemma | 9 | 31.0% |
| User | 17 | 58.6% |

Automatically settled: 12 of 29, of which 11 are correct (**91.7%**). Escalated to the user: 17 (escalation rate 58.6%); the best-scoring proposal was right for 15 of them.

### Stage order

The order is chosen on the validation set: the order that escalates least while its automatic answers meet the target precision; ties and the case where none meets it keep the default `laya>gemma`. Chosen: `laya>gemma`. A stage with no calibrated threshold is replayed at the 0.75 placeholder.

Validation set (used for the decision; replayed from each stage's answers):

| Order | Escalated to user | Accuracy of automatic answers |
|---|---|---|
| `laya>gemma` (default) | 61.5% | 98.4% |
| `heuristics>laya>gemma` | 33.5% | 88.8% |
| `laya>heuristics>gemma` | 33.5% | 88.8% |
| `heuristics>gemma` | 42.2% | 87.1% |
| `laya` | 73.9% | 97.6% |
| `heuristics` | 50.9% | 84.8% |
| `gemma` | 77.0% | 100.0% |

Held-out set (informational only, not used for the decision; replayed from cached answers, so Gemma saw whole sheets here instead of only the leftovers):

| Order | Escalated to user | Accuracy of automatic answers |
|---|---|---|
| `laya>gemma` (default) | 62.1% | 100.0% |
| `heuristics>laya>gemma` | 37.9% | 100.0% |
| `laya>heuristics>gemma` | 37.9% | 100.0% |
| `heuristics>gemma` | 37.9% | 100.0% |
| `laya` | 89.7% | 100.0% |
| `heuristics` | 55.2% | 100.0% |
| `gemma` | 72.4% | 100.0% |

## Latency

| Classifier | Unit | Calls | Mean ms | Median ms | p95 ms |
|---|---|---|---|---|---|
| Heuristics | per column | 0 | n/a | n/a | n/a |
| Laya zero-shot (cuda) | per column | 29 | 43.1 | 42.1 | 63.0 |
| Laya fine-tuned (cuda) | per column | 29 | 34.0 | 31.7 | 48.8 |
| Gemma (Ollama) | per sheet | 5 | 10632.6 | 11615.3 | 13991.1 |
| Laya zero-shot (cpu) | per column | 29 | 355.5 | 333.0 | 396.2 |
| Laya fine-tuned (cpu) | per column | 29 | 647.3 | 585.4 | 1380.0 |

GPU: NVIDIA GeForce RTX 4060 Laptop GPU. Laya latency is the model call for one column after a warm-up call; Gemma latency is the one request that classifies a whole sheet (a different unit, not comparable per column). Heuristics are not timed.

## Changes made after seeing held-out numbers

None: nothing was changed after the held-out numbers were seen.

## Limits

- The held-out set is small (see its size above), so every accuracy has a wide uncertainty: one column is several percentage points. Treat the numbers as a signal, not a precise estimate.
- It has no column for several roles (listed above), so nothing here says how any classifier does on them. The training pool has no real `retail_price` or `vat_rate` column either.
- Dipel's files share most of their columns, so the number of distinct columns is smaller than the count; DistriLap's lists have no header row, which is a hard case by construction.
- The validation set is partly synthetic and its synthetic share comes from the same generator as the training data, so thresholds calibrated on it can be optimistic for real lists. The real-only precision at each threshold is shown next to it. The held-out test set was never used for calibration or for any choice of threshold or stage order.
- **The heuristics are not a clean baseline on this held-out set.** Their keyword rules, such as the cost-vs-retail modifiers `lista`, `venta` and `sugerido`, were written after the Dipel headers had been seen during exploration and smoke runs. Their 89.7% is therefore optimistic. On the synthetic-heavy validation set, no confidence threshold reached the precision target. Laya and Gemma never saw the held-out distributors.
- The reference labels are one person's judgment (ambiguous columns are noted in `tools/laya/labels.json`).
- Gemma runs at temperature 0 through Ollama with `think: false`; its reported confidence is the model's own number, not a probability.
- Latency depends on this machine (an 8 GB laptop GPU) and on what else it was running.

## Reproduce

```text
uv sync --extra laya
uv run python -m tools.benchmark collect --out bench-results/collect-gpu.json
uv run python -m tools.benchmark collect --device cpu --classifiers laya_zero_shot,laya_finetuned --out bench-results/collect-cpu.json
uv run python -m tools.benchmark calibrate --collect bench-results/collect-gpu.json
uv run python -m tools.benchmark cascade --collect bench-results/collect-gpu.json
uv run python -m tools.benchmark report
```

The raw lists are not committed (`data/raw/`, see `tools/corpus`); Gemma needs `OLLAMA_FLASH_ATTENTION=0 ollama serve`.
