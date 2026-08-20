"""Portable Uvicorn process entry point for legal_qa_platform."""

from __future__ import annotations

import argparse

import uvicorn

from legal_qa_platform.async_runtime import run_async


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the legal_qa_platform API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--access-log",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable Uvicorn access logging (disabled by default).",
    )
    return parser


async def serve(*, host: str, port: int, access_log: bool) -> int:
    """Serve the ASGI app inside the application-owned event loop."""

    config = uvicorn.Config(
        "legal_qa_platform.api.app:app",
        host=host,
        port=port,
        access_log=access_log,
    )
    server = uvicorn.Server(config)
    await server.serve()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run_async(serve(host=args.host, port=args.port, access_log=args.access_log))


if __name__ == "__main__":
    raise SystemExit(main())
