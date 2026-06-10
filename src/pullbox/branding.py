"""ASCII branding helpers for terminal and startup surfaces."""

from __future__ import annotations

import os

import pullbox

_BANNER_LINES = (
    r"   _ _ _ _ _         ____   _   _  _      _      ____    ___   __  __    ",
    r"  | | | | | |       |  _ \ | | | || |    | |    | __ )  / _ \  \ \/ /    ",
    r"  | | | | | |       | |_) || | | || |    | |    |  _ \ | | | |  \  /     ",
    r"  | | | | | |       |  __/ | |_| || |___ | |___ | |_) || |_| |  /  \     ",
    r"  |_|_|_|_|_|       |_|     \___/ |_____||_____||____/  \___/  /_/\_\    ",
    r" /_____________\                                                         ",
    r" \_____________/    comic book management & acquisition                  ",
)


def _pad_to_width(lines: tuple[str, ...], width: int) -> tuple[str, ...]:
    """Right-pad every line to a fixed width so the block stays rectangular."""
    return tuple(line.ljust(width)[:width] for line in lines)


def display_version() -> str:
    """Return the best available user-facing version string."""
    return str(os.environ.get("PULLBOX_BUILD_VERSION") or pullbox.__version__).strip()


def startup_banner(version: str | None = None, *, width: int = 80) -> str:
    """Return the Pullbox startup banner as a multi-line string."""
    lines = list(_pad_to_width(_BANNER_LINES, width))
    version_text = (version or "").strip()
    if version_text:
        lines.append(f"    v{version_text}".ljust(width)[:width])
    return "\n".join(lines)


__all__ = ["display_version", "startup_banner"]
