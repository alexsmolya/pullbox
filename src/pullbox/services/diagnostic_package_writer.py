"""Diagnostic package ZIP writing helpers."""

from __future__ import annotations

import io
import json
import zipfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


def build_diagnostic_zip(
    *,
    prefix: str,
    json_artifacts: Mapping[str, object],
    binary_artifacts: Iterable[tuple[str, bytes]],
    log_files: Iterable[tuple[str, bytes]],
    db_copy: bytes | None,
) -> bytes:
    """Build the diagnostic ZIP bytes from collected artifacts."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, payload in json_artifacts.items():
            zf.writestr(
                f"{prefix}/{name}",
                json.dumps(payload, indent=2, default=str),
            )

        for name, content in binary_artifacts:
            zf.writestr(f"{prefix}/{name}", content)

        if db_copy is not None:
            zf.writestr(f"{prefix}/pullbox.db", db_copy)

        # Always create the logs/ directory entry, even if no log files were found.
        zf.mkdir(f"{prefix}/logs")
        for log_name, log_content in log_files:
            zf.writestr(f"{prefix}/logs/{log_name}", log_content)

    return buf.getvalue()
