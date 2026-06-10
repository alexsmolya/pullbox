"""RAR backend configuration for CBR support."""

from __future__ import annotations

from typing import Any


class RarBackendUnavailableError(RuntimeError):
    """Raised when no compatible official UnRAR backend is available."""


def configure_rarfile_backend() -> Any:
    """Configure rarfile to use the official unrar-compatible CLI."""
    try:
        import rarfile  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RarBackendUnavailableError("rarfile package is required for CBR support.") from exc

    rarfile.UNRAR_TOOL = "unrar"
    rarfile.ORIG_UNRAR_TOOL = "unrar"
    rarfile.CURRENT_SETUP = None

    try:
        return rarfile.tool_setup(
            unrar=True,
            unar=False,
            bsdtar=False,
            sevenzip=False,
            sevenzip2=False,
            force=True,
        )
    except rarfile.RarCannotExec as exc:
        raise RarBackendUnavailableError(
            "official UnRAR is required for CBR support but was not found or could not run."
        ) from exc
