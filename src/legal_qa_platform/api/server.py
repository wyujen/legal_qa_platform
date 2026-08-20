"""Portable Uvicorn process entry point for legal_qa_platform."""

from __future__ import annotations

import argparse

import uvicorn
from pydantic import ValidationError

from legal_qa_platform.api.app import create_app
from legal_qa_platform.async_runtime import run_async
from legal_qa_platform.config import (
    ENDPOINT_SCOPE_CHOICES,
    RuntimeSettings,
    missing_for_runtime_scope,
    runtime_endpoint_families,
    select_endpoint_scope,
)
from legal_qa_platform.errors import ConfigurationError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the legal_qa_platform API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--endpoint-scope",
        choices=ENDPOINT_SCOPE_CHOICES,
        default="auto",
        help=(
            "Select runtime endpoint families. 'auto' keeps internal-first "
            "precedence; no endpoint values are accepted."
        ),
    )
    parser.add_argument(
        "--access-log",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable Uvicorn access logging (disabled by default).",
    )
    return parser


async def serve(
    *,
    settings: RuntimeSettings,
    host: str,
    port: int,
    access_log: bool,
) -> int:
    """Serve the ASGI app inside the application-owned event loop."""

    application = create_app(settings=settings)
    config = uvicorn.Config(
        application,
        host=host,
        port=port,
        access_log=access_log,
    )
    server = uvicorn.Server(config)
    await server.serve()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = select_endpoint_scope(RuntimeSettings(), args.endpoint_scope)
    except (ValueError, ValidationError):
        print("[FAIL] runtime configuration is invalid; check documented types.")
        return 2
    families = runtime_endpoint_families(settings)
    print(
        "[INFO] API endpoint selection "
        f"scope={args.endpoint_scope} "
        f"postgres={families.postgres} "
        f"qdrant={families.qdrant} "
        f"litellm={families.litellm}"
    )
    missing = missing_for_runtime_scope(settings, args.endpoint_scope)
    if missing:
        print("[SKIP] required environment variable names are missing:")
        for name in missing:
            print(f"  - {name}")
        print(
            "Human Operator: inject these variables into the current process, "
            "then rerun the API command."
        )
        return 2
    try:
        settings.require_runtime()
    except ConfigurationError:
        print("[FAIL] API runtime configuration category=endpoint_contract_invalid")
        return 2
    return run_async(
        serve(
            settings=settings,
            host=args.host,
            port=args.port,
            access_log=args.access_log,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
