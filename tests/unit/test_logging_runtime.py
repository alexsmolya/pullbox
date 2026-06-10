"""Unit tests for runtime logging sinks and log-surface separation."""

from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING

import structlog

from pullbox.logging import _ApschedulerNoiseFilter, configure_logging

if TYPE_CHECKING:
    from pathlib import Path


def _read_json_lines(path: Path) -> list[dict[str, object]]:
    lines = [line for line in path.read_text().splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def _flush_logger_handlers(*logger_names: str) -> None:
    for logger_name in logger_names:
        target = logging.getLogger(logger_name)
        for handler in target.handlers:
            handler.flush()


class TestLoggingRuntime:
    """Verify root and dedicated workflow log files stay intentionally separated."""

    def test_apscheduler_max_instances_warning_is_filtered(self) -> None:
        aps_filter = _ApschedulerNoiseFilter()
        noisy_message = (
            'Execution of job "monitor_downloads" skipped: '
            "maximum number of running instances reached (1)"
        )
        noisy = logging.LogRecord(
            name="apscheduler.scheduler",
            level=logging.WARNING,
            pathname=__file__,
            lineno=1,
            msg=noisy_message,
            args=(),
            exc_info=None,
        )
        useful = logging.LogRecord(
            name="apscheduler.scheduler",
            level=logging.WARNING,
            pathname=__file__,
            lineno=1,
            msg='Scheduler "default" started',
            args=(),
            exc_info=None,
        )

        assert aps_filter.filter(noisy) is False
        assert aps_filter.filter(useful) is True

    def test_import_detail_writes_to_imports_log_not_root_log(self, tmp_path: Path) -> None:
        logging.getLogger("pullbox.imports").disabled = True

        configure_logging("INFO", debug=False, logs_dir=tmp_path)

        imports_logger = logging.getLogger("pullbox.imports")
        assert imports_logger.disabled is False
        assert imports_logger.propagate is False
        assert any(
            isinstance(handler, RotatingFileHandler)
            and handler.baseFilename == str(tmp_path / "imports.log")
            for handler in imports_logger.handlers
        )

        # This test is about stdlib logger routing. Using stdlib logging keeps
        # the assertion independent of structlog's process-global capture/cache state.
        imports_logger.info("import_scan_series_detail")
        logging.getLogger("pullbox.tests").info("runtime_summary")
        _flush_logger_handlers("", "pullbox.imports")

        imports_entries = _read_json_lines(tmp_path / "imports.log")
        root_entries = _read_json_lines(tmp_path / "pullbox.log")

        assert any(entry["event"] == "import_scan_series_detail" for entry in imports_entries)
        assert not any(entry["event"] == "import_scan_series_detail" for entry in root_entries)
        assert any(entry["event"] == "runtime_summary" for entry in root_entries)

    def test_exception_traceback_text_is_sanitized(self, tmp_path: Path) -> None:
        configure_logging("INFO", debug=False, logs_dir=tmp_path)

        try:
            raise ValueError("provider failed with api_key=super-secret\nnext-line")
        except ValueError:
            structlog.get_logger("pullbox.tests").exception(
                "provider_failure",
                endpoint="http://indexer.test/api?apikey=query-secret",
            )

        _flush_logger_handlers("")
        [entry] = _read_json_lines(tmp_path / "pullbox.log")

        assert entry["endpoint"] == "http://indexer.test/api?apikey=***REDACTED***"
        exception = entry["exception"]
        assert isinstance(exception, str)
        assert "super-secret" not in exception
        assert "query-secret" not in exception
        assert "api_key=***REDACTED***" in exception
        assert "\\nnext-line" in exception
        assert "\nnext-line" not in exception
