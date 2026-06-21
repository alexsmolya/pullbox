"""Contracts for static assets packaged into the production wheel."""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_production_package_includes_only_served_runtime_css() -> None:
    """Tailwind source CSS is needed in the repo but should not ship in the wheel."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["tool"]["setuptools"]["include-package-data"] is False

    package_data = pyproject["tool"]["setuptools"]["package-data"]["pullbox"]

    assert "ui/static/css/tailwind.css" in package_data
    assert "ui/static/css/input.css" not in package_data
    assert "ui/static/css/*.css" not in package_data


def test_production_package_includes_donation_qr_codes() -> None:
    """Donation QR codes live in a nested static directory that must ship."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]["pullbox"]

    assert "ui/static/img/donations/*.png" in package_data
    assert (REPO_ROOT / "src/pullbox/ui/static/img/donations/buy-me-a-coffee-qr.png").is_file()
    assert (REPO_ROOT / "src/pullbox/ui/static/img/donations/liberapay-qr.png").is_file()
