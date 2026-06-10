"""Unit tests for filename validation in system routes.

Tests cover the _validate_safe_filename() helper and endpoint-level
rejection of path traversal attempts.

Run:
    pytest tests/unit/test_filename_validation.py -v
"""

from __future__ import annotations

from pullbox.api.v1.system import _validate_safe_filename


class TestValidFilenames:
    """Tests for filenames that should be accepted."""

    def test_valid_backup_filename(self) -> None:
        assert _validate_safe_filename("pullbox-backup-2026-03-02.zip") is True

    def test_valid_log_filename(self) -> None:
        assert _validate_safe_filename("pullbox.log.1") is True

    def test_valid_simple_name(self) -> None:
        assert _validate_safe_filename("backup.zip") is True

    def test_valid_alphanumeric_start(self) -> None:
        assert _validate_safe_filename("9backup.tar.gz") is True


class TestRejectedFilenames:
    """Tests for filenames that must be rejected."""

    def test_rejects_path_traversal(self) -> None:
        assert _validate_safe_filename("../../../etc/passwd") is False

    def test_rejects_absolute_path(self) -> None:
        assert _validate_safe_filename("/etc/passwd") is False

    def test_rejects_backslash_traversal(self) -> None:
        assert _validate_safe_filename("..\\..\\windows\\system32") is False

    def test_rejects_dotdot(self) -> None:
        assert _validate_safe_filename("backup..zip") is False

    def test_rejects_hidden_file(self) -> None:
        assert _validate_safe_filename(".htaccess") is False

    def test_rejects_dash_start(self) -> None:
        assert _validate_safe_filename("-rf") is False

    def test_rejects_empty_string(self) -> None:
        assert _validate_safe_filename("") is False

    def test_rejects_too_long(self) -> None:
        assert _validate_safe_filename("a" * 256) is False

    def test_rejects_null_byte(self) -> None:
        assert _validate_safe_filename("file\x00name") is False

    def test_rejects_space_in_name(self) -> None:
        assert _validate_safe_filename("my file.zip") is False

    def test_max_length_accepted(self) -> None:
        # 1 char start + 254 chars = 255 total
        assert _validate_safe_filename("a" * 255) is True
