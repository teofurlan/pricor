"""Command line entry point: `pricor serve [--host H] [--port P]` starts the API."""

import argparse


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pricor")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="run the HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    import uvicorn

    uvicorn.run(
        "pricor.entrypoints.wiring:app_from_env", factory=True, host=args.host, port=args.port
    )
