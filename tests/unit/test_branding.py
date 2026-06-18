"""Tests for terminal branding helpers."""

from __future__ import annotations

import pullbox
from pullbox.branding import display_version, startup_banner


def test_display_version_prefers_build_version(monkeypatch) -> None:
    monkeypatch.setenv("PULLBOX_BUILD_VERSION", "  v-test-build  ")

    assert display_version() == "v-test-build"


def test_display_version_falls_back_to_package_version(monkeypatch) -> None:
    monkeypatch.delenv("PULLBOX_BUILD_VERSION", raising=False)

    assert display_version() == pullbox.__version__


def test_startup_banner_omits_blank_version_and_keeps_width() -> None:
    banner = startup_banner("   ", width=24)
    lines = banner.splitlines()

    assert all(len(line) == 24 for line in lines)
    assert not any(line.strip().startswith("v") for line in lines)


def test_startup_banner_includes_trimmed_version() -> None:
    banner = startup_banner("  1.2.3  ", width=32)

    assert banner.splitlines()[-1].strip() == "v1.2.3"
