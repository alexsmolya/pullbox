"""Local development launcher with runtime-parity config resolution."""

from __future__ import annotations

import argparse
import os

import uvicorn

from pullbox.__main__ import _resolve_db_path, ensure_host_secret
from pullbox.config import get_settings
from pullbox.core.https_runtime import (
    resolve_https_runtime_settings,
    uvicorn_ssl_kwargs,
    validate_https_runtime_settings,
)


def main() -> None:
    """Start the local development server with the normal runtime semantics."""
    os.environ.setdefault("PULLBOX_STARTUP_UPDATE_CHECK_ENABLED", "false")
    os.environ.setdefault("PULLBOX_DEV_AUTO_MIGRATE", "true")

    parser = argparse.ArgumentParser(description="Run Pullbox in local development mode.")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable uvicorn auto-reload.",
    )
    args = parser.parse_args()

    settings = get_settings()
    ensure_host_secret(settings.data_dir, db_path=_resolve_db_path(settings.db_url))
    https_settings = resolve_https_runtime_settings(settings=settings)
    validate_https_runtime_settings(https_settings)

    uvicorn.run(
        "pullbox.app:create_app",
        host=settings.bind_address,
        port=settings.port,
        factory=True,
        reload=args.reload,
        **uvicorn_ssl_kwargs(https_settings),
    )


if __name__ == "__main__":
    main()
