"""RAR backend selection for CBR support."""

from __future__ import annotations

import pytest


def test_configure_rarfile_backend_selects_official_unrar(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pullbox should force rarfile through the official unrar-compatible CLI."""
    import rarfile

    from pullbox.core.rar_backend import configure_rarfile_backend

    selected: list[dict[str, bool]] = []
    expected_setup = object()
    rarfile.CURRENT_SETUP = object()

    def fake_tool_setup(**kwargs: bool):
        selected.append(kwargs)
        return expected_setup

    monkeypatch.setattr(rarfile, "tool_setup", fake_tool_setup)

    setup = configure_rarfile_backend()

    assert setup is expected_setup
    assert selected == [
        {
            "unrar": True,
            "unar": False,
            "bsdtar": False,
            "sevenzip": False,
            "sevenzip2": False,
            "force": True,
        }
    ]
    assert rarfile.UNRAR_TOOL == "unrar"
    assert rarfile.ORIG_UNRAR_TOOL == "unrar"
    assert rarfile.CURRENT_SETUP is None


def test_configure_rarfile_backend_raises_clear_error_when_unrar_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing official UnRAR should surface as an actionable Pullbox error."""
    import rarfile

    from pullbox.core.rar_backend import RarBackendUnavailableError, configure_rarfile_backend

    def fake_tool_setup(**_kwargs: bool):
        raise rarfile.RarCannotExec("Cannot find working tool")

    monkeypatch.setattr(rarfile, "tool_setup", fake_tool_setup)

    with pytest.raises(RarBackendUnavailableError, match="official UnRAR"):
        configure_rarfile_backend()
