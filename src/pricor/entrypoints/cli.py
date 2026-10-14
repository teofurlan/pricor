"""Command line entry point.

    pricor                     serve on http://127.0.0.1:8000 and open the browser
    pricor --no-browser        serve only
    pricor serve --port 9000   the same options, spelled with the subcommand

If the default port is busy, a free one is used. An explicit `--port` is never
replaced: if it is busy the command stops and says so.
"""

import argparse
import socket
import sys
import threading
import time
import webbrowser
from collections.abc import Callable, Sequence

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
_STARTUP_WAIT_SECONDS = 60

ServeFunction = Callable[[str, int, Callable[[], None]], None]


def _can_bind(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def find_free_port(host: str, preferred: int | None = None) -> int:
    """`preferred` when it can be bound, otherwise a port the system hands out."""
    if preferred is not None and _can_bind(host, preferred):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return probe.getsockname()[1]


def _serve(host: str, port: int, on_started: Callable[[], None]) -> None:
    import uvicorn

    config = uvicorn.Config(
        "pricor.entrypoints.wiring:app_from_env", factory=True, host=host, port=port
    )
    server = uvicorn.Server(config)

    def announce() -> None:
        deadline = time.monotonic() + _STARTUP_WAIT_SECONDS
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        if server.started:
            on_started()

    threading.Thread(target=announce, daemon=True).start()
    server.run()


def _add_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument(
        "--port", type=int, default=None, help=f"port to listen on (default {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="do not open the browser"
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    serve: ServeFunction = _serve,
    open_browser: Callable[[str], object] = webbrowser.open,
    preferred_port_is_free: Callable[[str, int], bool] = _can_bind,
) -> None:
    parser = argparse.ArgumentParser(prog="pricor", description="Pricor price list importer")
    _add_options(parser)
    commands = parser.add_subparsers(dest="command")
    _add_options(commands.add_parser("serve", help="run the app (the default command)"))
    args = parser.parse_args(argv)

    if args.port is not None:
        port = args.port
        if not preferred_port_is_free(args.host, port):
            parser.exit(1, f"pricor: port {port} on {args.host} is already in use\n")
    elif preferred_port_is_free(args.host, DEFAULT_PORT):
        port = DEFAULT_PORT
    else:
        port = find_free_port(args.host)

    url = f"http://{args.host}:{port}/"

    def started() -> None:
        print(f"Pricor is running at {url}", file=sys.stderr, flush=True)
        if not args.no_browser:
            open_browser(url)

    serve(args.host, port, started)
