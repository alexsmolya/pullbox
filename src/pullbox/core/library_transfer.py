"""Low-level library file transfer helpers."""

from __future__ import annotations

import os
import shutil
import time
from contextlib import suppress
from typing import TYPE_CHECKING

import structlog

from pullbox.core.exceptions import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = structlog.get_logger(__name__)

_TRANSFER_SOURCE_RETRY_DELAYS = (0.0, 0.5, 1.0, 2.0, 4.0)


def copy_with_retries(src: Path, dst: Path, *, preserve_metadata: bool) -> None:
    """Copy a file with brief retries for shared-storage visibility glitches."""
    copier = shutil.copy2 if preserve_metadata else shutil.copy
    total_attempts = len(_TRANSFER_SOURCE_RETRY_DELAYS)

    for attempt, delay_seconds in enumerate(_TRANSFER_SOURCE_RETRY_DELAYS, start=1):
        if delay_seconds:
            time.sleep(delay_seconds)
        try:
            copier(str(src), str(dst))
            return
        except FileNotFoundError:
            with suppress(FileNotFoundError):
                dst.unlink()
            if attempt >= total_attempts:
                raise
            logger.warning(
                "library_transfer_source_retry",
                source=str(src),
                destination=str(dst),
                attempt=attempt,
                total_attempts=total_attempts,
                preserve_metadata=preserve_metadata,
                hint=(
                    "Source was not readable during transfer. Retrying briefly to "
                    "tolerate shared/network storage visibility delays."
                ),
            )


def safe_move(src: Path, dst: Path) -> None:
    """Move a file, retrying cross-device copy fallbacks for flaky mounts."""
    try:
        os.rename(src, dst)
        return
    except OSError as exc:
        if exc.errno != 18:  # Cross-device link
            raise

    copy_with_retries(src, dst, preserve_metadata=False)
    remove_source_if_present(src)


def remove_source_if_present(src: Path) -> None:
    """Best-effort source cleanup after a successful transfer."""
    try:
        src.unlink()
    except FileNotFoundError:
        return


def transfer_into_library(
    src: Path,
    dst: Path,
    method: str,
    progress_callback: Callable[[int, int], None] | None = None,
) -> None:
    """Place a file into the library using the configured transfer method."""
    if method in {"move", "copy"} and progress_callback is not None:
        import threading

        total_bytes = src.stat().st_size
        monitor_stop = threading.Event()

        def _sample_transfer_progress() -> None:
            last_reported = -1
            while not monitor_stop.wait(0.25):
                try:
                    transferred = min(dst.stat().st_size, total_bytes)
                except FileNotFoundError:
                    transferred = 0
                if transferred == last_reported:
                    continue
                last_reported = transferred
                progress_callback(transferred, total_bytes)

            try:
                transferred = min(dst.stat().st_size, total_bytes)
            except FileNotFoundError:
                transferred = total_bytes if dst.exists() else 0
            progress_callback(transferred, total_bytes)

        progress_callback(0, total_bytes)
        monitor_thread = threading.Thread(
            target=_sample_transfer_progress,
            name="pullbox-transfer-progress",
            daemon=True,
        )
        monitor_thread.start()
        try:
            transfer_into_library(src, dst, method, None)
        finally:
            monitor_stop.set()
            monitor_thread.join(timeout=1.0)
        return

    match method:
        case "move":
            safe_move(src, dst)
        case "copy":
            copy_with_retries(src, dst, preserve_metadata=True)
        case "hardlink":
            os.link(str(src), str(dst))
        case "symlink":
            os.symlink(str(src), str(dst))
        case _:
            raise ConfigurationError(f"Unsupported transfer method: {method}")
