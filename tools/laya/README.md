# Laya training pipeline

Fine-tunes the [Laya](https://huggingface.co/convaiinnovations/laya) `multilingual` checkpoint to pick the **role** of a spreadsheet column from a closed set of ten labels: `code`, `description`, `cost_price`, `retail_price`, `vat_rate`, `units_per_pack`, `barcode`, `discount`, `currency`, `ignore`.

## Install and run

```text
uv sync --extra laya          # laya==0.4.6 and torch 2.14.1 (CUDA 12.6 wheels, about 3 GB)
uv run python -c "import torch; print(torch.cuda.is_available())"

uv run python -m tools.laya.train       # build datasets, fine-tune, write models/laya-pricor/
uv run python -m tools.laya.evaluate    # zero-shot vs fine-tuned on the held-out distributors
```

Run these as modules (`-m`) from the repository root, never as scripts inside `tools/`: a script run from there would let the `tools/laya` package shadow the `laya` library. The base install (`uv sync`) stays torch-free; only training and the Laya classifier need the extra. The raw price lists must be in `data/raw/` (see `tools/corpus`).

Training on an RTX 4060 Laptop (8 GB) uses micro-batch 4, gradient accumulation 2, AMP and gradient checkpointing. Everything is written under `models/laya-pricor/`, which is gitignored: the model, `training_report.json`, `heldout_eval.json` and `datasets/*.jsonl` (these contain sample cell values from real lists, so they are not committed). **Weights are not published from here.**

## What is committed

| File | Content |
|---|---|
| `labels.json` | One hand-assigned role per real column (source id, sheet, column index, header text, role, optional note) plus the header row of each sheet. Headers and notes only, no cell values. Ambiguous columns carry a `note`. |
| `labels.py`, `split.py` | Loading and validation, and the split by distributor. |
| `synth.py` | Seeded synthetic columns. |
| `dataset.py`, `build.py` | Example construction, leakage guard, validation carve-out. |
| `train.py`, `evaluate.py` | The two entry points. |

`dipel-lista-000` (password-protected) and the simulated week-2 files are not labeled.

## State text

A column is serialized by `src/pricor/adapters/laya_state.py`, the module the runtime adapter uses too:

```text
Column header: <header or "(no header)">
Column type: <profiler apparent type>
Sample values: up to 5 values separated by " | "
Stats: numeric=k/n min=.. max=.. avg_len=.. distinct=..
```

Training examples are not formatted by hand: each one is the **profile** of a column (the same `profile_sheet` the app runs), so the type and the samples have exactly the shape the classifier will see. Real columns are augmented by profiling several random row subsets of the sheet (`seed` makes it deterministic); synthetic columns are profiled the same way.

## Split by distributor

Rows are never split randomly. Two whole distributors are held out:

- **Dipel**: three lists, 29 columns with `PRECIO LISTA` and `PRECIO VENTA`, unnamed columns and a header that sits under a contact block.
- **DistriLap**: two lists that have no header row at all.

Training uses the other four distributors (Electricidad Emilio, Distribución Masiva, Bulonera Camba, Megamayorista). Beyond that:

- A training column is dropped when its **exact normalized header** (accents, case, spaces and punctuation removed) equals a held-out header. `CODIGO` and `DESCRIPCION` are held-out headers, so those columns of Emilio and Megamayorista are not trained on.
- The synthetic generator filters the same headers out of its vocabulary. Spelling variants only change case, spacing, punctuation and accents, so one filter covers all of them.
- The **empty header is exempt**: "no header" is a kind of column, and the synthetic header-less examples are how the model learns it.
- `assert_no_leakage` checks both rules before any dataset is returned, and `tests/tools/test_laya_*.py` assert them against the committed labels.
- Validation is carved from the training distributors by header, so no header appears on both sides. It is passed to Laya as its evaluation set. Laya itself calibrates temperature on a random 10% slice of the training file, which is in-sample with respect to headers; the cascade threshold is recalibrated on held-out data in the evaluation task.

## Limits

- The held-out set is 29 columns and has no `vat_rate`, `units_per_pack`, `barcode`, `discount` or `currency` columns. Dipel's two files share most columns, so the effective number of distinct columns is smaller.
- The training pool has no real `retail_price` or `vat_rate` columns: they come from the synthetic generator only. Synthetic examples are labeled synthetic and are not evidence about real lists.
- The reference labels are one person's judgment; the ambiguous cases are marked in `labels.json`. Dipel's `PRECIO VENTA` was first labeled `retail_price`; the user later confirmed it is a supplier calculator (a formula driven by the merchant's DESCUENTO and MARGEN cells), so it is now `ignore` (see `docs/benchmark.md`). Dipel is held out whole, so this label never reached training or validation.
- Accuracy numbers from `evaluate` are a preview. The formal benchmark against the heuristics and Gemma, with calibrated thresholds, is `tools/benchmark`; its results are in `docs/benchmark.md`.
