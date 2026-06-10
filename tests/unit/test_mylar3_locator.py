"""Unit tests for Mylar3 database locator."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from pullbox.core.mylar3_locator import (
    Mylar3DbCandidate,
    _find_via_docker,
    _find_via_filesystem,
    _run_command,
    locate_mylar3_db,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestRunCommand:
    """Test subprocess helper."""

    @pytest.mark.asyncio
    async def test_successful_command(self) -> None:
        result = await _run_command("echo", "hello")
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_failed_command(self) -> None:
        result = await _run_command("false")
        assert result is None

    @pytest.mark.asyncio
    async def test_nonexistent_command(self) -> None:
        result = await _run_command("nonexistent_command_xyz")
        assert result is None


class TestFindViaDocker:
    """Test Docker-based detection."""

    @pytest.mark.asyncio
    async def test_no_docker(self) -> None:
        with patch(
            "pullbox.core.mylar3_locator._run_command",
            return_value=None,
        ):
            results = await _find_via_docker()
            assert results == []

    @pytest.mark.asyncio
    async def test_no_mylar_containers(self) -> None:
        with patch(
            "pullbox.core.mylar3_locator._run_command",
            return_value="nginx\tnginx:latest",
        ):
            results = await _find_via_docker()
            assert results == []

    @pytest.mark.asyncio
    async def test_bind_mount_found(self, tmp_path: Path) -> None:
        db_file = tmp_path / "mylar.db"
        db_file.touch()

        docker_ps = "mylar3\tlscr.io/linuxserver/mylar3:latest"
        inspect_data = json.dumps(
            [
                {
                    "Mounts": [
                        {
                            "Destination": "/config",
                            "Source": str(tmp_path),
                            "Type": "bind",
                        },
                        {
                            "Destination": "/data",
                            "Source": "/mnt/storage",
                            "Type": "bind",
                        },
                    ]
                }
            ]
        )

        call_count = 0

        async def mock_run(*args: str) -> str | None:
            nonlocal call_count
            call_count += 1
            if "ps" in args:
                return docker_ps
            if "inspect" in args:
                return inspect_data
            return None

        with patch("pullbox.core.mylar3_locator._run_command", side_effect=mock_run):
            results = await _find_via_docker()

        assert len(results) == 1
        assert results[0].source == "docker_bind_mount"
        assert results[0].ready is True
        assert results[0].path_map == {"/data": "/mnt/storage"}

    @pytest.mark.asyncio
    async def test_bind_mount_db_missing(self, tmp_path: Path) -> None:
        # tmp_path exists but no mylar.db inside
        docker_ps = "mylar3\tmylar:latest"
        inspect_data = json.dumps(
            [
                {
                    "Mounts": [
                        {
                            "Destination": "/config",
                            "Source": str(tmp_path),
                            "Type": "bind",
                        }
                    ]
                }
            ]
        )

        async def mock_run(*args: str) -> str | None:
            if "ps" in args:
                return docker_ps
            if "inspect" in args:
                return inspect_data
            return None

        with patch("pullbox.core.mylar3_locator._run_command", side_effect=mock_run):
            results = await _find_via_docker()

        assert len(results) == 1
        assert results[0].ready is False
        assert "not found" in (results[0].note or "")

    @pytest.mark.asyncio
    async def test_named_volume(self) -> None:
        docker_ps = "mylar3\tmylar:latest"
        inspect_data = json.dumps(
            [
                {
                    "Mounts": [
                        {
                            "Destination": "/config",
                            "Source": "mylar3_config",
                            "Type": "volume",
                        }
                    ]
                }
            ]
        )

        async def mock_run(*args: str) -> str | None:
            if "ps" in args:
                return docker_ps
            if "inspect" in args:
                return inspect_data
            return None

        with patch("pullbox.core.mylar3_locator._run_command", side_effect=mock_run):
            results = await _find_via_docker()

        assert len(results) == 1
        assert results[0].source == "docker_named_volume"
        assert results[0].ready is False
        assert "docker cp" in (results[0].note or "")

    @pytest.mark.asyncio
    async def test_no_config_mount(self) -> None:
        docker_ps = "mylar3\tmylar:latest"
        inspect_data = json.dumps([{"Mounts": []}])

        async def mock_run(*args: str) -> str | None:
            if "ps" in args:
                return docker_ps
            if "inspect" in args:
                return inspect_data
            return None

        with patch("pullbox.core.mylar3_locator._run_command", side_effect=mock_run):
            results = await _find_via_docker()

        assert len(results) == 1
        assert results[0].ready is False


class TestFindViaFilesystem:
    """Test filesystem-based detection."""

    @pytest.mark.asyncio
    async def test_finds_known_path(self, tmp_path: Path) -> None:
        mylar_dir = tmp_path / ".mylar"
        mylar_dir.mkdir()
        (mylar_dir / "mylar.db").touch()

        with patch("pathlib.Path.home", return_value=tmp_path):
            results = await _find_via_filesystem()

        assert len(results) >= 1
        paths = [r.path for r in results]
        assert str(mylar_dir / "mylar.db") in paths

    @pytest.mark.asyncio
    async def test_no_paths_found(self, tmp_path: Path) -> None:
        # Use an empty tmp_path as home so nothing matches
        with patch("pathlib.Path.home", return_value=tmp_path):
            results = await _find_via_filesystem()

        # May find system paths, but tmp_path-based ones won't exist
        # Just verify it doesn't crash
        assert isinstance(results, list)


class TestFindViaDockerEdgeCases:
    """Edge cases in Docker detection."""

    @pytest.mark.asyncio
    async def test_malformed_ps_line_no_tab(self) -> None:
        """Line without tab separator is skipped."""

        async def mock_run(*args: str) -> str | None:
            if "ps" in args:
                return "mylar3_no_tab"
            return None

        with patch("pullbox.core.mylar3_locator._run_command", side_effect=mock_run):
            results = await _find_via_docker()
        assert results == []

    @pytest.mark.asyncio
    async def test_inspect_returns_none(self) -> None:
        """Container inspect fails gracefully."""

        async def mock_run(*args: str) -> str | None:
            if "ps" in args:
                return "mylar3\tmylar:latest"
            if "inspect" in args:
                return None
            return None

        with patch("pullbox.core.mylar3_locator._run_command", side_effect=mock_run):
            results = await _find_via_docker()
        assert results == []

    @pytest.mark.asyncio
    async def test_inspect_invalid_json(self) -> None:
        """Malformed inspect JSON handled gracefully."""

        async def mock_run(*args: str) -> str | None:
            if "ps" in args:
                return "mylar3\tmylar:latest"
            if "inspect" in args:
                return "not json"
            return None

        with patch("pullbox.core.mylar3_locator._run_command", side_effect=mock_run):
            results = await _find_via_docker()
        assert results == []

    @pytest.mark.asyncio
    async def test_inspect_empty_array(self) -> None:
        """Empty inspect array handled gracefully."""

        async def mock_run(*args: str) -> str | None:
            if "ps" in args:
                return "mylar3\tmylar:latest"
            if "inspect" in args:
                return "[]"
            return None

        with patch("pullbox.core.mylar3_locator._run_command", side_effect=mock_run):
            results = await _find_via_docker()
        assert results == []

    @pytest.mark.asyncio
    async def test_docker_exception_swallowed(self) -> None:
        """Top-level exception in _find_via_docker doesn't propagate."""

        async def mock_run(*args: str) -> str | None:
            msg = "boom"
            raise RuntimeError(msg)

        with patch("pullbox.core.mylar3_locator._run_command", side_effect=mock_run):
            results = await _find_via_docker()
        assert results == []


class TestFindViaFilesystemEdgeCases:
    """Edge cases in filesystem detection."""

    @pytest.mark.asyncio
    async def test_glob_match(self, tmp_path: Path) -> None:
        """Glob pattern matching finds mylar.db."""
        docker_dir = tmp_path / "docker" / "custom_name"
        docker_dir.mkdir(parents=True)
        (docker_dir / "mylar.db").touch()

        with patch("pathlib.Path.home", return_value=tmp_path):
            results = await _find_via_filesystem()

        paths = [r.path for r in results]
        assert str(docker_dir / "mylar.db") in paths

    @pytest.mark.asyncio
    async def test_filesystem_exception_swallowed(self) -> None:
        """Exception in _check_paths doesn't propagate."""
        with patch(
            "asyncio.to_thread",
            side_effect=RuntimeError("boom"),
        ):
            results = await _find_via_filesystem()
        assert results == []


class TestLocateMylar3Db:
    """Test the top-level locate function."""

    @pytest.mark.asyncio
    async def test_deduplication(self) -> None:
        candidate = Mylar3DbCandidate(path="/tmp/mylar.db", source="filesystem", label="test")
        with (
            patch(
                "pullbox.core.mylar3_locator._find_via_docker",
                return_value=[candidate],
            ),
            patch(
                "pullbox.core.mylar3_locator._find_via_filesystem",
                return_value=[candidate],  # same path
            ),
        ):
            results = await locate_mylar3_db()

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_empty_results(self) -> None:
        with (
            patch(
                "pullbox.core.mylar3_locator._find_via_docker",
                return_value=[],
            ),
            patch(
                "pullbox.core.mylar3_locator._find_via_filesystem",
                return_value=[],
            ),
        ):
            results = await locate_mylar3_db()

        assert results == []
