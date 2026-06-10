"""Tests for diagnostic package ZIP writer helpers."""

from __future__ import annotations

import io
import json
import zipfile

from pullbox.services.diagnostic_package_writer import build_diagnostic_zip


def test_build_diagnostic_zip_writes_json_artifacts_and_logs_directory() -> None:
    zip_bytes = build_diagnostic_zip(
        prefix="pullbox-diagnostic-test",
        json_artifacts={
            "system_info.json": {"python_version": "3.14.0"},
            "config.json": [{"key": "log_level", "value": "info"}],
        },
        binary_artifacts=[],
        log_files=[],
        db_copy=None,
    )

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        assert "pullbox-diagnostic-test/system_info.json" in names
        assert "pullbox-diagnostic-test/config.json" in names
        assert "pullbox-diagnostic-test/logs/" in names
        assert json.loads(zf.read("pullbox-diagnostic-test/system_info.json")) == {
            "python_version": "3.14.0"
        }


def test_build_diagnostic_zip_writes_optional_binary_artifacts_logs_and_db_snapshot() -> None:
    zip_bytes = build_diagnostic_zip(
        prefix="pullbox-diagnostic-test",
        json_artifacts={"system_info.json": {"ok": True}},
        binary_artifacts=[("config_xml.xml", b"<Config />\n")],
        log_files=[("startup.log", b"booted\n")],
        db_copy=b"sqlite-bytes",
    )

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        assert zf.read("pullbox-diagnostic-test/config_xml.xml") == b"<Config />\n"
        assert zf.read("pullbox-diagnostic-test/logs/startup.log") == b"booted\n"
        assert zf.read("pullbox-diagnostic-test/pullbox.db") == b"sqlite-bytes"
