# Benchmark: column classifiers and cascade

Generated 2026-10-14T19:24:22 on NVIDIA GeForce RTX 4060 Laptop GPU. Raw answers are in `bench-results/` (not committed).

## Method

Each classifier assigns one of ten roles to every labeled column of a supplier price list. All of them receive the same deterministic column profile: Laya reads the serialized state (`src/pricor/adapters/laya_state.py`), the heuristics and Gemma read the profile directly.

- **Heuristics:** keyword and type rules.
- **Laya zero-shot:** the `multilingual` base checkpoint, no fine-tuning.
- **Laya fine-tuned:** that checkpoint fine-tuned on the training distributors plus synthetic columns (`tools/laya`).
- **Gemma:** `gemma4:e4b` through Ollama, one request per sheet.
- **Agreement:** a cascade stage that runs the heuristics and fine-tuned Laya together and settles a column only when both pick the same role (optionally also requiring that at least one of them reaches a calibrated confidence).
- **Cascade:** the application's own stages with calibrated thresholds; a column a stage scores at or above its threshold is settled, the rest go on, and what is left goes to the user.

## Data

- **Validation set:** 161 columns carved from the training distributors (header-disjoint from training; real resamples plus synthetic columns). Used only to calibrate thresholds.
- **Held-out test set:** 29 labeled columns of Dipel and DistriLap, profiled whole-sheet like the app does (code 5, description 5, cost_price 4, retail_price 1, ignore 14). Roles with no held-out column: vat_rate, units_per_pack, barcode, discount, currency.

## Held-out results

| Classifier | Columns | Correct | Accuracy |
|---|---|---|---|
| Heuristics | 29 | 24 | 82.8% |
| Laya zero-shot | 29 | 18 | 62.1% |
| Laya fine-tuned | 29 | 22 | 75.9% |
| Gemma | 29 | 25 | 86.2% |

| Label | Support | Heuristics (P / R) | Laya zero-shot (P / R) | Laya fine-tuned (P / R) | Gemma (P / R) |
|---|---|---|---|---|---|
| code | 5 | 1.00 / 0.60 | 1.00 / 0.60 | 1.00 / 0.60 | 1.00 / 1.00 |
| description | 5 | 1.00 / 1.00 | 1.00 / 0.80 | 1.00 / 0.80 | 0.71 / 1.00 |
| cost_price | 4 | 0.80 / 1.00 | n/a / 0.00 | 1.00 / 0.50 | 1.00 / 1.00 |
| retail_price | 1 | 0.33 / 1.00 | 0.20 / 1.00 | 0.14 / 1.00 | 0.33 / 1.00 |
| vat_rate | 0 | n/a / n/a | 0.00 / n/a | n/a / n/a | n/a / n/a |
| barcode | 0 | n/a / n/a | 0.00 / n/a | n/a / n/a | n/a / n/a |
| currency | 0 | n/a / n/a | 0.00 / n/a | n/a / n/a | n/a / n/a |
| ignore | 14 | 0.85 / 0.79 | 0.83 / 0.71 | 0.92 / 0.86 | 1.00 / 0.71 |

P is precision and R is recall; `n/a` means the label was never predicted (P) or never occurs (R).

## Calibration

Method: lowest validation confidence whose accepted answers (score >= threshold) have precision >= 0.95 with support >= 20. Calibrated on 2026-10-14 on 161 validation columns (48 real resamples, 113 synthetic).

| Stage | Threshold | Validation n | Accepted | Precision of accepted | Real only (accepted / precision) | Note |
|---|---|---|---|---|---|---|
| heuristics | not calibrated | 161 | 0 | n/a | n/a | no threshold meets the target precision with the minimum support |
| laya | 0.9959 | 161 | 42 | 97.6% | 1 / 0.0% | met |
| gemma | 0.9800 | 161 | 37 | 100.0% | 6 / 100.0% | met |
| agreement | 0.9959 | 108 agreed | 31 | 96.8% | n/a | met; precision of the agreed answers is 88.0% without a confidence bar, and the threshold is a bar the higher of the two scores must reach |

## Cascade on the held-out set

Order: `laya>gemma` (decided on the validation set, see below). Thresholds in force: laya 0.9959, gemma 0.9800. This is the application's own cascade run over whole held-out sheets, so Gemma only sees the columns the earlier stage left over.

| Settled by | Columns | Share |
|---|---|---|
| Laya | 3 | 10.3% |
| Gemma | 8 | 27.6% |
| User | 18 | 62.1% |

Automatically settled: 11 of 29, of which 10 are correct (**90.9%**). Escalated to the user: 18 (escalation rate 62.1%); the best-scoring proposal was right for 15 of them.

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
| `agreement>laya>gemma` | 61.5% | 98.4% |
| `agreement>heuristics>laya>gemma` | 33.5% | 88.8% |
| `agreement>laya>heuristics>gemma` | 33.5% | 88.8% |
| `agreement>gemma` | 67.7% | 98.1% |

Held-out set (informational only, not used for the decision; replayed from cached answers, so Gemma saw whole sheets here instead of only the leftovers):

| Order | Escalated to user | Accuracy of automatic answers |
|---|---|---|
| `laya>gemma` (default) | 62.1% | 100.0% |
| `heuristics>laya>gemma` | 37.9% | 88.9% |
| `laya>heuristics>gemma` | 37.9% | 88.9% |
| `heuristics>gemma` | 37.9% | 88.9% |
| `laya` | 89.7% | 100.0% |
| `heuristics` | 55.2% | 84.6% |
| `gemma` | 72.4% | 100.0% |
| `agreement>laya>gemma` | 62.1% | 100.0% |
| `agreement>heuristics>laya>gemma` | 37.9% | 88.9% |
| `agreement>laya>heuristics>gemma` | 37.9% | 88.9% |
| `agreement>gemma` | 62.1% | 100.0% |

## Latency

| Classifier | Unit | Calls | Mean ms | Median ms | p95 ms |
|---|---|---|---|---|---|
| Heuristics | per column | 0 | n/a | n/a | n/a |
| Laya zero-shot (cuda) | per column | 29 | 35.7 | 34.9 | 40.7 |
| Laya fine-tuned (cuda) | per column | 29 | 35.4 | 34.0 | 38.7 |
| Gemma (Ollama) | per sheet | 5 | 11408.1 | 12578.4 | 16081.9 |
| Laya zero-shot (cpu) | per column | 29 | 464.9 | 458.8 | 538.9 |
| Laya fine-tuned (cpu) | per column | 29 | 516.5 | 490.9 | 768.9 |

GPU: NVIDIA GeForce RTX 4060 Laptop GPU. Laya latency is the model call for one column after a warm-up call; Gemma latency is the one request that classifies a whole sheet (a different unit, not comparable per column). Heuristics are not timed.

## Changes made after seeing held-out numbers

- **1. Label correction (post hoc).** After the first held-out run the user confirmed that Dipel's `PRECIO VENTA` is not list data but a calculator the supplier gives the merchant: an Excel formula column driven by the DESCUENTO and MARGEN input cells (rows 14-15), with the instruction in row 11 to load your own margin to use it as the public price. Both entries (`dipel-lista-pagina-web` LISTA and `dipel-haga-su-pedido` Hoja1) were relabeled from `retail_price` to `ignore` in `tools/laya/labels.json`. This is a correction of the test labels made after seeing held-out results; the numbers above use the corrected labels.
- Effect of the relabeling on held-out accuracy. The heuristics, fine-tuned Laya and Gemma had all labeled both columns `retail_price`, so each loses two correct answers: Heuristics 26/29 to 24/29 (89.7% to 82.8%), Laya fine-tuned 24/29 to 22/29 (82.8% to 75.9%), Gemma 27/29 to 25/29 (93.1% to 86.2%). Zero-shot Laya had labeled both `ignore`, so it gains two: 16/29 to 18/29 (55.2% to 62.1%). Laya was not retrained: Dipel is held out whole, so none of its columns, including these two, is in the training or validation data (checked by `tests/tools/test_laya_labels.py`).
- **2. Agreement stage (post hoc).** The agreement stage (heuristics and fine-tuned Laya settle a column when they pick the same role) was designed after seeing the held-out results, to cut the share of columns escalated to the user. It was calibrated and its position in the cascade was chosen on the validation set only, with the same method and parameters as the other stages (target precision 0.95, minimum support 20). The heuristics' advantage on this held-out set is inflated (see Limits), so the agreement stage's held-out result is likely optimistic too.
- Outcome of the agreement stage: on validation the two classifiers agree on 108 of 161 columns, but only 88.0% of those answers are right, below the target. Requiring a confidence bar reaches the target only at 0.9959, which is Laya's own threshold, where the stage settles 31 columns at 96.8% precision (a subset of the 42 columns Laya alone settles at 97.6%). So `agreement>laya>gemma` ties `laya>gemma` on validation (61.5% escalated, 98.4% accurate); the tie keeps the default order, and the shipped cascade does not include the agreement stage. On the held-out set it also ties (62.1% escalated), so the escalation rate is unchanged.
- In the second run the cascade settled Gemma 8 columns instead of 9. No label of a column Gemma settled changed, so this is not an effect of the relabeling; it is most likely run-to-run variation of the model (an inference, not checked).

## Previous run

- First run, before any post-hoc change (2026-10-14): held-out accuracy was Heuristics 26/29 (89.7%), Laya zero-shot 16/29 (55.2%), Laya fine-tuned 24/29 (82.8%) and Gemma 27/29 (93.1%), with 3 `retail_price` columns.
- Its cascade (`laya>gemma`) settled Laya 3, Gemma 9 and the user 17 columns (58.6% escalated); 12 columns were settled automatically and 11 of them were correct (91.7%).
- The validation set, the calibration and the chosen order are identical to that run; only the two Dipel `PRECIO VENTA` reference labels changed, and the classifiers were re-run once.

## Limits

- The held-out set is small (see its size above), so every accuracy has a wide uncertainty: one column is several percentage points. Treat the numbers as a signal, not a precise estimate.
- It has no column for several roles (listed above), so nothing here says how any classifier does on them. The training pool has no real `retail_price` or `vat_rate` column either.
- Dipel's files share most of their columns, so the number of distinct columns is smaller than the count; DistriLap's lists have no header row, which is a hard case by construction.
- The validation set is partly synthetic and its synthetic share comes from the same generator as the training data, so thresholds calibrated on it can be optimistic for real lists. The real-only precision at each threshold is shown next to it. The held-out test set was never used for calibration or for any choice of threshold or stage order.
- **The heuristics are not a clean baseline on this held-out set.** Their keyword rules, such as the cost-vs-retail modifiers `lista`, `venta` and `sugerido`, were written after the Dipel headers had been seen during exploration and smoke runs. Their held-out score is therefore optimistic. On the synthetic-heavy validation set, no confidence threshold reached the precision target. Laya and Gemma never saw the held-out distributors. Any stage that leans on the heuristics, the agreement stage included, inherits that advantage.
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
