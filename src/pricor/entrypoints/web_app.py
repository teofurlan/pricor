"""Serves the built React app next to the API.

`npm --prefix web run build` writes the app to `src/pricor/web_dist/`. The build
output is generated, not committed. When it is missing, `/` answers with a short
plain-text note on how to build it and the API keeps working.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response

DEFAULT_WEB_DIST = Path(__file__).resolve().parent.parent / "web_dist"

# Paths owned by the API: an unknown one is a JSON 404, never the HTML shell.
_API_PREFIXES = frozenset({"imports", "docs", "redoc", "openapi.json"})

_NOT_BUILT = (
    "Pricor is running, but the web app has not been built yet.\n"
    "\n"
    "Build it once with:\n"
    "\n"
    "    npm --prefix web ci\n"
    "    npm --prefix web run build\n"
    "\n"
    "Then reload this page. The API is available meanwhile at /docs.\n"
)


def install_web_app(app: FastAPI, directory: Path) -> None:
    """Add the catch-all routes for the app shell. Call it after the API routes."""
    root = directory.resolve()
    index = root / "index.html"

    @app.get("/", include_in_schema=False)
    def shell() -> Response:
        return _shell(index)

    @app.get("/{path:path}", include_in_schema=False)
    def asset_or_shell(path: str) -> Response:
        if path.split("/", 1)[0] in _API_PREFIXES:
            return JSONResponse(
                {"error": {"code": "not_found", "message": "unknown path"}}, status_code=404
            )
        candidate = (root / path).resolve()
        if candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return _shell(index)


def _shell(index: Path) -> Response:
    if not index.is_file():
        return PlainTextResponse(_NOT_BUILT)
    # The shell names hashed assets, so it must never be cached across rebuilds.
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
