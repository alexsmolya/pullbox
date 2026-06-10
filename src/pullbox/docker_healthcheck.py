"""Docker healthcheck entry point that does not require curl."""

from __future__ import annotations

import os
import ssl
import sys
from http.client import HTTPConnection, HTTPSConnection

from pullbox.core.https_runtime import resolve_https_runtime_settings


def _healthcheck_port() -> int:
    """Read and validate the local Pullbox port from runtime environment."""
    try:
        port = int(os.environ.get("PULLBOX_PORT", "8585"))
    except ValueError:
        return 8585
    return port if 1 <= port <= 65535 else 8585


def main() -> None:
    """Exit successfully only when the local Pullbox ping endpoint is healthy."""
    https_settings = resolve_https_runtime_settings()
    connection: HTTPConnection
    if https_settings.enabled:
        connection = HTTPSConnection(
            "127.0.0.1",
            _healthcheck_port(),
            timeout=5,
            context=ssl._create_unverified_context(),
        )
    else:
        connection = HTTPConnection("127.0.0.1", _healthcheck_port(), timeout=5)
    try:
        connection.request("GET", "/ping", headers={"Accept": "application/json"})
        response = connection.getresponse()
        if response.status == 200:
            return
    except OSError:
        pass
    finally:
        connection.close()
    sys.exit(1)


if __name__ == "__main__":
    main()
