from __future__ import annotations

from io import StringIO

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
