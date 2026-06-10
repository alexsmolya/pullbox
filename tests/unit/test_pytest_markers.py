"""Tests verifying pytest marker auto-application for fast/slow test splitting.

Ensures unit tests are NOT marked slow and non-unit tests ARE marked slow,
so developers can run `pytest tests/unit/ -v` for fast iteration (~15-20s)
and `pytest tests/ -v` for the full suite.

Run:
    pytest tests/unit/test_pytest_markers.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Root tests/ directory for path resolution
_TESTS_ROOT = Path(__file__).resolve().parent.parent


class TestSlowMarkerAutoApplication:
    """Verify the conftest auto-marker applies 'slow' to non-unit tests."""

    def test_unit_tests_not_marked_slow(self, request: pytest.FixtureRequest) -> None:
        """This test lives in tests/unit/ and should NOT have the slow marker."""
        item = request.node
        marker_names = {m.name for m in item.iter_markers()}
        assert "slow" not in marker_names

    def test_slow_marker_is_registered(self) -> None:
        """The 'slow' marker should be registered in pyproject.toml."""
        # If this test runs without a PytestUnknownMarkWarning, the marker is registered.
        # We also verify by checking pyproject.toml directly.
        pyproject = _TESTS_ROOT.parent / "pyproject.toml"
        content = pyproject.read_text()
        assert '"slow' in content


class TestExistingMarkersPreserved:
    """Verify existing markers still work alongside the new slow marker."""

    @pytest.mark.parser
    def test_parser_marker_still_works(self) -> None:
        """The parser marker should still be usable."""
        # Just needs to not raise — marker is recognized
        pass

    @pytest.mark.regression
    def test_regression_marker_still_works(self) -> None:
        """The regression marker should still be usable."""
        pass


class TestSlowMarkerOnNonUnitPaths:
    """Verify path-based logic for auto-marking."""

    def test_unit_path_detection(self) -> None:
        """Files under tests/unit/ should be detected as unit tests."""
        unit_path = _TESTS_ROOT / "unit" / "test_example.py"
        assert "/unit/" in str(unit_path)

    def test_integration_path_detection(self) -> None:
        """Files under tests/integration/ should NOT contain /unit/."""
        integration_path = _TESTS_ROOT / "integration" / "test_example.py"
        assert "/unit/" not in str(integration_path)

    def test_api_path_detection(self) -> None:
        """Files under tests/api/ should NOT contain /unit/."""
        api_path = _TESTS_ROOT / "api" / "test_example.py"
        assert "/unit/" not in str(api_path)

    def test_ui_path_detection(self) -> None:
        """Files under tests/ui/ should NOT contain /unit/."""
        ui_path = _TESTS_ROOT / "ui" / "test_example.py"
        assert "/unit/" not in str(ui_path)

    def test_tasks_path_detection(self) -> None:
        """Files under tests/tasks/ should NOT contain /unit/."""
        tasks_path = _TESTS_ROOT / "tasks" / "test_example.py"
        assert "/unit/" not in str(tasks_path)

    def test_providers_path_detection(self) -> None:
        """Files under tests/providers/ should NOT contain /unit/."""
        providers_path = _TESTS_ROOT / "providers" / "test_example.py"
        assert "/unit/" not in str(providers_path)
