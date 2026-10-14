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
