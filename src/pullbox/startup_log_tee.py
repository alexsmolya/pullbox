"""Mirror container stdout/stderr to a rotating startup log file."""

from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO


class StartupLogMirror:
    """Write raw text lines to a rotating log file."""

    def __init__(self, log_file: Path, *, max_bytes: int, backup_count: int) -> None:
        log_file.parent.mkdir(parents=True, exist_ok=True)

        self._logger = logging.getLogger(f"pullbox.startup_tee.{id(self)}")
        self._logger.handlers.clear()
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False

        handler = RotatingFileHandler(
            filename=str(log_file),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.terminator = ""
        self._handler = handler
        self._logger.addHandler(handler)

    def write(self, text: str) -> None:
        """Append text to the rotating log file."""
        if not text:
            return
        record = self._logger.makeRecord(
            self._logger.name,
            logging.INFO,
            __file__,
            0,
            text,
            args=(),
            exc_info=None,
            func=None,
            extra=None,
        )
        self._handler.emit(record)

    def close(self) -> None:
        """Close the underlying file handler."""
        self._handler.close()


def mirror_stream(
    input_stream: TextIO,
    output_stream: TextIO,
    mirror: StartupLogMirror,
) -> None:
    """Copy all incoming lines to stdout and the rotating startup log."""
    for line in input_stream:
        output_stream.write(line)
        output_stream.flush()
        mirror.write(line)


def main() -> None:
    """Run the startup log mirror process."""
    parser = argparse.ArgumentParser(description="Mirror container stdout/stderr to startup.log.")
    parser.add_argument("log_file", help="Path to the startup log file.")
    parser.add_argument(
        "--max-mb",
        type=int,
        default=1,
        help="Maximum log file size in MB before rotation.",
    )
    parser.add_argument(
        "--backup-count",
        type=int,
        default=5,
        help="Number of rotated startup log files to keep.",
    )
    args = parser.parse_args()

    mirror = StartupLogMirror(
        Path(args.log_file),
        max_bytes=args.max_mb * 1024 * 1024,
        backup_count=args.backup_count,
    )
    try:
        mirror_stream(sys.stdin, sys.stdout, mirror)
    finally:
        mirror.close()


if __name__ == "__main__":
    main()
