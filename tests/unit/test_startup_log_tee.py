from __future__ import annotations

import runpy
import sys
from io import StringIO

from pullbox import startup_log_tee
from pullbox.startup_log_tee import StartupLogMirror, mirror_stream


def test_mirror_stream_writes_stdout_and_startup_log(tmp_path) -> None:
    log_file = tmp_path / "startup.log"
    mirror = StartupLogMirror(log_file, max_bytes=1024, backup_count=1)
    output = StringIO()
    try:
        mirror_stream(StringIO("one\nTwo\n"), output, mirror)
    finally:
        mirror.close()

    assert output.getvalue() == "one\nTwo\n"
    assert log_file.read_text(encoding="utf-8") == "one\nTwo\n"


def test_startup_log_mirror_ignores_empty_writes(tmp_path) -> None:
    log_file = tmp_path / "startup.log"
    mirror = StartupLogMirror(log_file, max_bytes=1024, backup_count=1)
    try:
        mirror.write("")
    finally:
        mirror.close()

    assert log_file.read_text(encoding="utf-8") == ""


def test_startup_log_rotates(tmp_path) -> None:
    log_file = tmp_path / "startup.log"
    mirror = StartupLogMirror(log_file, max_bytes=32, backup_count=1)
    try:
        for index in range(8):
            mirror.write(f"line-{index}\n")
    finally:
        mirror.close()

    assert log_file.exists()
    assert (tmp_path / "startup.log.1").exists()


def test_main_mirrors_stdin_to_stdout_and_startup_log(tmp_path, monkeypatch) -> None:
    log_file = tmp_path / "startup.log"
    stdout = StringIO()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "startup-log-tee",
            str(log_file),
            "--max-mb",
            "1",
            "--backup-count",
            "1",
        ],
    )
    monkeypatch.setattr(sys, "stdin", StringIO("booting\nready\n"))
    monkeypatch.setattr(sys, "stdout", stdout)

    startup_log_tee.main()

    assert stdout.getvalue() == "booting\nready\n"
    assert log_file.read_text(encoding="utf-8") == "booting\nready\n"


def test_module_entrypoint_mirrors_stdin_to_stdout_and_startup_log(tmp_path, monkeypatch) -> None:
    log_file = tmp_path / "startup-entrypoint.log"
    stdout = StringIO()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "startup-log-tee",
            str(log_file),
            "--max-mb",
            "1",
            "--backup-count",
            "1",
        ],
    )
    monkeypatch.setattr(sys, "stdin", StringIO("entrypoint\n"))
    monkeypatch.setattr(sys, "stdout", stdout)

    runpy.run_path(startup_log_tee.__file__, run_name="__main__")

    assert stdout.getvalue() == "entrypoint\n"
    assert log_file.read_text(encoding="utf-8") == "entrypoint\n"
