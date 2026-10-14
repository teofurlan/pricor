# Pricor

Pricor turns heterogeneous supplier price lists (Excel/CSV) from Argentine stores into a normalized catalog. Models propose an import plan from a closed catalog of operations, and a deterministic engine executes it with exact decimal math, so no model ever touches the numbers.

## Running the tests

```text
uv run pytest
```

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

## Running the API

Pricor serves the first-import flow over HTTP (FastAPI):

```text
uv run pricor serve                      # http://127.0.0.1:8000, docs at /docs
uv run uvicorn pricor.entrypoints.wiring:app_from_env --factory --port 8000
```

The endpoints and the session flow are documented in the docstring of `src/pricor/entrypoints/api.py`.
Uploads accept `.csv`, `.xlsx`, `.xlsm` and `.xls` up to 20 MB.

### Storage (SQLite)

Sessions, approved supplier plans and the price history live in one SQLite file (standard library `sqlite3`, no server). Settings:

| Variable | Default |
|---|---|
| `PRICOR_DB` | `%LOCALAPPDATA%\Pricor\pricor.db` on Windows, `$XDG_DATA_HOME/pricor/pricor.db` if set, otherwise `./pricor.db` |

The schema is versioned (`schema_version` table) and migrated at startup; a file written by a newer Pricor is refused. Approving an import stores the plan version, the accepted records and the session state in a single transaction. Plans are never overwritten: each approval adds a version. Prices are stored as exact decimal text.

### Exports

Once a session is approved, `GET /imports/{id}/export?format=csv|xlsx` returns the products and `GET /imports/{id}/rejected?format=csv|xlsx` the rejected-rows report (409 before approval).

- Columns, in this order: `supplier_code, description, unit_cost_net, currency, vat_rate, units_per_pack, barcode, suggested_retail_price`, then `source_row` (the row number in the supplier's file). The rejected report is `source_row, reasons`, then the original cells under the file's own headers.
- CSV: UTF-8 with BOM, `,` delimiter, CRLF, RFC 4180 quoting, `.` as decimal separator, values written as exact text (`855.00`). Excel with a `;` list separator (es-AR) splits `;` CSVs by default; use `CsvExporter(delimiter=";")` if that is your setup. Excel drops the leading zeros of codes in CSV files it opens directly: use the XLSX export for that.
- XLSX: sheets `Products` and `Rejected rows` (the standalone rejected report has only the second one). Codes, barcodes and original cells are text cells; prices and rates are numeric cells. A number with more than 15 significant digits is written as text instead of being rounded.
- Text that spreadsheet software could run as a formula (`=`, `+`, `-`, `@` at the start) is stored as text in XLSX and prefixed with `'` in CSV; plain numbers such as `-123` are left alone.

### Models (Ollama)

Column classification and question suggestions use Gemma through a local [Ollama](https://ollama.com) server. Settings:

| Variable | Default |
|---|---|
| `PRICOR_OLLAMA_URL` | `http://localhost:11434` |
| `PRICOR_OLLAMA_MODEL` | `gemma4:e4b` |
| `PRICOR_OLLAMA_TIMEOUT` | `180` (seconds per model call) |

`gemma4:e4b` crashes with flash attention on the tested setup (`fattn.cu:110`). Start Ollama with it disabled:

```text
OLLAMA_FLASH_ATTENTION=0 ollama serve
```

If Ollama is down, slow or returns something invalid, the import continues with the heuristic classifier only: the user confirms the uncertain columns, every open plan parameter is asked, and the session shows a `model_unavailable` notice.

**Model output is never executed.** A model can only pick a role for a column from a closed list and suggest an answer to a question. Questions and their options are deterministic, a suggestion is never applied until the user answers, and the import plan is built and run by deterministic code with exact decimal math. The confidence thresholds that decide which columns are shown to the user are placeholders until they are calibrated on held-out data.

## License

Copyright 2026 The Pricor Authors. Licensed under Apache-2.0; see `LICENSE`.
