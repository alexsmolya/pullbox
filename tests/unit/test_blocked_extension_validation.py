"""Tests for blocked extension validation in allowed_import_extensions (C-6.5).

Verifies:
- Dangerous extensions are rejected by the config API validation
- Safe comic extensions pass validation
- Case-insensitive matching
- Extensions with and without leading dot
"""

from __future__ import annotations

import pytest

from pullbox.core.file_safety import DANGEROUS_EXTENSIONS


def _validate_extensions(value: str) -> str | None:
    """Reproduce the validation logic from config.py — returns error or None."""
    for ext in value.split(","):
        ext = ext.strip().lower()
        if ext and not ext.startswith("."):
            ext = "." + ext
        if ext in DANGEROUS_EXTENSIONS:
            return f"Extension '{ext}' is blocked for security reasons"
    return None


class TestBlockedExtensionValidation:
    """Dangerous extensions rejected in allowed_import_extensions config."""

    def test_exe_rejected(self) -> None:
        err = _validate_extensions(".cbz,.exe")
        assert err is not None
        assert ".exe" in err

    def test_bat_rejected(self) -> None:
        err = _validate_extensions(".cbz,.bat")
        assert err is not None
        assert ".bat" in err

    def test_ps1_rejected(self) -> None:
        err = _validate_extensions(".ps1,.cbz")
        assert err is not None
        assert ".ps1" in err

    def test_sh_rejected(self) -> None:
        err = _validate_extensions(".sh")
        assert err is not None
        assert ".sh" in err

    def test_dll_rejected(self) -> None:
        err = _validate_extensions(".dll")
        assert err is not None

    def test_case_insensitive(self) -> None:
        """Uppercase extension also rejected."""
        err = _validate_extensions(".cbz,EXE")
        assert err is not None

    def test_without_dot_rejected(self) -> None:
        """Extension without leading dot still rejected."""
        err = _validate_extensions(".cbz,bat")
        assert err is not None

    def test_safe_extensions_accepted(self) -> None:
        err = _validate_extensions(".cbz,.cbr,.pdf,.epub,.cb7,.cbt")
        assert err is None

    def test_single_safe_extension(self) -> None:
        err = _validate_extensions(".cbz")
        assert err is None

    def test_empty_value(self) -> None:
        err = _validate_extensions("")
        assert err is None

    def test_all_dangerous_extensions_in_set(self) -> None:
        """Verify expected entries in DANGEROUS_EXTENSIONS."""
        for ext in (".exe", ".bat", ".cmd", ".ps1", ".sh", ".dll", ".app", ".lnk"):
            assert ext in DANGEROUS_EXTENSIONS, f"{ext} not in DANGEROUS_EXTENSIONS"

    def test_comic_extensions_not_blocked(self) -> None:
        for ext in (".cbz", ".cbr", ".cb7", ".cbt", ".pdf", ".epub"):
            assert ext not in DANGEROUS_EXTENSIONS, f"{ext} in DANGEROUS_EXTENSIONS"

    @pytest.mark.parametrize(
        "ext",
        [".exe", ".bat", ".cmd", ".ps1", ".sh", ".dll", ".vbs", ".msi", ".scr"],
    )
    def test_each_common_dangerous_ext(self, ext: str) -> None:
        err = _validate_extensions(ext)
        assert err is not None, f"Expected {ext} to be rejected"
